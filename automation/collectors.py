from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from automation.models import Signal
from automation.security import sanitize


EVENT_PRIORITY = {
    "http_request_failed": "urgent",
    "upload_batch_failed": "urgent",
    "basalam_publish_failed": "urgent",
    "processing_job_failed": "high",
    "basalam_product_failed": "high",
    "torob_publish_failed": "high",
    "basalam_oauth_failed": "medium",
    "basalam_publish_validation_failed": "ux",
    "image_upload_rejected": "ux",
    "http_response_failed": "high",
}
EVENT_PATTERN = re.compile(r"\b(" + "|".join(map(re.escape, EVENT_PRIORITY)) + r")\b")
FIELD_PATTERN = re.compile(r"([A-Za-z][A-Za-z0-9_]*)=([^\s]+)")


class CollectorError(RuntimeError):
    pass


def collect_local_logs(repo: Path, policy: dict[str, Any]) -> list[Signal]:
    paths: set[Path] = set()
    for pattern in policy["sources"]["local_log_globs"]:
        paths.update(repo.glob(pattern))
    external = os.getenv("AUTONOMY_LOG_DIR")
    if external:
        paths.update(Path(external).glob("*.log"))

    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for path in sorted(paths):
        if not path.is_file():
            continue
        for line in _tail_text(path, int(policy["sources"]["max_local_log_bytes"])).splitlines():
            parsed = _parse_log_line(line)
            if not parsed:
                continue
            event = str(parsed.pop("event"))
            key = (event, str(parsed.get("path", "")), str(parsed.get("stage", "")))
            grouped[key].append(parsed)

    signals: list[Signal] = []
    for (event, _path, _stage), items in grouped.items():
        latest = {
            key: value
            for key, value in sanitize(items[-1]).items()
            if value != "[REDACTED]"
        }
        signals.append(
            Signal(
                source="local_log",
                event=event,
                priority=EVENT_PRIORITY[event],
                summary_fa=f"رخداد {event} در لاگ‌ها {len(items)} بار دیده شد.",
                count=len(items),
                evidence=latest,
            )
        )
    return signals


def collect_sentry(env: dict[str, str] | None = None) -> list[Signal]:
    env = env or os.environ
    token, org, projects = env.get("SENTRY_AUTH_TOKEN"), env.get("SENTRY_ORG"), env.get("SENTRY_PROJECTS")
    if not token or not org or not projects:
        raise CollectorError("Sentry تنظیم نشده است.")
    params: list[tuple[str, str]] = [("query", "is:unresolved"), ("statsPeriod", "24h"), ("sort", "freq"), ("limit", "50")]
    params.extend(("project", project.strip()) for project in projects.split(",") if project.strip())
    url = f"https://sentry.io/api/0/organizations/{urllib.parse.quote(org)}/issues/?{urllib.parse.urlencode(params)}"
    payload = _get_json(url, token)
    if not isinstance(payload, list):
        raise CollectorError("پاسخ Sentry معتبر نیست.")
    results: list[Signal] = []
    for issue in payload:
        count = _safe_int(issue.get("count"), 1)
        metadata = sanitize(issue.get("metadata") or {})
        results.append(
            Signal(
                source="sentry",
                event=str(issue.get("type") or "sentry_issue"),
                priority="urgent" if str(issue.get("level")) in {"fatal", "error"} and count > 2 else "high",
                summary_fa=f"خطای حل‌نشده‌ی Sentry با {count} رخداد ثبت شده است.",
                count=count,
                occurred_at=str(issue.get("lastSeen") or datetime.now(timezone.utc).isoformat()),
                evidence={"issue_id": issue.get("id"), "culprit": issue.get("culprit"), "metadata": metadata},
                source_url=issue.get("permalink"),
            )
        )
    return results


def collect_clarity(env: dict[str, str] | None = None) -> list[Signal]:
    env = env or os.environ
    token = env.get("CLARITY_API_TOKEN")
    if not token:
        raise CollectorError("Clarity Data Export تنظیم نشده است.")
    query = urllib.parse.urlencode({"numOfDays": "3", "dimension1": "URL", "dimension2": "Device"})
    payload = _get_json(f"https://www.clarity.ms/export-data/api/v1/project-live-insights?{query}", token)
    if not isinstance(payload, list):
        raise CollectorError("پاسخ Clarity معتبر نیست.")
    results: list[Signal] = []
    interesting = {"DeadClickCount", "RageClickCount", "ScriptErrorCount", "ErrorClickCount", "QuickbackClick"}
    for metric in payload:
        metric_name = str(metric.get("metricName") or "")
        if metric_name.replace(" ", "").lower() == "traffic":
            rows = metric.get("information") or []
            sessions = sum(_safe_int(row.get("totalSessionCount")) for row in rows if isinstance(row, dict))
            results.append(
                Signal(
                    source="clarity",
                    event="clarity_traffic",
                    priority="info",
                    summary_fa=f"Clarity در بازه پایش {sessions} session ثبت کرده است.",
                    count=sessions,
                    evidence={"observation_count": sessions},
                )
            )
            continue
        if metric_name.replace(" ", "") not in interesting:
            continue
        rows = metric.get("information") or []
        total = sum(_sum_count_fields(row) for row in rows if isinstance(row, dict))
        if total <= 0:
            continue
        results.append(
            Signal(
                source="clarity",
                event=_snake_case(metric_name),
                priority="high" if "Error" in metric_name else "ux",
                summary_fa=f"Clarity برای {metric_name} تعداد {total} رخداد گزارش کرده است.",
                count=total,
                evidence={"metric": metric_name, "top_rows": sanitize(rows[:5])},
            )
        )
    return results


def collect_health(env: dict[str, str] | None = None) -> list[Signal]:
    env = env or os.environ
    url = env.get("PRODUCTION_HEALTH_URL")
    if not url:
        raise CollectorError("آدرس health production تنظیم نشده است.")
    try:
        with urllib.request.urlopen(url, timeout=15) as response:
            if 200 <= response.status < 300:
                return []
            status = response.status
    except Exception as exc:  # network exception becomes evidence, not a crash
        return [Signal(source="health", event="production_health_failed", priority="urgent", summary_fa="health production در دسترس نبود.", evidence={"exception_type": type(exc).__name__})]
    return [Signal(source="health", event="production_health_failed", priority="urgent", summary_fa=f"health production پاسخ {status} داد.", evidence={"status": status})]


def collect_product_events(
    env: dict[str, str] | None = None,
    *,
    now: datetime | None = None,
) -> list[Signal]:
    env = env or os.environ
    url = env.get("PRODUCTION_OBSERVABILITY_URL")
    token = env.get("PRODUCTION_OBSERVABILITY_TOKEN")
    if not url or not token:
        raise CollectorError("فید رویدادهای production تنظیم نشده است.")
    separator = "&" if "?" in url else "?"
    since = (now or datetime.now(timezone.utc)) - timedelta(hours=24)
    query = urllib.parse.urlencode({"limit": "500", "since": since.isoformat()})
    payload = _get_json(f"{url}{separator}{query}", token)
    if not isinstance(payload, list):
        raise CollectorError("پاسخ فید رویدادهای production معتبر نیست.")
    results: list[Signal] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        event = str(item.get("event") or "")
        if event not in EVENT_PRIORITY:
            continue
        evidence = {
            key: value
            for key, value in sanitize(item).items()
            if key not in {"event", "count"} and value not in {None, "[REDACTED]"}
        }
        count = _safe_int(item.get("count"), 1)
        results.append(
            Signal(
                source="product_events",
                event=event,
                priority=EVENT_PRIORITY[event],
                summary_fa=f"رویداد {event} در خود محصول production ثبت شده است.",
                count=max(1, count),
                occurred_at=str(item.get("last_seen_at") or datetime.now(timezone.utc).isoformat()),
                evidence=evidence,
            )
        )
    return results


def _parse_log_line(line: str) -> dict[str, Any] | None:
    try:
        data = json.loads(line)
        event = str(data.get("event") or "")
        if event not in EVENT_PRIORITY:
            return None
        return {key: value for key, value in data.items() if key not in {"message", "traceback"}}
    except (json.JSONDecodeError, AttributeError):
        match = EVENT_PATTERN.search(line)
        if not match:
            return None
        return {"event": match.group(1), **dict(FIELD_PATTERN.findall(line))}


def _tail_text(path: Path, max_bytes: int) -> str:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        size = handle.tell()
        handle.seek(max(0, size - max_bytes))
        return handle.read().decode("utf-8", errors="replace")


def _get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise CollectorError(type(exc).__name__) from exc


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _sum_count_fields(row: dict[str, Any]) -> int:
    counts = [_safe_int(value) for key, value in row.items() if key.lower().endswith("count") and "session" not in key.lower()]
    return sum(counts) if counts else 0


def _snake_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value.replace(" ", "_")).lower()
