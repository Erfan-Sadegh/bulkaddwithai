from __future__ import annotations

import html
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote


# Iran has used UTC+03:30 year-round since September 2022. A fixed offset keeps
# the local dashboard dependency-free on Windows, where IANA tzdata is optional.
TEHRAN = timezone(timedelta(hours=3, minutes=30), "Asia/Tehran")
PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")
MONTHS_FA = (
    "ژانویه", "فوریه", "مارس", "آوریل", "مه", "ژوئن",
    "ژوئیه", "اوت", "سپتامبر", "اکتبر", "نوامبر", "دسامبر",
)

STATUS = {
    "detected": ("🟡", "سیگنال نیازمند بررسی"),
    "reproduced": ("🟠", "با تست بازسازی شد"),
    "fixed_in_test": ("🟠", "در محیط تست رفع شد"),
    "ready_for_review": ("🔵", "آماده بررسی شما"),
    "deployed": ("🔵", "منتشر شد؛ در حال پایش"),
    "confirmed_production": ("🟢", "در محیط واقعی تأیید شد"),
    "insufficient_evidence": ("⚪", "شواهد کافی نیست"),
    "rejected": ("⚫", "تغییر رد شد"),
}

PHASES = {
    "report_only": "پایش و گزارش‌گیری",
    "monitoring": "پایش سه‌ساعته (بدون تغییر کد)",
    "one_fix": "اصلاح محدود (حداکثر یک مورد)",
    "guarded": "اصلاح محافظت‌شده",
}

SOURCES = {
    "local_logs": "لاگ‌های محلی",
    "product_events": "رخدادهای خود محصول",
    "sentry": "خطاهای فنی Sentry",
    "clarity": "رفتار کاربران در Clarity",
    "production_health": "سلامت برنامهٔ واقعی",
}

EVENTS = {
    "image_upload_rejected": "رد شدن تصویر هنگام بارگذاری",
    "image_picker_blocked": "کلیک روی آپلود در زمانی که افزودن عکس قفل بود",
    "processing_job_failed": "ناموفق بودن پردازش هوش مصنوعی",
    "http_request_failed": "خطای داخلی درخواست",
    "http_response_failed": "پاسخ ناموفق سرور",
    "upload_batch_failed": "ناموفق بودن بارگذاری گروهی",
    "basalam_publish_failed": "ناموفق بودن انتشار در باسلام",
    "basalam_product_failed": "ناموفق بودن یک محصول در باسلام",
    "basalam_oauth_failed": "ناموفق بودن اتصال باسلام",
    "basalam_publish_validation_failed": "رد شدن اعتبارسنجی انتشار باسلام",
    "torob_publish_failed": "ناموفق بودن انتشار در ترب",
}


def write_run_report(run_dir: Path, report: dict) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    target = run_dir / "report.html"
    target.write_text(_run_html(report, run_dir), encoding="utf-8")
    return target


def rebuild_dashboard(state_root: Path) -> Path:
    dashboard_dir = state_root / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    run_kinds: dict[str, str] = {}
    try:
        state = json.loads((state_root / "state.json").read_text(encoding="utf-8"))
        run_kinds = {
            str(item.get("run_id")): str(item.get("kind"))
            for item in state.get("runs", [])
            if item.get("run_id") and item.get("kind")
        }
    except (OSError, json.JSONDecodeError):
        pass
    reports: list[tuple[dict, Path]] = []
    for report_path in sorted((state_root / "runs").glob("*/report.json"), reverse=True):
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report.setdefault("run_kind", run_kinds.get(str(report.get("run_id")), "manual"))
            reports.append((report, report_path.parent))
            # Rebuild historical pages too, so a dashboard upgrade is immediately visible.
            report_path.with_name("report.html").write_text(
                _run_html(report, report_path.parent), encoding="utf-8"
            )
        except (OSError, json.JSONDecodeError):
            continue

    cards: list[str] = []
    for index, (report, directory) in enumerate(reports[:100]):
        link = directory.joinpath("report.html").as_uri()
        position = "آخرین اجرا" if index == 0 else "اجرای قبلی"
        label = f"{position} · {_run_kind_label(report)}"
        outcome = _short_outcome(report)
        cards.append(
            '<article class="run-card">'
            f'<p class="eyebrow">{label}</p>'
            f'<h2>{html.escape(_format_time(report.get("started_at")))}</h2>'
            f'<p class="muted">{html.escape(PHASES.get(report.get("phase", ""), report.get("phase", "نامشخص")))}</p>'
            f'<p>{html.escape(outcome)}</p>'
            f'<a class="button" href="{html.escape(link, quote=True)}">گزارش شفاف این اجرا</a>'
            f'<details class="run-id"><summary>شناسه فنی اجرا</summary><code>{html.escape(report.get("run_id", ""))}</code></details>'
            '</article>'
        )

    body = (
        '<section class="hero"><p class="eyebrow">مرکز کنترل شبانه</p>'
        '<h1>داشبورد عامل BulkAddWithAI</h1>'
        '<p>هر کارت می‌گوید چه چیزی بررسی شد، چه چیزی ثابت شد و آیا کاری از شما لازم است.</p></section>'
        + ("".join(cards) if cards else '<div class="empty">هنوز گزارشی ساخته نشده است.</div>')
    )
    target = dashboard_dir / "index.html"
    target.write_text(_shell("داشبورد عامل BulkAddWithAI", body, show_title=False), encoding="utf-8")
    return target


def _run_html(report: dict, run_dir: Path) -> str:
    started = _format_time(report.get("started_at"))
    duration = _duration_text(report.get("started_at"), report.get("finished_at"))
    phase = PHASES.get(report.get("phase", ""), str(report.get("phase", "نامشخص")))
    status = "با موفقیت تمام شد" if report.get("status") == "completed" else "اجرا کامل نشد"
    outcome = _short_outcome(report)
    action = _next_action(report)

    overview = (
        '<section class="hero">'
        f'<p class="eyebrow">گزارش {_run_kind_label(report)}</p>'
        f'<h1>{html.escape(started)}</h1>'
        f'<p>{html.escape(status)} · مدت اجرا: {html.escape(duration)} · {html.escape(phase)}</p>'
        '</section>'
        '<section class="summary-grid">'
        f'<article class="summary"><p class="eyebrow">نتیجه در یک نگاه</p><h2>{html.escape(outcome)}</h2></article>'
        f'<article class="summary action"><p class="eyebrow">الان چه کار کنم؟</p><h2>{html.escape(action)}</h2></article>'
        '</section>'
    )

    timeline = _timeline(report)
    sources = _sources_html(report.get("source_health", {}))
    candidates = "".join(_candidate_html(candidate, run_dir) for candidate in report.get("candidates", []))
    fixes = "".join(_fix_html(fix) for fix in report.get("fixes", []))
    findings = candidates + fixes
    if not findings:
        findings = '<div class="empty good"><h2>✅ مشکل قابل اقدامی پیدا نشد</h2><p>هیچ باگی که نیاز به بررسی یا اصلاح داشته باشد دیده نشد.</p></div>'

    raw = html.escape(json.dumps(report, ensure_ascii=False, indent=2))
    body = (
        overview
        + '<section><h2 class="section-title">دیشب دقیقاً چه اتفاقی افتاد؟</h2>' + timeline + '</section>'
        + '<section><h2 class="section-title">وضعیت منابع پایش</h2>' + sources + '</section>'
        + '<section><h2 class="section-title">یافته‌ها و میزان قطعیت</h2>' + findings + '</section>'
        + f'<details class="technical"><summary>گزارش فنی کامل (برای توسعه‌دهنده)</summary><pre>{raw}</pre></details>'
    )
    return _shell(f"گزارش {started}", body, show_title=False)


def _candidate_html(candidate: dict, run_dir: Path) -> str:
    status_key = candidate.get("status", "detected")
    icon, label = STATUS.get(status_key, ("⚪", str(status_key)))
    confidence = round(float(candidate.get("confidence", 0)) * 100)
    evidence = html.escape(json.dumps(candidate.get("evidence", []), ensure_ascii=False, indent=2))
    status_note = ""
    if status_key == "detected":
        status_note = (
            '<div class="notice">این مورد هنوز باگ اثبات‌شده نیست. فقط یک نشانه دیده شده و '
            'برای تغییر کد باید ابتدا با تست روی نسخهٔ قبلی بازسازی شود.</div>'
        )
    return (
        '<article class="finding">'
        f'<div class="finding-head"><h2>{icon} {html.escape(candidate.get("title_fa", "یافته"))}</h2>'
        f'<span class="badge">{html.escape(label)}</span></div>'
        f'<p>{html.escape(candidate.get("problem_fa", candidate.get("summary_fa", "")))}</p>'
        f'<p class="confidence">اطمینان تحلیل: {_fa_number(confidence)}٪</p>'
        f'{status_note}'
        f'<details><summary>چرا عامل این مورد را مطرح کرد؟</summary><p>{html.escape(candidate.get("reproducible_hint", "نیازمند بازسازی کنترل‌شده است."))}</p></details>'
        f'<details><summary>شواهد فنی پاک‌سازی‌شده</summary><pre>{evidence}</pre></details>'
        f'{_media(run_dir, candidate.get("fingerprint", ""))}'
        '</article>'
    )


def _fix_html(fix: dict) -> str:
    status_key = fix.get("status", "insufficient_evidence")
    icon, label = STATUS.get(status_key, ("⚪", str(status_key)))
    pr_link = fix.get("pr_url")
    return (
        '<article class="finding">'
        f'<div class="finding-head"><h2>{icon} {html.escape(fix.get("title_fa", "نتیجه اصلاح"))}</h2>'
        f'<span class="badge">{html.escape(label)}</span></div>'
        f'<p>{html.escape(fix.get("summary_fa", ""))}</p>'
        f'<p><b>نظر بازبین مستقل:</b> {html.escape(fix.get("review_fa", "هنوز بررسی نشده"))}</p>'
        f'{f"<a class=\"button\" href=\"{html.escape(pr_link, quote=True)}\">مشاهده PR</a>" if pr_link else ""}'
        '</article>'
    )


def _short_outcome(report: dict) -> str:
    if report.get("status") != "completed":
        return "اجرا کامل نشد؛ جزئیات خطا داخل گزارش است."
    fixes = report.get("fixes", [])
    candidates = report.get("candidates", [])
    if any(item.get("status") == "ready_for_review" for item in fixes):
        return "یک اصلاح با تست و بازبینی آمادهٔ تصمیم شماست."
    if fixes:
        return f"{_fa_number(len(fixes))} تلاش اصلاح انجام شد؛ نتیجه داخل گزارش آمده است."
    if candidates:
        return f"{_fa_number(len(candidates))} سیگنال نیازمند بررسی دیده شد؛ هنوز باگی با تست اثبات نشده است."
    return "مشکل قابل اقدامی پیدا نشد."


def _next_action(report: dict) -> str:
    if report.get("status") != "completed":
        return "جزئیات خطا را بررسی کن؛ هیچ تغییری روی محصول اعمال نشده است."
    fixes = report.get("fixes", [])
    if any(item.get("status") == "ready_for_review" for item in fixes):
        return "PR را ببین و فقط اگر شواهد برایت روشن بود، دربارهٔ merge تصمیم بگیر."
    if report.get("phase") == "report_only":
        return "فعلاً کاری از شما لازم نیست؛ عامل در این مرحله اجازه تغییر کد نداشت."
    if report.get("phase") == "monitoring":
        return "فعلاً کاری لازم نیست؛ این نوبت فقط پایش بود و پنجرهٔ اصلاح روزانه جداست."
    if report.get("candidates") and not fixes:
        return "فعلاً اقدامی نکن؛ شواهد برای یک اصلاح امن کافی نبوده است."
    return "کاری لازم نیست؛ اجرای بعدی به‌صورت خودکار انجام می‌شود."


def _run_kind_label(report: dict) -> str:
    return "اجرای شبانهٔ خودکار" if report.get("run_kind") == "scheduled" else "اجرای آزمایشی دستی"


def _timeline(report: dict) -> str:
    signals = report.get("signals", [])
    traffic = sum(
        int(signal.get("evidence", {}).get("observation_count", signal.get("count", 0)) or 0)
        for signal in signals if signal.get("event") == "clarity_traffic"
    )
    product_signals = [signal for signal in signals if signal.get("event") != "clarity_traffic"]
    steps = [f"اجرا در {_format_time(report.get('started_at'))} شروع شد."]
    source_health = report.get("source_health", {})
    healthy = sum(str(value).startswith("ok") for value in source_health.values())
    steps.append(f"{_fa_number(healthy)} از {_fa_number(len(source_health))} منبع پایش بررسی شدند.")
    if traffic:
        steps.append(f"Clarity در بازهٔ پایش {_fa_number(traffic)} نشست کاربری ثبت کرده بود.")
    for signal in product_signals[:5]:
        event = EVENTS.get(signal.get("event", ""), str(signal.get("event", "رخداد")))
        count = int(signal.get("count", 1) or 1)
        batch = signal.get("evidence", {}).get("batch_id")
        context = f" در یک گروه کاری (شمارهٔ فنی {_fa_number(batch)})" if batch is not None else ""
        steps.append(f"{event}{context}، {_fa_number(count)} بار ثبت شد.")
    if report.get("candidates"):
        steps.append("عامل شواهد را تحلیل کرد، اما هنوز هیچ باگی با regression test اثبات نشد.")
    if report.get("phase") == "report_only":
        steps.append("به‌دلیل دورهٔ هفت‌شبِ فقط‌گزارش، کد تغییر نکرد، تست اصلاح اجرا نشد و PR ساخته نشد.")
    elif report.get("phase") == "monitoring":
        steps.append("این نوبت پایش سه‌ساعته بود؛ برای جلوگیری از اصلاح تکراری، کد فقط در پنجرهٔ روزانه می‌تواند تغییر کند.")
    elif not report.get("fixes"):
        steps.append("شواهد برای شروع اصلاح خودکار کافی نبود؛ کد و محصول دست‌نخورده ماندند.")
    return '<ol class="timeline">' + "".join(f"<li>{html.escape(step)}</li>" for step in steps) + "</ol>"


def _sources_html(source_health: dict) -> str:
    healthy = sum(str(value).startswith("ok") for value in source_health.values())
    total = len(source_health)
    lead = (
        f"هر {_fa_number(total)} منبع با موفقیت بررسی شدند."
        if total and healthy == total
        else f"{_fa_number(healthy)} از {_fa_number(total)} منبع در دسترس بودند."
    )
    cards = []
    for key, value in source_health.items():
        ok = str(value).startswith("ok")
        cards.append(
            f'<div class="source {"ok" if ok else "warn"}"><b>{"✓" if ok else "!"} {html.escape(SOURCES.get(key, key))}</b>'
            f'<span>{"بررسی شد" if ok else html.escape(str(value))}</span></div>'
        )
    return f'<p>{lead}</p><div class="sources">{"".join(cards)}</div>'


def _format_time(value: object) -> str:
    parsed = _parse_time(value)
    if parsed is None:
        return "زمان نامشخص"
    local = parsed.astimezone(TEHRAN)
    rendered = f"{local.day} {MONTHS_FA[local.month - 1]} {local.year}، ساعت {local:%H:%M}"
    return _fa_number(rendered)


def _duration_text(started: object, finished: object) -> str:
    start, finish = _parse_time(started), _parse_time(finished)
    if start is None or finish is None:
        return "نامشخص"
    seconds = max(0, round((finish - start).total_seconds()))
    if seconds < 60:
        return f"{_fa_number(seconds)} ثانیه"
    minutes, remaining = divmod(seconds, 60)
    return f"{_fa_number(minutes)} دقیقه و {_fa_number(remaining)} ثانیه"


def _parse_time(value: object) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed
    except ValueError:
        return None


def _fa_number(value: object) -> str:
    return str(value).translate(PERSIAN_DIGITS)


def _media(run_dir: Path, fingerprint: str) -> str:
    evidence_dir = run_dir / "evidence" / fingerprint
    pieces: list[str] = []
    for name, caption in (("before.png", "قبل از اصلاح"), ("after.png", "بعد از اصلاح")):
        path = evidence_dir / name
        if path.exists():
            pieces.append(f'<figure><img src="{path.as_uri()}" alt="{caption}"><figcaption>{caption}</figcaption></figure>')
    video = evidence_dir / "scenario.webm"
    if video.exists():
        pieces.append(f'<video controls src="{video.as_uri()}"></video>')
    return '<div class="media">' + "".join(pieces) + "</div>" if pieces else ""


def _shell(title: str, body: str, *, show_title: bool = True) -> str:
    title_html = f"<h1>{html.escape(title)}</h1>" if show_title else ""
    return f'''<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>
:root{{--ink:#172522;--muted:#60706c;--brand:#126b5c;--line:#dfe7e5;--paper:#fff;--bg:#f4f7f6;--soft:#edf6f4;--amber:#fff8e6}}
*{{box-sizing:border-box}}body{{font-family:Tahoma,"Segoe UI",sans-serif;background:var(--bg);color:var(--ink);margin:0;padding:28px;line-height:1.9}}
main{{max-width:1040px;margin:auto}}h1,h2{{line-height:1.45;margin-top:0}}h1{{color:var(--brand);font-size:clamp(1.6rem,4vw,2.35rem)}}h2{{font-size:1.12rem}}a{{color:#075fbc}}
.hero{{padding:12px 2px 20px}}.hero p{{color:var(--muted);margin:.35rem 0}}.eyebrow{{font-size:.78rem;font-weight:bold;color:var(--brand)!important;margin:0 0 4px!important}}
.summary-grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}article,.empty,.technical,.timeline{{background:var(--paper);border:1px solid var(--line);border-radius:16px;padding:20px;margin:14px 0;box-shadow:0 5px 20px #00000008}}
.summary{{border-top:4px solid var(--brand);margin:0}}.summary.action{{border-top-color:#d39400}}.summary h2{{margin:0}}.section-title{{margin:34px 0 8px;color:var(--brand)}}
.timeline{{list-style:none;counter-reset:step;padding:12px 20px}}.timeline li{{counter-increment:step;position:relative;padding:10px 46px 10px 0;border-bottom:1px solid #edf1f0}}.timeline li:last-child{{border:0}}.timeline li:before{{content:counter(step);position:absolute;right:0;top:9px;background:var(--soft);color:var(--brand);width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-weight:bold}}
.sources{{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:10px}}.source{{display:flex;flex-direction:column;padding:12px;border-radius:12px;background:var(--soft)}}.source span,.muted{{color:var(--muted);font-size:.88rem}}.source.warn{{background:#fff0ed}}
.finding-head{{display:flex;gap:10px;align-items:center;justify-content:space-between;flex-wrap:wrap}}.badge{{display:inline-block;background:var(--amber);border-radius:20px;padding:2px 12px;font-size:.82rem}}.notice{{background:var(--amber);border-right:4px solid #d39400;padding:12px;border-radius:10px}}.confidence{{font-weight:bold}}
.button{{display:inline-block;text-decoration:none;background:var(--brand);color:white;padding:8px 16px;border-radius:10px;margin-top:6px}}details{{margin-top:14px}}summary{{cursor:pointer;font-weight:bold}}pre{{direction:ltr;text-align:left;white-space:pre-wrap;overflow-wrap:anywhere;background:#10201d;color:#d8eee9;padding:14px;border-radius:10px;font-size:.82rem}}.technical{{margin-top:36px}}.run-card h2{{margin-bottom:0}}.run-id{{color:var(--muted);font-size:.78rem}}.good{{border-right:5px solid #3b9b72}}
.media{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}}img,video{{max-width:100%;border-radius:10px;border:1px solid #ddd}}figure{{margin:0}}
@media(max-width:700px){{body{{padding:16px}}.summary-grid{{grid-template-columns:1fr}}article,.empty,.technical,.timeline{{padding:16px}}}}
</style></head><body><main>{title_html}{body}</main></body></html>'''
