from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unittest.mock import patch

from automation import runner
from automation import collectors
from automation.collectors import (
    CollectorError,
    collect_browser_probe,
    collect_clarity,
    collect_local_logs,
    collect_product_events,
    collect_ux_contract,
)
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
                json.dumps(
                    {
                        "event": "processing_job_failed",
                        "stage": "vision",
                        "job_id": 7,
                        "request_id": "raw-session-id",
                    }
                )
                + "\nprocessing_job_failed stage=vision job_id=8 request_id=raw-session-id "
                "session_key=hashed-session access_token=do-not-copy\n",
                encoding="utf-8",
            )

            signals = collect_local_logs(root, POLICY)

            self.assertEqual(len(signals), 1)
            self.assertEqual(signals[0].count, 2)
            self.assertEqual(signals[0].priority, "high")
            self.assertNotIn("access_token", signals[0].evidence)
            self.assertNotIn("request_id", signals[0].evidence)
            self.assertNotIn("session_key", signals[0].evidence)

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

    def test_product_event_collector_promotes_oauth_restore_data_loss_signal(self):
        payload = [
            {
                "event": "basalam_oauth_restore_failed",
                "severity": "error",
                "count": 2,
                "last_seen_at": "2026-07-15T00:00:00Z",
                "stage": "items",
                "reason": "count_mismatch",
                "expected_item_count": 3,
                "restored_item_count": 0,
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
        self.assertEqual(signals[0].event, "basalam_oauth_restore_failed")
        self.assertEqual(signals[0].priority, "urgent")
        self.assertEqual(signals[0].evidence["expected_item_count"], 3)
        self.assertEqual(signals[0].evidence["restored_item_count"], 0)
        self.assertIn("OAuth", signals[0].summary_fa)

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

    def test_product_event_collector_keeps_safe_validation_field(self):
        payload = [
            {
                "event": "ui_action_blocked",
                "control": "publish_basalam",
                "outcome": "validation",
                "failure_field": "package_weight_grams",
                "count": 3,
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

        self.assertEqual(signals[0].event, "ui_action_blocked")
        self.assertEqual(signals[0].evidence["control"], "publish_basalam")
        self.assertEqual(signals[0].evidence["failure_field"], "package_weight_grams")
        self.assertIn("وزن با بسته‌بندی", signals[0].summary_fa)
        self.assertIn("ثبت در باسلام", signals[0].summary_fa)

    def test_validation_fields_have_distinct_signal_fingerprints(self):
        payload = [
            {
                "event": "ui_action_blocked",
                "control": "publish_basalam",
                "outcome": "validation",
                "failure_field": field,
                "last_seen_at": "2026-07-15T00:00:00Z",
            }
            for field in ("stock", "package_weight_grams")
        ]
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                }
            )

        self.assertEqual(len({signal.fingerprint for signal in signals}), 2)

    def test_validation_without_a_field_uses_a_validation_fallback_summary(self):
        payload = [
            {
                "event": "ui_action_blocked",
                "control": "publish_basalam",
                "outcome": "validation",
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

        self.assertIn("اعتبارسنجی", signals[0].summary_fa)
        self.assertNotIn("وضعیت فعلی صفحه", signals[0].summary_fa)

    def test_product_event_collector_groups_exact_dead_clicks_by_control(self):
        payload = [
            {
                "event": "ui_dead_click",
                "control": "build_product_list",
                "session_key": session,
                "last_seen_at": f"2026-07-15T00:0{index}:00Z",
            }
            for index, session in ((3, "session-c"), (2, "session-b"), (1, "session-a"))
        ]
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                }
            )

        dead = [signal for signal in signals if signal.event == "ui_dead_click"]
        self.assertEqual(len(dead), 1)
        self.assertEqual(dead[0].count, 3)
        self.assertEqual(dead[0].evidence["control"], "build_product_list")
        self.assertEqual(dead[0].occurred_at, "2026-07-15T00:03:00Z")
        self.assertNotIn("session", json.dumps(dead[0].to_dict()))

    def test_product_event_collector_correlates_rage_and_dead_click_in_one_session(self):
        payload = [
            {
                "event": "ui_rage_click",
                "control": "publish_basalam",
                "session_key": "same-session",
                "click_count": 4,
                "last_seen_at": "2026-07-15T00:01:00Z",
            },
            {
                "event": "ui_dead_click",
                "control": "publish_basalam",
                "session_key": "same-session",
                "last_seen_at": "2026-07-15T00:01:02Z",
            },
        ]
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                }
            )

        friction = next(signal for signal in signals if signal.event == "ui_control_friction")
        self.assertEqual(friction.evidence["control"], "publish_basalam")
        self.assertEqual(friction.evidence["symptoms"], ["rage_click", "dead_click"])

    def test_product_event_collector_correlates_rage_and_stall_only_inside_one_anonymous_session(self):
        now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        payload = [
            {
                "event": "ui_rage_click",
                "control": "photo_drop_zone",
                "session_key": "same-session",
                "click_count": 4,
                "last_seen_at": "2026-07-15T11:50:00+00:00",
            },
            {
                "event": "image_picker_opened",
                "control": "photo_drop_zone",
                "session_key": "same-session",
                "attempt_id": "11111111-1111-4111-8111-111111111111",
                "last_seen_at": "2026-07-15T11:51:00+00:00",
            },
            {
                "event": "ui_rage_click",
                "control": "add_photo_button",
                "session_key": "different-session-a",
                "click_count": 4,
                "last_seen_at": "2026-07-15T11:52:00+00:00",
            },
            {
                "event": "image_picker_opened",
                "control": "add_photo_button",
                "session_key": "different-session-b",
                "attempt_id": "22222222-2222-4222-8222-222222222222",
                "last_seen_at": "2026-07-15T11:53:00+00:00",
            },
            {
                "event": "ui_rage_click",
                "control": "build_product_list",
                "session_key": "same-session-different-controls",
                "click_count": 4,
                "last_seen_at": "2026-07-15T11:54:00+00:00",
            },
            {
                "event": "ui_action_started",
                "control": "publish_basalam",
                "session_key": "same-session-different-controls",
                "attempt_id": "33333333-3333-4333-8333-333333333333",
                "last_seen_at": "2026-07-15T11:55:00+00:00",
            },
        ]
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                },
                now=now,
            )

        friction = [signal for signal in signals if signal.event == "ui_control_friction"]
        self.assertEqual(len(friction), 1)
        self.assertEqual(friction[0].evidence["control"], "photo_drop_zone")
        self.assertEqual(friction[0].evidence["symptoms"], ["rage_click", "picker_unresponsive"])
        self.assertNotIn("request_id", friction[0].evidence)
        serialized = json.dumps([signal.to_dict() for signal in signals])
        self.assertNotIn("request_id", serialized)
        self.assertNotIn("session_key", serialized)
        self.assertNotIn("anonymous_session_fingerprint", serialized)
        self.assertNotIn("same-session", serialized)
        self.assertNotIn("different-session", serialized)

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

    def test_terminal_event_from_another_session_and_control_does_not_hide_a_stall(self):
        now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        attempt_id = "11111111-1111-4111-8111-111111111111"
        payload = [
            {
                "event": "ui_rage_click",
                "control": "photo_drop_zone",
                "session_key": "session-a",
                "click_count": 4,
                "last_seen_at": "2026-07-15T11:50:00+00:00",
            },
            {
                "event": "image_picker_opened",
                "control": "photo_drop_zone",
                "session_key": "session-a",
                "attempt_id": attempt_id,
                "last_seen_at": "2026-07-15T11:50:01+00:00",
            },
            {
                "event": "image_files_selected",
                "control": "add_photo_button",
                "session_key": "session-b",
                "attempt_id": attempt_id,
                "file_count": 1,
                "last_seen_at": "2026-07-15T11:50:02+00:00",
            },
        ]
        with patch("automation.collectors._get_json", return_value=payload):
            signals = collect_product_events(
                {
                    "PRODUCTION_OBSERVABILITY_URL": "https://app.example/observability/events",
                    "PRODUCTION_OBSERVABILITY_TOKEN": "read-only-token",
                },
                now=now,
            )

        self.assertIn("ui_control_friction", {signal.event for signal in signals})

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

    def test_json_collector_retries_temporary_http_failure_and_keeps_status_private(self):
        class FakeResponse:
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"ok": true}'

        temporary_error = urllib.error.HTTPError(
            "https://www.clarity.ms/export-data/api/v1/project-live-insights",
            503,
            "temporary private provider text",
            {},
            None,
        )
        with (
            patch("automation.collectors.urllib.request.urlopen", side_effect=[temporary_error, FakeResponse()]) as request,
            patch("automation.collectors.time.sleep") as sleep,
        ):
            payload = collectors._get_json("https://www.clarity.ms/export-data/api/v1/project-live-insights", "secret")

        self.assertEqual(payload, {"ok": True})
        self.assertEqual(request.call_count, 2)
        sleep.assert_called_once()

    def test_clarity_uses_recent_proven_report_when_rate_limited(self):
        now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "runs" / "recent"
            run_dir.mkdir(parents=True)
            (run_dir / "report.json").write_text(
                json.dumps(
                    {
                        "started_at": "2026-07-15T11:00:00+00:00",
                        "signals": [
                            {
                                "source": "clarity",
                                "event": "rage_click_count",
                                "priority": "ux",
                                "summary_fa": "Clarity reported 7 rage clicks",
                                "count": 7,
                                "occurred_at": "2026-07-15T11:00:00+00:00",
                                "evidence": {"metric": "RageClickCount"},
                                "source_url": None,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with patch("automation.collectors._get_json", side_effect=CollectorError("HTTP 429")):
                signals = collect_clarity(
                    {"CLARITY_API_TOKEN": "read-only-token"},
                    now=now,
                    cache_path=root / "cache" / "clarity.json",
                    reports_dir=root / "runs",
                )
            cached_payload = json.loads((root / "cache" / "clarity.json").read_text(encoding="utf-8"))

        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].event, "rage_click_count")
        self.assertEqual(signals[0].count, 7)
        self.assertTrue(signals[0].evidence["cached"])
        self.assertEqual(cached_payload["fetched_at"], "2026-07-15T11:00:00+00:00")

    def test_run_source_health_discloses_cached_clarity_age(self):
        cached_signal = Signal(
            source="clarity",
            event="rage_click_count",
            priority="ux",
            summary_fa="cached",
            count=7,
            evidence={"cached": True, "cache_age_minutes": 133},
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "state" / "runs" / "run"
            run_dir.mkdir(parents=True)
            health: dict[str, str] = {}
            with (
                patch.object(runner, "collect_local_logs", return_value=[]),
                patch.object(runner, "collect_product_events", return_value=[]),
                patch.object(runner, "collect_sentry", return_value=[]),
                patch.object(runner, "collect_clarity", return_value=[cached_signal]),
                patch.object(runner, "collect_health", return_value=[]),
                patch.object(runner, "collect_ux_contract", return_value=[]),
                patch.object(runner, "collect_browser_probe", return_value=[]),
            ):
                runner.collect_all(root, {"sources": {"local_log_globs": [], "max_local_log_bytes": 1}}, health, run_dir)

        self.assertEqual(health["clarity"], "cached (1, age 133m)")

    def test_clarity_report_fallback_prefers_original_live_data_over_newer_cached_copy(self):
        now = datetime(2026, 7, 15, 12, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temporary:
            reports = Path(temporary)
            for run_id, started_at, cached, count in (
                ("20260715T113000Z", "2026-07-15T11:30:00+00:00", True, 99),
                ("20260715T110000Z", "2026-07-15T11:00:00+00:00", False, 7),
            ):
                run_dir = reports / run_id
                run_dir.mkdir()
                evidence = {"metric": "RageClickCount"}
                if cached:
                    evidence.update({"cached": True, "cache_age_minutes": 30})
                (run_dir / "report.json").write_text(
                    json.dumps(
                        {
                            "started_at": started_at,
                            "signals": [
                                {
                                    "source": "clarity",
                                    "event": "rage_click_count",
                                    "priority": "ux",
                                    "summary_fa": "signal",
                                    "count": count,
                                    "evidence": evidence,
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )

            signals = collectors._load_clarity_report_fallback(reports, now)

        self.assertEqual(signals[0].count, 7)
        self.assertEqual(signals[0].evidence["cache_age_minutes"], 60)

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

    def test_ux_contract_reports_missing_lifecycle_instrumentation(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            (repo / "automation").mkdir()
            shutil.copy(Path(__file__).parents[1] / "ux_contract.json", repo / "automation" / "ux_contract.json")
            (repo / "frontend" / "src" / "lib").mkdir(parents=True)
            (repo / "backend" / "app").mkdir(parents=True)
            (repo / "frontend" / "src" / "App.tsx").write_text(
                'data-observe-control="delete_photo"', encoding="utf-8"
            )
            (repo / "frontend" / "src" / "lib" / "telemetry.ts").write_text("", encoding="utf-8")
            (repo / "backend" / "app" / "schemas.py").write_text("", encoding="utf-8")

            signals = collect_ux_contract(repo)

        delete_gap = next(signal for signal in signals if signal.evidence.get("control") == "delete_photo")
        self.assertEqual(delete_gap.event, "ux_observability_gap")
        self.assertIn(
            "frontend/src/App.tsx:beginProductAction('delete_photo')",
            delete_gap.evidence["missing_markers"],
        )

    def test_current_ux_contract_has_no_uninstrumented_control(self):
        self.assertEqual(collect_ux_contract(Path(__file__).parents[2]), [])

    def test_browser_probe_turns_safe_production_ui_failures_into_signals(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = root / "run"
            run_dir.mkdir()
            script = root / "frontend" / "scripts" / "production-probe.mjs"
            script.parent.mkdir(parents=True)
            script.write_text("// fake probe", encoding="utf-8")

            def fake_probe(*_args, **_kwargs):
                (run_dir / "browser-probe.json").write_text(
                    json.dumps(
                        {
                            "views": [
                                {
                                    "name": "mobile",
                                    "screenshot": "production-mobile.png",
                                    "issues": [
                                        "horizontal_overflow",
                                        "page_error",
                                        "file_picker_failed",
                                        "image_rejection_guidance_missing",
                                        "validation_guidance_missing",
                                    ],
                                    "occluded_controls": [
                                        {
                                            "control": "build_product_list",
                                            "screenshot": "production-mobile-initial.png",
                                        }
                                    ],
                                }
                            ]
                        }
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess([], 0, "", "")

            with patch("automation.collectors.subprocess.run", side_effect=fake_probe):
                signals = collect_browser_probe(
                    root,
                    run_dir,
                    {"PRODUCTION_HEALTH_URL": "https://app.example/health"},
                )

        self.assertEqual(
            {signal.event for signal in signals},
            {
                "browser_horizontal_overflow",
                "browser_page_error",
                "browser_file_picker_failed",
                "browser_image_rejection_guidance_missing",
                "browser_validation_guidance_missing",
                "browser_control_occluded",
            },
        )
        self.assertTrue(all(signal.evidence["view"] == "mobile" for signal in signals))
        occluded = next(signal for signal in signals if signal.event == "browser_control_occluded")
        self.assertEqual(occluded.evidence["control"], "build_product_list")
        self.assertEqual(occluded.evidence["screenshot"], "production-mobile-initial.png")
        self.assertTrue(
            all(
                signal.evidence["screenshot"] == "production-mobile.png"
                for signal in signals
                if signal.event != "browser_control_occluded"
            )
        )

    def test_production_probe_rechecks_occlusion_after_a_retry_click_failure(self):
        root = Path(__file__).resolve().parents[2]
        probe = (root / "frontend" / "scripts" / "production-probe.mjs").read_text(encoding="utf-8")

        self.assertIn("async function recordOcclusionEvidence", probe)
        self.assertGreaterEqual(
            probe.count("await recordOcclusionEvidence(page, retryButton"),
            2,
        )
        self.assertIn("await recordOcclusionEvidence(page, control", probe)
        self.assertIn("scrollIntoView({ block: 'center'", probe)

    def test_production_probe_exercises_real_rejection_and_weight_guidance(self):
        root = Path(__file__).resolve().parents[2]
        probe = (root / "frontend" / "scripts" / "production-probe.mjs").read_text(encoding="utf-8")

        self.assertIn("image_rejection_guidance_missing", probe)
        self.assertIn("validation_guidance_missing", probe)
        self.assertIn("publish_failure_guidance_missing", probe)
        self.assertIn("package_weight_grams: 400", probe)
        self.assertIn("status: 422", probe)
        self.assertIn("/publish-jobs/3000", probe)
        self.assertIn("waitFor({ state: 'visible', timeout: 8000 }).then(() => true).catch(() => false)", probe)
        self.assertLess(
            probe.index("issues.add('image_rejection_guidance_missing')"),
            probe.index("await imageInput.setInputFiles"),
        )

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

    def test_model_triage_cannot_attach_unrelated_signals_to_proven_session_friction(self):
        friction = Signal(
            source="product_events",
            event="ui_control_friction",
            priority="high",
            summary_fa="در یک نشست ناشناس، باکس عکس کلیک عصبی و بی‌پاسخ ماندن ثبت کرده است.",
            evidence={"control": "photo_drop_zone", "symptoms": ["rage_click", "picker_unresponsive"]},
        )
        rage = Signal(
            source="product_events",
            event="ui_rage_click",
            priority="ux",
            summary_fa="کلیک عصبی تجمیعی",
            evidence={"control": "photo_drop_zone", "click_count": 4},
        )
        clarity = Signal(
            source="clarity",
            event="dead_click_count",
            priority="ux",
            summary_fa="Clarity عدد تجمیعی گزارش کرده است.",
            count=20,
            evidence={"metric": "DeadClickCount"},
        )
        policy = {"limits": {"max_candidate_signals": 20}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "triage.json"

            def unsafe_model_link(*_args, **_kwargs):
                output.write_text(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "fingerprint": friction.fingerprint,
                                    "title_fa": "پیوند حدسی",
                                    "problem_fa": "Clarity حتماً مربوط به همین نشست بوده است.",
                                    "priority": "high",
                                    "confidence": 0.9,
                                    "signal_fingerprints": [
                                        friction.fingerprint,
                                        rage.fingerprint,
                                        clarity.fingerprint,
                                    ],
                                    "reproducible_hint": "با تست بازسازی شود.",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess([], 0, "", "")

            with (
                patch.object(runner, "_find_command", return_value="codex"),
                patch.object(runner, "_run", side_effect=unsafe_model_link),
            ):
                candidates = runner.triage(root, root, [friction, rage, clarity], policy, False)

        self.assertEqual(len(candidates), 1)
        self.assertEqual({item["event"] for item in candidates[0].evidence}, {"ui_control_friction"})
        self.assertEqual(candidates[0].problem_fa, friction.summary_fa)
        self.assertEqual(candidates[0].priority, friction.priority)
        self.assertEqual(candidates[0].confidence, 0.8)
        self.assertNotEqual(candidates[0].reproducible_hint, "با تست بازسازی شود.")

    def test_fallback_prefers_proven_session_correlation_over_lower_level_signals(self):
        friction = Signal(
            source="product_events",
            event="ui_control_friction",
            priority="high",
            summary_fa="در یک نشست ناشناس، باکس عکس هم کلیک عصبی و هم بی‌پاسخ ثبت کرده است.",
            evidence={"control": "photo_drop_zone", "symptoms": ["rage_click", "picker_unresponsive"]},
        )
        rage = Signal(
            source="product_events",
            event="ui_rage_click",
            priority="ux",
            summary_fa="کاربر روی باکس عکس چند بار پشت سر هم کلیک کرده است.",
            count=4,
            evidence={"control": "photo_drop_zone", "click_count": 4},
        )
        stalled_picker = Signal(
            source="product_events",
            event="image_picker_unresponsive",
            priority="ux",
            summary_fa="فایل‌پیکر باکس عکس در دو تلاش نتیجه‌ای ثبت نکرده است.",
            count=2,
            evidence={"control": "photo_drop_zone", "orphaned_attempts": 2},
        )
        clarity = Signal(
            source="clarity",
            event="dead_click_count",
            priority="ux",
            summary_fa="Clarity کلیک بی‌نتیجه گزارش کرده است.",
            count=20,
            evidence={"metric": "DeadClickCount"},
        )
        candidates = runner._fallback_candidates([friction, rage, stalled_picker, clarity])

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].fingerprint, friction.fingerprint)
        self.assertEqual(
            {item["event"] for item in candidates[0].evidence},
            {"ui_control_friction"},
        )

    def test_semantic_triage_cannot_hide_exact_product_failures_or_rage_clicks(self):
        product_failure = Signal(
            source="product_events",
            event="basalam_product_failed",
            priority="high",
            summary_fa="ثبت محصول به‌خاطر وزن بسته‌بندی رد شده است.",
            evidence={"stage": "publish", "failure_field": "package_weight_grams"},
        )
        rage = Signal(
            source="product_events",
            event="ui_rage_click",
            priority="ux",
            summary_fa="کاربر روی باکس عکس چند بار پشت سر هم کلیک کرده است.",
            evidence={"control": "photo_drop_zone", "click_count": 4},
        )
        clarity = Signal(
            source="clarity",
            event="dead_click_count",
            priority="ux",
            summary_fa="Clarity کلیک بی‌نتیجه گزارش کرده است.",
            count=40,
            evidence={"metric": "DeadClickCount"},
        )
        policy = {"limits": {"max_candidate_signals": 20}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "triage.json"

            def model_only_returns_aggregate_clarity(*_args, **_kwargs):
                output.write_text(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "fingerprint": clarity.fingerprint,
                                    "title_fa": "کلیک بی‌نتیجه",
                                    "problem_fa": clarity.summary_fa,
                                    "priority": "ux",
                                    "confidence": 0.9,
                                    "signal_fingerprints": [clarity.fingerprint],
                                    "reproducible_hint": "بررسی شود.",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess([], 0, "", "")

            with (
                patch.object(runner, "_find_command", return_value="codex"),
                patch.object(runner, "_run", side_effect=model_only_returns_aggregate_clarity),
            ):
                candidates = runner.triage(root, root, [clarity, rage, product_failure], policy, False)

        self.assertEqual(
            [candidate.fingerprint for candidate in candidates[:2]],
            [product_failure.fingerprint, rage.fingerprint],
        )
        self.assertIn(clarity.fingerprint, {candidate.fingerprint for candidate in candidates})

    def test_fallback_builds_every_anchor_before_final_ranking(self):
        generic = [
            Signal(
                source="product_events",
                event=f"generic_signal_{index}",
                priority="high",
                summary_fa=f"سیگنال عمومی {index}",
            )
            for index in range(3)
        ]
        exact_failure = Signal(
            source="product_events",
            event="basalam_product_failed",
            priority="high",
            summary_fa="ثبت محصول دقیقاً روی وزن بسته‌بندی شکست خورد.",
            evidence={"failure_field": "package_weight_grams"},
        )

        candidates = runner._fallback_candidates([*generic, exact_failure])

        self.assertEqual(len(candidates), 4)
        self.assertIn(exact_failure.fingerprint, {candidate.fingerprint for candidate in candidates})

    def test_semantic_context_survives_a_fallback_fingerprint_collision(self):
        failure = Signal(
            source="product_events",
            event="basalam_product_failed",
            priority="high",
            summary_fa="ثبت محصول روی وزن بسته‌بندی شکست خورد.",
            evidence={"failure_field": "package_weight_grams"},
        )
        policy = {"limits": {"max_candidate_signals": 20}}
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            output = root / "triage.json"

            def semantic_result(*_args, **_kwargs):
                output.write_text(
                    json.dumps(
                        {
                            "candidates": [
                                {
                                    "fingerprint": failure.fingerprint,
                                    "title_fa": "وزن بسته‌بندی قابل اصلاح نیست",
                                    "problem_fa": "کاربر علت ردشدن وزن بسته‌بندی را پیش از ثبت نمی‌بیند.",
                                    "priority": "high",
                                    "confidence": 0.91,
                                    "signal_fingerprints": [failure.fingerprint],
                                    "reproducible_hint": "پیام قابل‌اقدام را با داده ساختگی بازسازی کن.",
                                }
                            ]
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                return subprocess.CompletedProcess([], 0, "", "")

            with (
                patch.object(runner, "_find_command", return_value="codex"),
                patch.object(runner, "_run", side_effect=semantic_result),
            ):
                candidates = runner.triage(root, root, [failure], policy, False)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].problem_fa, "کاربر علت ردشدن وزن بسته‌بندی را پیش از ثبت نمی‌بیند.")
        self.assertEqual(candidates[0].confidence, 0.91)

    def test_concrete_product_evidence_outranks_urgent_aggregate_clarity(self):
        concrete = Candidate(
            fingerprint="concrete",
            title_fa="شکست دقیق محصول",
            problem_fa="ثبت محصول روی وزن بسته‌بندی شکست خورد.",
            priority="high",
            confidence=0.8,
            evidence=[
                Signal(
                    source="product_events",
                    event="basalam_product_failed",
                    priority="high",
                    summary_fa="شکست دقیق",
                    evidence={"failure_field": "package_weight_grams"},
                ).to_dict()
            ],
            reproducible_hint="بازسازی شود.",
        )
        aggregate = Candidate(
            fingerprint="aggregate",
            title_fa="آمار کلی Clarity",
            problem_fa="آمار کلی کلیک‌ها زیاد شده است.",
            priority="urgent",
            confidence=0.95,
            evidence=[
                Signal(
                    source="clarity",
                    event="dead_click_count",
                    priority="urgent",
                    summary_fa="آمار کلی",
                    evidence={"metric": "DeadClickCount"},
                ).to_dict()
            ],
            reproducible_hint="بررسی شود.",
        )

        ranked = sorted([aggregate, concrete], key=runner._candidate_rank)

        self.assertEqual(ranked[0].fingerprint, concrete.fingerprint)

    def test_one_repeated_http_event_cannot_fill_every_diagnosis_slot(self):
        http_candidates = [
            Candidate(
                fingerprint=f"http-{index}",
                title_fa="شکست درخواست",
                problem_fa="یک درخواست production شکست خورد.",
                priority="urgent",
                confidence=0.9,
                evidence=[
                    Signal(
                        source="product_events",
                        event="http_request_failed",
                        priority="urgent",
                        summary_fa="شکست درخواست",
                        evidence={"path": f"/synthetic/{index}"},
                    ).to_dict()
                ],
                reproducible_hint="بازسازی شود.",
            )
            for index in range(3)
        ]
        browser_ux = Candidate(
            fingerprint="browser-ux",
            title_fa="راهنمای اعتبارسنجی دیده نشد",
            problem_fa="کاربر علت خطای وزن را نمی‌بیند.",
            priority="high",
            confidence=0.8,
            evidence=[
                Signal(
                    source="browser_probe",
                    event="browser_validation_guidance_missing",
                    priority="high",
                    summary_fa="راهنمای وزن دیده نشد.",
                ).to_dict()
            ],
            reproducible_hint="سناریوی وزن بازسازی شود.",
        )

        selected = runner._select_candidate_portfolio([*http_candidates, browser_ux], limit=3)

        self.assertIn(browser_ux.fingerprint, {candidate.fingerprint for candidate in selected})
        self.assertEqual(
            sum(candidate.fingerprint.startswith("http-") for candidate in selected),
            2,
        )

    def test_backend_gate_uses_a_creatable_single_level_pytest_temp_directory(self):
        policy = json.loads((Path(__file__).parents[1] / "policy.json").read_text(encoding="utf-8"))
        backend_gate = next(gate for gate in policy["gates"] if gate["name"] == "backend tests")

        self.assertIn("--basetemp .pytest-tmp-autonomy", backend_gate["command"])
        self.assertNotIn("--basetemp .pytest-tmp\\autonomy", backend_gate["command"])

    def test_agent_pytest_artifacts_are_ignored_before_reproducer_diff_validation(self):
        repo = Path(__file__).parents[2]
        ignored = subprocess.run(
            ["git", "check-ignore", "backend/.pytest-tmp-autonomy/example.db"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(ignored.returncode, 0, ignored.stderr)

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

    def test_dashboard_embeds_the_safe_browser_probe_screenshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            run_dir.mkdir()
            (run_dir / "production-mobile.png").write_bytes(b"safe synthetic screenshot")
            (run_dir / "production-mobile-journey.png").write_bytes(b"safe synthetic journey screenshot")
            report = {
                "run_id": "probe",
                "started_at": "2026-07-15T12:00:00+00:00",
                "finished_at": "2026-07-15T12:00:01+00:00",
                "status": "completed",
                "phase": "diagnosis",
                "source_health": {"browser_probe": "ok (1)"},
                "signals": [],
                "candidates": [
                    {
                        "fingerprint": "probe-mobile",
                        "title_fa": "بیرون‌زدگی موبایل",
                        "problem_fa": "صفحه از عرض موبایل بیرون زده است.",
                        "confidence": 0.9,
                        "status": "detected",
                        "evidence": [
                            {
                                "source": "browser_probe",
                                "event": "browser_horizontal_overflow",
                                "evidence": {"view": "mobile", "screenshot": "production-mobile.png"},
                            }
                        ],
                    }
                ],
                "diagnoses": [],
                "fixes": [],
            }

            page = write_run_report(run_dir, report).read_text(encoding="utf-8")

        self.assertIn("production-mobile.png", page)
        self.assertIn("production-mobile-journey.png", page)
        self.assertIn("<img", page)

    def test_dashboard_does_not_call_correlated_evidence_a_single_signal(self):
        with tempfile.TemporaryDirectory() as temporary:
            run_dir = Path(temporary) / "run"
            report = {
                "run_id": "correlated",
                "started_at": "2026-07-15T12:00:00+00:00",
                "finished_at": "2026-07-15T12:00:01+00:00",
                "status": "completed",
                "phase": "diagnosis",
                "source_health": {"product_events": "ok (2)"},
                "signals": [],
                "candidates": [
                    {
                        "fingerprint": "friction",
                        "title_fa": "مشکل باکس عکس",
                        "problem_fa": "کلیک عصبی و بی‌پاسخ ماندن در یک نشست دیده شد.",
                        "confidence": 0.8,
                        "status": "detected",
                        "evidence": [
                            {
                                "event": "ui_control_friction",
                                "evidence": {
                                    "control": "photo_drop_zone",
                                    "symptoms": ["rage_click", "picker_unresponsive"],
                                },
                            }
                        ],
                    }
                ],
                "diagnoses": [],
                "fixes": [],
            }

            page = write_run_report(run_dir, report).read_text(encoding="utf-8")

        self.assertIn("۲ شاهد مرتبط", page)
        self.assertNotIn("فقط یک نشانه", page)


if __name__ == "__main__":
    unittest.main()
