from __future__ import annotations

import fnmatch
import hashlib
import re
from pathlib import Path
from typing import Any, Iterable


SENSITIVE_KEY = re.compile(
    r"(access[_-]?token|refresh[_-]?token|api[_-]?key|authorization|client[_-]?secret|password|mobile|phone|transcript|voice|oauth[_-]?code|state|payload)",
    re.IGNORECASE,
)
SECRET_VALUE = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{8,}|"
    r"(access_token|refresh_token|api_key|client_secret|password)=([^\s&]+)|"
    r"(sk-[A-Za-z0-9_-]{12,})"
)
QUERY_STRING = re.compile(r"(https?://[^\s?#]+)[?#][^\s]+")


def redact_text(value: str) -> str:
    value = QUERY_STRING.sub(r"\1", value)
    return SECRET_VALUE.sub("[REDACTED]", value)


def sanitize(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): "[REDACTED]" if SENSITIVE_KEY.search(str(key)) else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def validate_diff(
    changed_files: Iterable[str],
    diff_text: str,
    policy: dict[str, Any],
) -> list[str]:
    files = [item.replace("\\", "/") for item in changed_files]
    errors: list[str] = []
    if len(files) > int(policy["limits"]["max_changed_files"]):
        errors.append("تعداد فایل‌های تغییرکرده از سقف مجاز بیشتر است.")
    changed_lines = sum(1 for line in diff_text.splitlines() if line.startswith(("+", "-")) and not line.startswith(("+++", "---")))
    if changed_lines > int(policy["limits"]["max_changed_lines"]):
        errors.append("اندازه تغییر از سقف fix کوچک بیشتر است.")
    for path in files:
        if any(fnmatch.fnmatch(path, pattern) for pattern in policy["forbidden_paths"]):
            errors.append(f"مسیر ممنوع تغییر کرده است: {path}")
    if SECRET_VALUE.search(diff_text):
        errors.append("diff شبیه secret یا credential است.")
    test_patterns = tuple(policy["test_file_patterns"])
    if files and not any(fnmatch.fnmatch(path, pattern) for path in files for pattern in test_patterns):
        errors.append("هیچ regression test تغییر نکرده است.")
    return errors


def validate_reproducer_diff(changed_files: Iterable[str], policy: dict[str, Any]) -> list[str]:
    files = [item.replace("\\", "/") for item in changed_files]
    patterns = tuple(policy["test_file_patterns"])
    if not files or not any(fnmatch.fnmatch(path, pattern) for path in files for pattern in patterns):
        return ["The reproducer stage did not add or change a regression test."]
    source_files = [
        path for path in files if not any(fnmatch.fnmatch(path, pattern) for pattern in patterns)
    ]
    if source_files:
        return [f"The reproducer stage changed source files: {', '.join(source_files)}"]
    return []


def digest_test_patch(diff_text: str) -> str:
    return hashlib.sha256(diff_text.encode("utf-8")).hexdigest()


def safe_evidence_path(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
