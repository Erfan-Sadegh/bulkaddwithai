from __future__ import annotations

import json
import os
import shutil
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator


def default_state_dir() -> Path:
    base = Path(os.getenv("LOCALAPPDATA") or Path.home() / ".local" / "share")
    return base / "BulkAddWithAi-agent"


def load_state(root: Path) -> dict:
    path = root / "state.json"
    if not path.exists():
        return {"runs": [], "fingerprints": {}}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"runs": [], "fingerprints": {}, "state_recovered": True}


def save_state(root: Path, state: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    target = root / "state.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def phase_for_completed_runs(completed_runs: int) -> tuple[str, int]:
    if completed_runs < 7:
        return "report_only", 0
    if completed_runs < 21:
        return "one_fix", 1
    return "guarded", 3


def apply_retention(root: Path, days: int = 30) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    runs_dir = root / "runs"
    if not runs_dir.exists():
        return
    for run_dir in runs_dir.iterdir():
        if not run_dir.is_dir():
            continue
        report_path = run_dir / "report.json"
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            started = datetime.fromisoformat(report["started_at"])
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
        protected = any(
            fix.get("pr_state") in {"open", "rollback", "failed"}
            for fix in report.get("fixes", [])
        )
        if started < cutoff and not protected:
            shutil.rmtree(run_dir)


@contextmanager
def exclusive_lock(root: Path) -> Iterator[None]:
    root.mkdir(parents=True, exist_ok=True)
    lock = root / "agent.lock"
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(descriptor, str(os.getpid()).encode("ascii"))
        os.close(descriptor)
    except FileExistsError as exc:
        raise RuntimeError("یک اجرای دیگر عامل هنوز فعال است.") from exc
    try:
        yield
    finally:
        lock.unlink(missing_ok=True)
