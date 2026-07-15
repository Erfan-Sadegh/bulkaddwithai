from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

from automation.collectors import collect_local_logs
from automation.dashboard import rebuild_dashboard, write_run_report
from automation.models import Candidate
from automation import runner


def run_self_improvement_simulation(root: Path) -> dict[str, object]:
    """Exercise the real collector/worktree/TDD/review/report pipeline without external writes."""
    root.mkdir(parents=True, exist_ok=True)
    repo = root / "product"
    origin = root / "origin.git"
    state = root / "agent-state"
    run_dir = state / "runs" / "simulation"
    repo.mkdir()
    run_dir.mkdir(parents=True)

    _checked(["git", "init", "--bare", str(origin)], root)
    _checked(["git", "init", "-b", "main"], repo)
    _checked(["git", "config", "user.email", "agent-simulation@example.invalid"], repo)
    _checked(["git", "config", "user.name", "Agent Simulation"], repo)
    backend = repo / "backend"
    backend.mkdir()
    (backend / "calc.py").write_text("def add(left, right):\n    return left + right + 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    (backend / "tests").mkdir()
    (backend / "tests" / "__init__.py").write_text("", encoding="utf-8")
    (backend / "tests" / "test_baseline.py").write_text(
        "import unittest\n\n"
        "class BaselineTest(unittest.TestCase):\n"
        "    def test_repository_starts_green(self):\n"
        "        self.assertTrue(True)\n",
        encoding="utf-8",
    )
    prompts = repo / "automation" / "prompts"
    prompts.mkdir(parents=True)
    (prompts / "reproducer.md").write_text("Write only the failing regression test.", encoding="utf-8")
    (prompts / "fixer.md").write_text("Fix product code without changing the test.", encoding="utf-8")
    _checked(["git", "add", "."], repo)
    _checked(["git", "commit", "-m", "seed intentional bug"], repo)
    _checked(["git", "remote", "add", "origin", str(origin)], repo)
    _checked(["git", "push", "-u", "origin", "main"], repo)

    (repo / "app.log").write_text(
        json.dumps(
            {
                "event": "processing_job_failed",
                "stage": "synthetic_calculation",
                "job_id": 42,
            }
        ),
        encoding="utf-8",
    )
    python = str(Path(sys.executable).resolve())
    policy = {
        "limits": {"max_changed_files": 4, "max_changed_lines": 100},
        "forbidden_paths": [],
        "test_file_patterns": ["backend/tests/test_*.py"],
        "sources": {"local_log_globs": ["*.log"], "max_local_log_bytes": 100_000},
        "setup_commands": [],
        "gates": [
            {
                "name": "backend tests",
                "cwd": "backend",
                "command": f'"{python}" -m unittest discover -s tests -v',
            }
        ],
    }
    signals = collect_local_logs(repo, policy)
    signal = signals[0]
    candidate = Candidate(
        fingerprint=signal.fingerprint,
        title_fa="اصلاح جمع ساختگی",
        problem_fa=signal.summary_fa,
        priority=signal.priority,
        confidence=1.0,
        evidence=[signal.to_dict()],
        reproducible_hint="تابع add یک واحد اضافه برمی‌گرداند.",
    )

    real_run = runner._run

    def simulated_run(command: list[str], cwd: Path, timeout: int):
        if command[0] != "synthetic-codex":
            return real_run(command, cwd, timeout)
        output = Path(command[command.index("-o") + 1])
        if "--output-schema" in command:
            output.write_text(
                json.dumps(
                    {"verdict": "approve", "summary_fa": "چرخه ساختگی تأیید شد.", "findings": []},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
        elif output.name in {"reproducer-message.txt", "diagnosis-message.txt"}:
            (cwd / "backend" / "tests" / "test_calc.py").write_text(
                "import unittest\n\nfrom calc import add\n\n"
                "class CalcRegressionTest(unittest.TestCase):\n"
                "    def test_add_does_not_invent_an_extra_unit(self):\n"
                "        self.assertEqual(add(2, 2), 4)\n",
                encoding="utf-8",
            )
            output.write_text("تست بازسازی نوشته شد.", encoding="utf-8")
        else:
            (cwd / "backend" / "calc.py").write_text(
                "def add(left, right):\n    return left + right\n",
                encoding="utf-8",
            )
            output.write_text("کد محصول اصلاح شد.", encoding="utf-8")
        return subprocess.CompletedProcess(command, 0, "", "")

    with (
        patch.object(runner, "_find_command", side_effect=lambda name: "synthetic-codex" if name == "codex" else None),
        patch.object(runner, "_run", side_effect=simulated_run),
        patch.dict(os.environ, {"GITHUB_TOKEN": ""}, clear=False),
    ):
        diagnosis = runner.attempt_diagnosis(repo, state, run_dir, candidate, policy)
        source_after_diagnosis = (repo / "backend" / "calc.py").read_text(encoding="utf-8")
        fix = runner.attempt_fix(repo, state, run_dir, candidate, policy)

    report = {
        "run_id": "simulation",
        "started_at": signal.occurred_at,
        "status": "completed",
        "phase": "simulation",
        "signals": [signal.to_dict()],
        "candidates": [candidate.to_dict()],
        "diagnoses": [diagnosis],
        "fixes": [fix],
        "source_health": {"synthetic_local_log": "ok (1)"},
    }
    write_run_report(run_dir, report)
    dashboard = rebuild_dashboard(state)
    review = json.loads((run_dir / f"review-{candidate.fingerprint}.json").read_text(encoding="utf-8"))
    worktrees = state / "worktrees"
    return {
        "signal_count": len(signals),
        "diagnosis_status": diagnosis["status"],
        "source_unchanged_after_diagnosis": source_after_diagnosis == "def add(left, right):\n    return left + right + 1\n",
        "fix_status": fix["status"],
        "regression_before_exit": _last_exit(run_dir / "regression-before.txt"),
        "final_test_exit": _last_exit(run_dir / "test-results.txt"),
        "review_verdict": review["verdict"],
        "dashboard_created": dashboard.exists(),
        "worktree_cleaned": not worktrees.exists() or not any(worktrees.iterdir()),
        "dashboard": str(dashboard),
    }


def _checked(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True, text=True, capture_output=True)


def _last_exit(path: Path) -> int:
    matches = re.findall(r"^exit=(\d+)$", path.read_text(encoding="utf-8"), re.MULTILINE)
    if not matches:
        raise RuntimeError(f"No test exit code in {path}")
    return int(matches[-1])


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        result = run_self_improvement_simulation(Path(temporary))
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
