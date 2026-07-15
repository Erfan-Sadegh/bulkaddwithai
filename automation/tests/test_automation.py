from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unittest.mock import patch

from automation import runner
from automation.collectors import CollectorError, collect_clarity, collect_local_logs, collect_product_events
from automation.dashboard import rebuild_dashboard, write_run_report
from automation.models import Candidate, Signal
from automation.security import (
    redact_text,
    sanitize,
    digest_test_patch,
    validate_diff,
    validate_reproducer_diff,
)
from automation.simulation import run_self_improvement_simulation
from automation.state import (
    apply_retention,
    completed_rollout_days,
    phase_for_completed_runs,
    remediation_allowed,
)


POLICY = {
    "limits": {"max_changed_files": 3, "max_changed_lines": 20},
    "forbidden_paths": ["backend/alembic/**", "automation/policy.json", "frontend/package.json"],
    "test_file_patterns": ["backend/tests/test_*.py", "frontend/src/*.test.tsx"],
    "sources": {"local_log_globs": ["*.log"], "max_local_log_bytes": 100_000},
}


class AutomationTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt" and shutil.which("powershell"), "Windows PowerShell only")
    def test_single_secret_setup_preserves_previously_saved_credentials(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            script = Path(__file__).resolve().parents[1] / "configure-secrets.ps1"
            environment = {**os.environ, "BULKADD_TEST_SECRET": "synthetic-secret"}
            for name in ("CLARITY_API_TOKEN", "GITHUB_TOKEN"):
                subprocess.run(
                    [
                        "powershell", "-NoProfile", "-File", str(script),
                        "-StateRoot", str(state), "-Only", name,
                        "-ValueFromEnvironment", "BULKADD_TEST_SECRET",
                    ],
                    check=True,
                    text=True,
                    capture_output=True,
                    env=environment,
                )
            result = subprocess.run(
                [
                    "powershell", "-NoProfile", "-Command",
                    f"@((Import-Clixml -LiteralPath '{state / 'collector-secrets.clixml'}').UserName) -join ','",
                ],
                check=True,
                text=True,
                capture_output=True,
            )

        self.assertEqual(result.stdout.strip(), "CLARITY_API_TOKEN,GITHUB_TOKEN")

    def test_local_log_collector_groups_structured_and_legacy_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "app.log").write_text(
                json.dumps({"event": "processing_job_failed", "stage": "vision", "job_id": 7})
                + "\nprocessing_job_failed stage=vision job_id=8 access_token=do-not-copy\n",
                encoding="utf-8",
            )

            signals = collect_local_logs(root, POLICY)

            self.assertEqual(len(signals), 1)
            self.assertEqual(signals[0].count, 2)
            self.assertEqual(signals[0].priority, "high")
            self.assertNotIn("access_token", signals[0].evidence)

    def test_redaction_removes_query_and_sensitive_mappings(self):
        self.assertEqual(redact_text("https://host/callback?code=secret"), "https://host/callback")
        scrubbed = sanitize({"access_token": "secret", "safe": "Bearer abcdefghijklmnop"})
        self.assertEqual(scrubbed["access_token"], "[REDACTED]")
        self.assertEqual(scrubbed["safe"], "[REDACTED]")

    def test_guard_rejects_forbidden_paths_secrets_and_missing_tests(self):
        errors = validate_diff(
            ["frontend/package.json", "frontend/src/App.tsx"],
            "+Authorization=Bearer abcdefghijklmnop\n+change",
            POLICY,
        )
        self.assertGreaterEqual(len(errors), 3)

    def test_guard_accepts_small_tested_change(self):
        errors = validate_diff(
            ["backend/app/services.py", "backend/tests/test_api_flow.py"],
            "+safe change\n-old line",
            POLICY,
        )
        self.assertEqual(errors, [])

    def test_reproducer_gate_allows_tests_only(self):
        self.assertEqual(
            validate_reproducer_diff(["backend/tests/test_api_flow.py"], POLICY),
            [],
        )

    def test_reproducer_gate_rejects_source_or_no_test_changes(self):
        errors = validate_reproducer_diff(
            ["backend/tests/test_api_flow.py", "backend/app/services.py"],
            POLICY,
        )
        self.assertTrue(any("source" in error.lower() for error in errors))
        self.assertTrue(validate_reproducer_diff(["README.md"], POLICY))

    def test_test_patch_digest_proves_fixer_did_not_rewrite_regression_test(self):
        before = digest_test_patch("diff --git a/backend/tests/test_x.py\n+assert broken")
        same = digest_test_patch("diff --git a/backend/tests/test_x.py\n+assert broken")
        changed = digest_test_patch("diff --git a/backend/tests/test_x.py\n+assert fixed")

        self.assertEqual(before, same)
        self.assertNotEqual(before, changed)

    def test_product_event_collector_maps_safe_production_events(self):
        payload = [
            {
                "event": "processing_job_failed",
                "severity": "error",
                "count": 4,
                "last_seen_at": "2026-07-15T00:00:00Z",
                "stage": "vision_extracting",
                "code": "provider_temporary",
            }
        ]
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                }
            )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].source, "product_events")
        self.assertEqual(signals[0].count, 4)
        self.assertEqual(signals[0].evidence["stage"], "vision_extracting")

    def test_product_event_collector_keeps_exact_control_for_product_rage_click(self):
        payload = [
            {
                "event": "ui_rage_click",
                "control": "build_product_list",
                "click_count": 5,
                "count": 1,
                "last_seen_at": "2026-07-15T00:00:00Z",
            }
        ]
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                }
            )

        self.assertEqual(signals[0].event, "ui_rage_click")
        self.assertEqual(signals[0].evidence["control"], "build_product_list")
        self.assertEqual(signals[0].evidence["click_count"], 5)

    def test_product_event_collector_detects_repeated_picker_opens_without_terminal_event(self):
        payload = [
            {
                "event": "image_picker_opened",
                "control": "photo_drop_zone",
                "attempt_id": "11111111-1111-4111-8111-111111111111",
                "last_seen_at": "2026-07-15T00:01:00Z",
            },
            {
                "event": "image_picker_opened",
                "control": "photo_drop_zone",
                "attempt_id": "22222222-2222-4222-8222-222222222222",
                "last_seen_at": "2026-07-15T00:02:00Z",
            },
            {
                "event": "image_picker_opened",
                "control": "add_photo_button",
                "attempt_id": "33333333-3333-4333-8333-333333333333",
                "last_seen_at": "2026-07-15T00:03:00Z",
            },
            {
                "event": "image_files_selected",
                "control": "add_photo_button",
                "attempt_id": "33333333-3333-4333-8333-333333333333",
                "file_count": 1,
                "last_seen_at": "2026-07-15T00:03:01Z",
            },
        ]
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                }
            )

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].event, "image_picker_unresponsive")
        self.assertEqual(signals[0].count, 2)
        self.assertEqual(signals[0].evidence["control"], "photo_drop_zone")

    def test_product_event_collector_gives_picker_attempts_time_to_finish(self):
        payload = [
            {
                "event": "image_picker_opened",
                "control": "photo_drop_zone",
                "attempt_id": attempt,
                "last_seen_at": f"2026-07-15T00:0{minute}:00Z",
            }
            for attempt, minute in [
                ("11111111-1111-4111-8111-111111111111", 8),
                ("22222222-2222-4222-8222-222222222222", 9),
            ]
        ]
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                },
                now=datetime(2026, 7, 15, 0, 10, tzinfo=timezone.utc),
            )

        self.assertEqual(signals, [])

    def test_product_event_collector_never_guesses_without_credentials(self):
        with self.assertRaises(CollectorError):
            collect_product_events({})

    def test_clarity_collector_uses_metric_subtotal_not_all_sessions(self):
        payload = [
            {
                "metricName": "DeadClickCount",
                "information": [
                    {"sessionsCount": "11", "subTotal": "6"},
                    {"sessionsCount": "33", "subTotal": "2"},
                ],
            },
            {
                "metricName": "RageClickCount",
                "information": [{"sessionsCount": "44", "subTotal": "7"}],
            },
            {
                "metricName": "ScriptErrorCount",
                "information": [{"sessionsCount": "44", "subTotal": "3"}],
            },
            {
                "metricName": "Traffic",
                "information": [
                    {"totalSessionCount": "11"},
                    {"totalSessionCount": "33"},
                ],
            },
        ]
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_clarity({"CLARITY_API_TOKEN": "read-only-token"})

        by_event = {signal.event: signal for signal in signals}
        self.assertEqual(by_event["dead_click_count"].count, 8)
        self.assertEqual(by_event["rage_click_count"].count, 7)
        self.assertEqual(by_event["script_error_count"].count, 3)
        self.assertEqual(by_event["clarity_traffic"].count, 44)

    def test_product_event_collector_only_requests_the_last_24_hours(self):
        now = datetime(2026, 7, 15, 0, 0, tzinfo=timezone.utc)
        with patch("automation.collectors._get_json", return_value=[]) as request:
            collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                },
                now=now,
            )

        url = request.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        self.assertEqual(query["since"], ["2026-07-14T00:00:00+00:00"])

    def test_product_event_collector_finds_repeated_actions_with_no_terminal_outcome(self):
        now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        payload = [
            {
                "event": "ui_action_started",
                "control": "publish_basalam",
                "attempt_id": attempt_id,
                "last_seen_at": "2026-07-15T11:50:00+00:00",
            }
            for attempt_id in (
                "11111111-1111-4111-8111-111111111111",
                "22222222-2222-4222-8222-222222222222",
            )
        ]
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                },
                now=now,
            )

        stalled = next(signal for signal in signals if signal.event == "ui_action_unresponsive")
        self.assertEqual(stalled.count, 2)
        self.assertEqual(stalled.evidence["control"], "publish_basalam")

    def test_product_event_collector_does_not_call_completed_actions_unresponsive(self):
        now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        payload = []
        for attempt_id in (
            "11111111-1111-4111-8111-111111111111",
            "22222222-2222-4222-8222-222222222222",
        ):
            payload.extend(
                [
                    {
                        "event": "ui_action_started",
                        "control": "publish_basalam",
                        "attempt_id": attempt_id,
                        "last_seen_at": "2026-07-15T11:50:00+00:00",
                    },
                    {
                        "event": "ui_action_accepted",
                        "control": "publish_basalam",
                        "attempt_id": attempt_id,
                        "last_seen_at": "2026-07-15T11:50:01+00:00",
                    },
                ]
            )
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                },
                now=now,
            )

        self.assertNotIn("ui_action_unresponsive", {signal.event for signal in signals})

    def test_full_self_improvement_cycle_in_an_isolated_repository(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = run_self_improvement_simulation(Path(temporary))

        self.assertEqual(result["signal_count"], 1)
        self.assertEqual(result["diagnosis_status"], "reproduced")
        self.assertTrue(result["source_unchanged_after_diagnosis"])
        self.assertEqual(result["fix_status"], "fixed_in_test")
        self.assertEqual(result["regression_before_exit"], 1)
        self.assertEqual(result["final_test_exit"], 0)
        self.assertEqual(result["review_verdict"], "approve")
        self.assertTrue(result["dashboard_created"])
        self.assertTrue(result["worktree_cleaned"])

    def test_every_run_diagnoses_but_never_auto_fixes(self):
        self.assertEqual(phase_for_completed_runs(0), ("diagnosis", 0))
        self.assertEqual(phase_for_completed_runs(100), ("diagnosis", 0))

    def test_scheduled_run_reproduces_candidates_without_calling_fixer(self):
        signal = Signal(source="product_events", event="processing_job_failed", priority="high", summary_fa="failed")
        candidate = Candidate(
            fingerprint="candidate-1",
            title_fa="خطای خواندن عکس",
            problem_fa="عکس سالم خوانده نشده است.",
            priority="high",
            confidence=0.9,
            evidence=[signal.to_dict()],
            reproducible_hint="با تصویر ساختگی بازسازی شود.",
        )
        policy = {"limits": {"retention_days": 30, "max_diagnoses_per_run": 3}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with (
                patch.object(runner, "collect_all", return_value=[signal]),
                patch.object(runner, "triage", return_value=[candidate]),
                patch.object(runner, "attempt_diagnosis", return_value={"fingerprint": "candidate-1", "status": "reproduced"}) as diagnose,
                patch.object(runner, "attempt_fix", side_effect=AssertionError("scheduled discovery must not fix")),
            ):
                exit_code = runner.run_once(root, root / "state", policy, False, False, True)

            report = json.loads(next((root / "state" / "runs").glob("*/report.json")).read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        diagnose.assert_called_once()
        self.assertEqual(report["phase"], "diagnosis")
        self.assertEqual(report["diagnoses"][0]["status"], "reproduced")
        self.assertEqual(report["fixes"], [])

    def test_triage_falls_back_to_product_failure_when_model_returns_no_candidate(self):
        product_failure = Signal(
            source="product_events",
            event="image_upload_rejected",
            priority="ux",
            summary_fa="four uploads were rejected",
            count=4,
        )
        clarity_lead = Signal(
            source="clarity",
            event="dead_click_count",
            priority="ux",
            summary_fa="twenty eight dead clicks",
            count=28,
        )
        policy = {"limits": {"max_candidate_signals": 20}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "triage.json"

            def empty_triage(*_args, **_kwargs):
                output.write_text('{"candidates": []}', encoding="utf-8")
                return subprocess.CompletedProcess([], 0, "", "")

            with (
                patch.object(runner, "_find_command", return_value="codex"),
                patch.object(runner, "_run", side_effect=empty_triage),
            ):
                candidates = runner.triage(root, root, [product_failure, clarity_lead], policy, False)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].fingerprint, product_failure.fingerprint)
        self.assertEqual({item["event"] for item in candidates[0].evidence}, {"image_upload_rejected", "dead_click_count"})

    def test_backend_gate_uses_a_creatable_single_level_pytest_temp_directory(self):
        policy = json.loads((Path(__file__).parents[1] / "policy.json").read_text(encoding="utf-8"))
        backend_gate = next(gate for gate in policy["gates"] if gate["name"] == "backend tests")

        self.assertIn("--basetemp .pytest-tmp-autonomy", backend_gate["command"])
        self.assertNotIn("--basetemp .pytest-tmp\\autonomy", backend_gate["command"])

    def test_three_hour_monitoring_does_not_accelerate_daily_rollout(self):
        runs = [
            {
                "kind": "scheduled",
                "status": "completed",
                "started_at": f"2026-07-15T{hour:02d}:00:00+00:00",
            }
            for hour in range(0, 24, 3)
        ]
        runs.append(
            {
                "kind": "scheduled",
                "status": "completed",
                "started_at": "2026-07-16T00:00:00+00:00",
            }
        )

        self.assertEqual(completed_rollout_days(runs), 2)

    def test_remediation_is_limited_to_once_per_day_while_monitoring_continues(self):
        now = datetime(2026, 7, 16, 0, 0, tzinfo=timezone.utc)
        recent = [
            {
                "kind": "scheduled",
                "status": "completed",
                "remediation_window": True,
                "started_at": "2026-07-15T21:00:00+00:00",
            }
        ]

        self.assertFalse(remediation_allowed(recent, now))
        self.assertTrue(remediation_allowed(recent, now + timedelta(hours=24)))

    def test_dashboard_is_local_and_retention_keeps_open_prs(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            old = (datetime.now(timezone.utc) - timedelta(days=40)).isoformat()
            removable = root / "runs" / "old-removable"
            protected = root / "runs" / "old-protected"
            write_run_report(removable, {"run_id": "old-removable", "started_at": old, "status": "completed", "phase": "report_only", "fixes": []})
            write_run_report(protected, {"run_id": "old-protected", "started_at": old, "status": "completed", "phase": "guarded", "fixes": [{"pr_state": "open"}]})

            dashboard = rebuild_dashboard(root)
            self.assertTrue(dashboard.exists())
            self.assertIn("داشبورد عامل", dashboard.read_text(encoding="utf-8"))
            apply_retention(root, 30)
            self.assertFalse(removable.exists())
            self.assertTrue(protected.exists())

    def test_run_report_explains_time_outcome_uncertainty_and_next_action_in_plain_persian(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "runs" / "20260714T234702Z"
            report = {
                "run_id": "20260714T234702Z",
                "started_at": "2026-07-14T23:47:02+00:00",
                "finished_at": "2026-07-14T23:47:31+00:00",
                "status": "completed",
                "phase": "report_only",
                "source_health": {
                    "local_logs": "ok (0)",
                    "product_events": "ok (4)",
                    "sentry": "ok (0)",
                    "clarity": "ok (1)",
                    "production_health": "ok (0)",
                },
                "signals": [
                    {
                        "source": "product_events",
                        "event": "image_upload_rejected",
                        "count": 4,
                        "occurred_at": "2026-07-14T23:00:57+00:00",
                        "evidence": {"batch_id": 5},
                    },
                    {
                        "source": "clarity",
                        "event": "clarity_traffic",
                        "count": 40,
                        "evidence": {"observation_count": 40},
                    },
                ],
                "candidates": [
                    {
                        "fingerprint": "upload",
                        "title_fa": "رد شدن بارگذاری تصویر",
                        "problem_fa": "چهار تصویر در یک batch رد شده‌اند.",
                        "confidence": 0.68,
                        "status": "detected",
                        "evidence": [],
                    }
                ],
                "fixes": [],
            }

            page = write_run_report(run_dir, report).read_text(encoding="utf-8")

            self.assertIn("۱۵ ژوئیه ۲۰۲۶، ساعت ۰۳:۱۷", page)
            self.assertIn("مدت اجرا: ۲۹ ثانیه", page)
            self.assertIn("هر ۵ منبع با موفقیت بررسی شدند", page)
            self.assertIn("۴ بار", page)
            self.assertIn("۴۰ نشست کاربری", page)
            self.assertIn("هنوز باگ اثبات‌شده نیست", page)
            self.assertIn("فعلاً کاری از شما لازم نیست", page)
            self.assertIn("عامل در این مرحله اجازه تغییر کد نداشت", page)
            self.assertIn("اطمینان تحلیل: ۶۸٪", page)

    def test_dashboard_uses_human_time_and_rebuilds_existing_run_pages(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "runs" / "opaque-id"
            run_dir.mkdir(parents=True)
            (run_dir / "report.json").write_text(
                json.dumps(
                    {
                        "run_id": "opaque-id",
                        "started_at": "2026-07-14T23:47:02+00:00",
                        "finished_at": "2026-07-14T23:47:31+00:00",
                        "status": "completed",
                        "phase": "report_only",
                        "source_health": {"sentry": "ok (0)"},
                        "signals": [],
                        "candidates": [],
                        "fixes": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (run_dir / "report.html").write_text("OLD DESIGN", encoding="utf-8")
            (root / "state.json").write_text(
                json.dumps({"runs": [{"run_id": "opaque-id", "kind": "scheduled"}]}),
                encoding="utf-8",
            )

            dashboard = rebuild_dashboard(root)
            index = dashboard.read_text(encoding="utf-8")
            rebuilt_report = (run_dir / "report.html").read_text(encoding="utf-8")

            self.assertIn("آخرین اجرا", index)
            self.assertIn("۱۵ ژوئیه ۲۰۲۶، ساعت ۰۳:۱۷", index)
            self.assertIn("شبانهٔ خودکار", index)
            self.assertIn("مشکل قابل اقدامی پیدا نشد", index)
            self.assertNotIn("OLD DESIGN", rebuilt_report)


if __name__ == "__main__":
    unittest.main()
