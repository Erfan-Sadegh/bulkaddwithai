from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unittest.mock import patch

from automation.collectors import CollectorError, collect_local_logs, collect_product_events
from automation.dashboard import rebuild_dashboard, write_run_report
from automation.security import (
    redact_text,
    sanitize,
    digest_test_patch,
    validate_diff,
    validate_reproducer_diff,
)
from automation.state import apply_retention, phase_for_completed_runs


POLICY = {
    "limits": {"max_changed_files": 3, "max_changed_lines": 20},
    "forbidden_paths": ["backend/alembic/**", "automation/policy.json", "frontend/package.json"],
    "test_file_patterns": ["backend/tests/test_*.py", "frontend/src/*.test.tsx"],
    "sources": {"local_log_globs": ["*.log"], "max_local_log_bytes": 100_000},
}


class AutomationTests(unittest.TestCase):
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

    def test_product_event_collector_never_guesses_without_credentials(self):
        with self.assertRaises(CollectorError):
            collect_product_events({})

    def test_rollout_phases_are_conservative(self):
        self.assertEqual(phase_for_completed_runs(0), ("report_only", 0))
        self.assertEqual(phase_for_completed_runs(6), ("report_only", 0))
        self.assertEqual(phase_for_completed_runs(7), ("one_fix", 1))
        self.assertEqual(phase_for_completed_runs(21), ("guarded", 3))

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


if __name__ == "__main__":
    unittest.main()
