from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
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
    "image_picker_blocked": "ux",
    "image_picker_unresponsive": "ux",
    "ui_rage_click": "ux",
    "ui_dead_click": "ux",
    "ui_action_blocked": "ux",
    "ui_action_failed": "high",
    "ui_action_unresponsive": "ux",
    "ui_control_friction": "high",
    "ux_observability_gap": "high",
    "frontend_runtime_failed": "high",
    "browser_console_error": "high",
    "browser_page_error": "high",
    "browser_resource_failed": "high",
    "browser_document_failed": "urgent",
    "browser_navigation_failed": "urgent",
    "browser_app_shell_missing": "urgent",
    "browser_primary_actions_missing": "urgent",
    "browser_horizontal_overflow": "ux",
    "browser_mutation_attempt": "urgent",
    "browser_platform_open_failed": "high",
    "browser_file_picker_missing": "urgent",
    "browser_file_picker_failed": "high",
    "browser_upload_render_failed": "high",
    "browser_image_rejection_guidance_missing": "high",
    "browser_build_action_missing": "urgent",
    "browser_list_build_failed": "high",
    "browser_product_review_missing": "high",
    "browser_validation_guidance_missing": "high",
    "browser_publish_failure_guidance_missing": "high",
    "browser_control_occluded": "high",
    "http_response_failed": "high",
}
CONTROL_LABELS_FA = {
    "photo_drop_zone": "باکس افزودن عکس",
    "add_photo_button": "دکمه افزودن عکس",
    "build_product_list": "ساخت فهرست محصولات",
    "publish_basalam": "ثبت در باسلام",
    "submit_torob": "ارسال به ترب",
    "connect_basalam": "اتصال غرفه باسلام",
    "record_voice": "ضبط صدا",
    "change_platform": "انتخاب مسیر فروش",
    "delete_photo": "حذف عکس",
    "split_photo": "جداسازی عکس",
    "start_new_products": "شروع محصولات جدید",
    "category_picker": "انتخاب دسته‌بندی",
    "fill_missing_fields": "رفتن به فیلدهای ناقص",
    "apply_preparation_days": "اعمال زمان آماده‌سازی",
}
FIELD_LABELS_FA = {
    "title": "نام محصول",
    "price_toman": "قیمت",
    "stock": "موجودی",
    "preparation_days": "زمان آماده‌سازی",
    "weight_grams": "وزن محصول",
    "package_weight_grams": "وزن با بسته‌بندی",
    "unit_quantity": "تعداد در هر واحد",
    "category": "دسته‌بندی",
    "shop_name": "نام فروشگاه",
    "contact_mobile": "شماره تماس",
}
EVENT_PATTERN = re.compile(r"\b(" + "|".join(map(re.escape, EVENT_PRIORITY)) + r")\b")
FIELD_PATTERN = re.compile(r"([A-Za-z][A-Za-z0-9_]*)=([^\s]+)")


class CollectorError(RuntimeError):
    pass


def _product_event_summary(item: dict[str, Any], event: str, count: int) -> str:
    control = str(item.get("control") or "")
    control_label = CONTROL_LABELS_FA.get(control, control or "کنترل نامشخص")
    failure_field = str(item.get("failure_field") or "")
    field_label = FIELD_LABELS_FA.get(failure_field, failure_field)
    if event == "ui_action_blocked" and item.get("outcome") == "validation":
        if field_label:
            return f"{control_label} {count} بار به‌دلیل نامعتبر یا ناقص بودن «{field_label}» متوقف شده است."
        return f"{control_label} {count} بار در مرحله اعتبارسنجی اطلاعات متوقف شده است؛ نام فیلد در این نسخه ثبت نشده است."
    if event == "ui_action_blocked":
        return f"{control_label} {count} بار به‌دلیل وضعیت فعلی صفحه قابل ادامه نبوده است."
    if event == "ui_action_failed":
        return f"{control_label} {count} بار پس از شروع با خطا تمام شده است."
    if event == "ui_rage_click":
        return f"روی {control_label} کلیک عصبی ثبت شده است."
    if event == "ui_dead_click":
        return f"فشار روی {control_label} بدون شروع هیچ واکنشی ثبت شده است."
    return f"رویداد {event} در خود محصول production ثبت شده است."


def collect_browser_probe(
    repo: Path,
    run_dir: Path,
    env: dict[str, str] | None = None,
) -> list[Signal]:
    env = env or os.environ
    health_url = env.get("PRODUCTION_HEALTH_URL")
    if not health_url:
        raise CollectorError("آدرس production برای browser probe تنظیم نشده است.")
    parsed = urllib.parse.urlsplit(health_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise CollectorError("آدرس production برای browser probe معتبر نیست.")
    app_url = f"{parsed.scheme}://{parsed.netloc}"
    node = shutil.which("node")
    script = repo / "frontend" / "scripts" / "production-probe.mjs"
    if not node or not script.is_file():
        raise CollectorError("Playwright browser probe در دسترس نیست.")
    output = run_dir / "browser-probe.json"
    completed = subprocess.run(
        [node, str(script), app_url, str(run_dir)],
        cwd=repo / "frontend",
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    (run_dir / "browser-probe.txt").write_text(
        f"exit={completed.returncode}\n{completed.stdout[-4000:]}\n{completed.stderr[-4000:]}",
        encoding="utf-8",
    )
    if completed.returncode != 0 or not output.is_file():
        raise CollectorError(f"browser probe failed ({completed.returncode})")
    try:
        payload = json.loads(output.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CollectorError("browser probe output is invalid") from exc
    signals: list[Signal] = []
    for view in payload.get("views", []):
        if not isinstance(view, dict):
            continue
        view_name = str(view.get("name") or "unknown")
        screenshot = str(view.get("screenshot") or "")
        for issue in view.get("issues", []):
            event = f"browser_{issue}"
            if event not in EVENT_PRIORITY:
                continue
            signals.append(
                Signal(
                    source="browser_probe",
                    event=event,
                    priority=EVENT_PRIORITY[event],
                    summary_fa=f"browser probe در نمای {view_name} مشکل {issue} را پیدا کرد.",
                    evidence={"view": view_name, "screenshot": screenshot},
                )
            )
        for control in view.get("occluded_controls", []):
            control_name = str(control.get("control") or "") if isinstance(control, dict) else str(control or "")
            control_screenshot = (
                str(control.get("screenshot") or screenshot) if isinstance(control, dict) else screenshot
            )
            if not control_name:
                continue
            control_label = CONTROL_LABELS_FA.get(control_name, control_name)
            signals.append(
                Signal(
                    source="browser_probe",
                    event="browser_control_occluded",
                    priority=EVENT_PRIORITY["browser_control_occluded"],
                    summary_fa=f"در نمای {view_name}، یک لایه روی «{control_label}» افتاده و کلیک کاربر به آن نمی‌رسد.",
                    evidence={"view": view_name, "screenshot": control_screenshot, "control": control_name},
                )
            )
    return signals


def collect_ux_contract(repo: Path) -> list[Signal]:
    """Turn missing UX instrumentation into an actionable signal before users find it."""
    contract_path = repo / "automation" / "ux_contract.json"
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CollectorError(f"ux contract is unreadable: {type(exc).__name__}") from exc
    source_cache: dict[str, str] = {}
    signals: list[Signal] = []
    missing_global: list[str] = []
    for marker in contract.get("global_markers", []):
        if not isinstance(marker, dict):
            continue
        relative = str(marker.get("path") or "")
        text = str(marker.get("text") or "")
        if relative not in source_cache:
            path = repo / relative
            source_cache[relative] = path.read_text(encoding="utf-8") if path.is_file() else ""
        if not text or text not in source_cache[relative]:
            missing_global.append(f"{relative}:{text}")
    if missing_global:
        signals.append(
            Signal(
                source="ux_contract",
                event="ux_observability_gap",
                priority=EVENT_PRIORITY["ux_observability_gap"],
                summary_fa="پوشش تشخیص خطاهای runtime رابط کاربری ناقص است.",
                evidence={"control": "frontend_runtime", "missing_markers": missing_global},
            )
        )
    for item in contract.get("controls", []):
        if not isinstance(item, dict):
            continue
        control = str(item.get("control") or "unknown")
        markers = [marker for marker in item.get("markers", []) if isinstance(marker, dict)]
        missing: list[str] = []
        for marker in markers:
            relative = str(marker.get("path") or "")
            text = str(marker.get("text") or "")
            if relative not in source_cache:
                path = repo / relative
                source_cache[relative] = path.read_text(encoding="utf-8") if path.is_file() else ""
            if not text or text not in source_cache[relative]:
                missing.append(f"{relative}:{text}")
        if not missing:
            continue
        signals.append(
            Signal(
                source="ux_contract",
                event="ux_observability_gap",
                priority=EVENT_PRIORITY["ux_observability_gap"],
                summary_fa=f"کنترل {control} بدون پوشش کامل lifecycle و outcome است.",
                evidence={"control": control, "missing_markers": missing},
            )
        )
    return signals


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
            if key not in {"request_id", "session_key"} and value != "[REDACTED]"
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


def collect_clarity(
    env: dict[str, str] | None = None,
    *,
    now: datetime | None = None,
    cache_path: Path | None = None,
    reports_dir: Path | None = None,
) -> list[Signal]:
    env = env or os.environ
    current_time = now or datetime.now(timezone.utc)
    token = env.get("CLARITY_API_TOKEN")
    if not token:
        raise CollectorError("Clarity Data Export تنظیم نشده است.")
    cached = _load_clarity_cache(cache_path, current_time, max_age=timedelta(minutes=150))
    if cached:
        return cached
    query = urllib.parse.urlencode({"numOfDays": "3", "dimension1": "URL", "dimension2": "Device"})
    try:
        payload = _get_json(f"https://www.clarity.ms/export-data/api/v1/project-live-insights?{query}", token)
    except CollectorError as exc:
        temporary = str(exc) in {"HTTP 429", "URLError", "TimeoutError"} or str(exc).startswith("HTTP 5")
        fallback = _load_clarity_cache(cache_path, current_time, max_age=timedelta(hours=24))
        if not fallback and reports_dir is not None:
            fallback = _load_clarity_report_fallback(reports_dir, current_time)
        if temporary and fallback:
            fallback_age = max(
                (_safe_int(signal.evidence.get("cache_age_minutes"), 0) for signal in fallback),
                default=0,
            )
            _save_clarity_cache(cache_path, fallback, current_time - timedelta(minutes=fallback_age))
            return fallback
        raise
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
    _save_clarity_cache(cache_path, results, current_time)
    return results


def _signal_from_dict(item: dict[str, Any], *, cached: bool, age_minutes: int) -> Signal | None:
    if item.get("source") != "clarity" or not item.get("event"):
        return None
    evidence = dict(item.get("evidence") or {})
    if cached:
        evidence.update({"cached": True, "cache_age_minutes": max(0, age_minutes)})
    return Signal(
        source="clarity",
        event=str(item["event"]),
        priority=str(item.get("priority") or "ux"),
        summary_fa=str(item.get("summary_fa") or "Clarity cached signal"),
        count=max(1, _safe_int(item.get("count"), 1)),
        occurred_at=str(item.get("occurred_at") or datetime.now(timezone.utc).isoformat()),
        evidence=evidence,
        source_url=item.get("source_url"),
    )


def _load_clarity_cache(cache_path: Path | None, now: datetime, *, max_age: timedelta) -> list[Signal]:
    if cache_path is None or not cache_path.is_file():
        return []
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
        fetched_at = datetime.fromisoformat(str(payload["fetched_at"]).replace("Z", "+00:00"))
        if fetched_at.tzinfo is None:
            fetched_at = fetched_at.replace(tzinfo=timezone.utc)
        age = now - fetched_at
        if age < timedelta(0) or age > max_age:
            return []
        age_minutes = int(age.total_seconds() // 60)
        return [
            signal
            for item in payload.get("signals", [])
            if isinstance(item, dict)
            for signal in [_signal_from_dict(item, cached=True, age_minutes=age_minutes)]
            if signal is not None
        ]
    except (OSError, KeyError, ValueError, json.JSONDecodeError):
        return []


def _load_clarity_report_fallback(reports_dir: Path, now: datetime) -> list[Signal]:
    if not reports_dir.is_dir():
        return []
    newest_cached: list[Signal] = []
    for report_path in sorted(reports_dir.glob("*/report.json"), reverse=True):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            started_at = datetime.fromisoformat(str(report["started_at"]).replace("Z", "+00:00"))
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            age = now - started_at
            if age < timedelta(0) or age > timedelta(hours=24):
                continue
            report_age_minutes = int(age.total_seconds() // 60)
            clarity_items = [
                item
                for item in report.get("signals", [])
                if isinstance(item, dict) and item.get("source") == "clarity"
            ]
            if not clarity_items:
                continue
            is_cached_copy = any(bool((item.get("evidence") or {}).get("cached")) for item in clarity_items)
            embedded_age = max(
                (_safe_int((item.get("evidence") or {}).get("cache_age_minutes"), 0) for item in clarity_items),
                default=0,
            )
            age_minutes = report_age_minutes + embedded_age if is_cached_copy else report_age_minutes
            signals = [
                signal
                for item in clarity_items
                for signal in [_signal_from_dict(item, cached=True, age_minutes=age_minutes)]
                if signal is not None
            ]
            if signals and not is_cached_copy:
                return signals
            if signals and not newest_cached:
                newest_cached = signals
        except (OSError, KeyError, ValueError, json.JSONDecodeError):
            continue
    return newest_cached


def _save_clarity_cache(cache_path: Path | None, signals: list[Signal], fetched_at: datetime) -> None:
    if cache_path is None:
        return
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(
            {"fetched_at": fetched_at.isoformat(), "signals": [signal.to_dict() for signal in signals]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temporary.replace(cache_path)


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


def _session_key(item: dict[str, Any]) -> str:
    # request_id is accepted only for a short transition from the previous
    # deployment; neither value is ever copied into a Signal or report.
    return str(item.get("session_key") or item.get("request_id") or "")


def _attempt_key(item: dict[str, Any]) -> tuple[str, str, str]:
    return _session_key(item), str(item.get("control") or ""), str(item.get("attempt_id") or "")


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
    current_time = now or datetime.now(timezone.utc)
    since = current_time - timedelta(hours=24)
    query = urllib.parse.urlencode({"limit": "500", "since": since.isoformat()})
    payload = _get_json(f"{url}{separator}{query}", token)
    if not isinstance(payload, list):
        raise CollectorError("پاسخ فید رویدادهای production معتبر نیست.")
    results: list[Signal] = []
    terminal_attempts = {
        _attempt_key(item)
        for item in payload
        if isinstance(item, dict)
        and item.get("event") in {"image_files_selected", "image_picker_cancelled"}
        and item.get("attempt_id")
    }
    terminal_actions = {
        _attempt_key(item)
        for item in payload
        if isinstance(item, dict)
        and item.get("event") in {"ui_action_accepted", "ui_action_blocked", "ui_action_failed"}
        and item.get("attempt_id")
    }
    rage_sessions = {
        (_session_key(item), str(item.get("control")))
        for item in payload
        if isinstance(item, dict)
        and item.get("event") == "ui_rage_click"
        and _session_key(item)
        and item.get("control")
    }
    dead_clicks_by_control: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stalled_session_symptoms: dict[tuple[str, str], set[str]] = defaultdict(set)
    for item in payload:
        if not isinstance(item, dict) or not _session_key(item) or not item.get("control"):
            continue
        if item.get("event") == "ui_dead_click":
            control = str(item["control"])
            dead_clicks_by_control[control].append(item)
            stalled_session_symptoms[(_session_key(item), control)].add("dead_click")
        attempt_id = str(item.get("attempt_id") or "")
        attempt_key = _attempt_key(item)
        if item.get("event") == "image_picker_opened" and (
            attempt_id
            and attempt_key not in terminal_attempts
            and _event_is_older_than(item, current_time, minutes=5)
        ):
            stalled_session_symptoms[(_session_key(item), str(item["control"]))].add("picker_unresponsive")
        if item.get("event") == "ui_action_started" and (
            attempt_id
            and attempt_key not in terminal_actions
            and _event_is_older_than(item, current_time, minutes=5)
        ):
            stalled_session_symptoms[(_session_key(item), str(item["control"]))].add("action_unresponsive")
    for request_id, control in sorted(rage_sessions & set(stalled_session_symptoms)):
        symptoms = ["rage_click", *sorted(stalled_session_symptoms[(request_id, control)])]
        results.append(
            Signal(
                source="product_events",
                event="ui_control_friction",
                priority=EVENT_PRIORITY["ui_control_friction"],
                summary_fa=(
                    f"در یک نشست ناشناس، کنترل {control} هم کلیک عصبی و هم بی‌پاسخ ماندن را ثبت کرده است."
                ),
                evidence={
                    "control": control,
                    "symptoms": symptoms,
                },
            )
        )
    for control, dead_clicks in dead_clicks_by_control.items():
        results.append(
            Signal(
                source="product_events",
                event="ui_dead_click",
                priority=EVENT_PRIORITY["ui_dead_click"],
                summary_fa=_product_event_summary(
                    {"event": "ui_dead_click", "control": control},
                    "ui_dead_click",
                    len(dead_clicks),
                ),
                count=len(dead_clicks),
                occurred_at=max(
                    (str(item.get("last_seen_at")) for item in dead_clicks if item.get("last_seen_at")),
                    default=datetime.now(timezone.utc).isoformat(),
                ),
                evidence={"control": control},
            )
        )
    orphaned_by_control: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in payload:
        if not isinstance(item, dict) or item.get("event") != "image_picker_opened":
            continue
        attempt_id = str(item.get("attempt_id") or "")
        if attempt_id and _attempt_key(item) not in terminal_attempts and _event_is_older_than(item, current_time, minutes=5):
            orphaned_by_control[str(item.get("control") or "unknown")].append(item)
    for control, orphaned in orphaned_by_control.items():
        if len(orphaned) < 2:
            continue
        results.append(
            Signal(
                source="product_events",
                event="image_picker_unresponsive",
                priority=EVENT_PRIORITY["image_picker_unresponsive"],
                summary_fa=f"فایل‌پیکر {control} در {len(orphaned)} تلاش باز شد اما انتخاب یا لغو ثبت نشد.",
                count=len(orphaned),
                occurred_at=str(orphaned[-1].get("last_seen_at") or datetime.now(timezone.utc).isoformat()),
                evidence={"control": control, "orphaned_attempts": len(orphaned)},
            )
        )
    stalled_actions_by_control: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in payload:
        if not isinstance(item, dict) or item.get("event") != "ui_action_started":
            continue
        attempt_id = str(item.get("attempt_id") or "")
        if attempt_id and _attempt_key(item) not in terminal_actions and _event_is_older_than(item, current_time, minutes=5):
            stalled_actions_by_control[str(item.get("control") or "unknown")].append(item)
    for control, stalled in stalled_actions_by_control.items():
        if len(stalled) < 2:
            continue
        results.append(
            Signal(
                source="product_events",
                event="ui_action_unresponsive",
                priority=EVENT_PRIORITY["ui_action_unresponsive"],
                summary_fa=f"کنترل {control} در {len(stalled)} تلاش شروع شد اما هیچ نتیجه‌ای ثبت نشد.",
                count=len(stalled),
                occurred_at=str(stalled[-1].get("last_seen_at") or datetime.now(timezone.utc).isoformat()),
                evidence={"control": control, "orphaned_attempts": len(stalled)},
            )
        )
    for item in payload:
        if not isinstance(item, dict):
            continue
        event = str(item.get("event") or "")
        if event == "ui_dead_click":
            continue
        if event not in EVENT_PRIORITY:
            continue
        evidence = {
            key: value
            for key, value in sanitize(item).items()
            if key not in {"event", "count", "request_id", "session_key"} and value not in {None, "[REDACTED]"}
        }
        count = _safe_int(item.get("count"), 1)
        results.append(
            Signal(
                source="product_events",
                event=event,
                priority=EVENT_PRIORITY[event],
                summary_fa=_product_event_summary(item, event, max(1, count)),
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
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            retryable = exc.code == 429 or 500 <= exc.code < 600
            if retryable and attempt < 2:
                time.sleep(attempt + 1)
                continue
            raise CollectorError(f"HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt < 2:
                time.sleep(attempt + 1)
                continue
            raise CollectorError(type(exc).__name__) from exc
        except json.JSONDecodeError as exc:
            raise CollectorError("JSONDecodeError") from exc
    raise CollectorError("collector retry exhausted")


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _event_is_older_than(item: dict[str, Any], now: datetime, *, minutes: int) -> bool:
    raw = item.get("last_seen_at")
    if not isinstance(raw, str):
        return False
    try:
        occurred_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return False
    if occurred_at.tzinfo is None:
        occurred_at = occurred_at.replace(tzinfo=timezone.utc)
    return occurred_at <= now - timedelta(minutes=minutes)


def _sum_count_fields(row: dict[str, Any]) -> int:
    # Clarity's behavioral metric rows expose the actual metric count as
    # `subTotal`; `sessionsCount` is only the denominator for the dimension.
    if "subTotal" in row:
        return _safe_int(row.get("subTotal"))
    counts = [_safe_int(value) for key, value in row.items() if key.lower().endswith("count") and "session" not in key.lower()]
    return sum(counts) if counts else 0


def _snake_case(value: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "_", value.replace(" ", "_")).lower()
