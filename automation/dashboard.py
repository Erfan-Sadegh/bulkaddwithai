from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import quote


STATUS = {
    "detected": ("🔴", "مشکل دیده شده"),
    "reproduced": ("🟠", "مشکل بازسازی شده"),
    "fixed_in_test": ("🟠", "در محیط تست رفع شده"),
    "ready_for_review": ("🔵", "آماده بررسی شما"),
    "deployed": ("🔵", "منتشر شده؛ در حال پایش"),
    "confirmed_production": ("🟢", "در production تأیید شده"),
    "insufficient_evidence": ("⚪", "داده کافی نیست"),
    "rejected": ("⚫", "تغییر رد شد"),
}


def write_run_report(run_dir: Path, report: dict) -> Path:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    page = _run_html(report, run_dir)
    target = run_dir / "report.html"
    target.write_text(page, encoding="utf-8")
    return target


def rebuild_dashboard(state_root: Path) -> Path:
    dashboard_dir = state_root / "dashboard"
    dashboard_dir.mkdir(parents=True, exist_ok=True)
    reports: list[tuple[dict, Path]] = []
    for report_path in sorted((state_root / "runs").glob("*/report.json"), reverse=True):
        try:
            reports.append((json.loads(report_path.read_text(encoding="utf-8")), report_path.parent))
        except (OSError, json.JSONDecodeError):
            continue
    cards = []
    for report, directory in reports[:100]:
        link = directory.joinpath("report.html").as_uri()
        signal_count = len(report.get("signals", []))
        fix_count = len(report.get("fixes", []))
        cards.append(
            f'<article><h2>{html.escape(report.get("run_id", ""))}</h2>'
            f'<p>وضعیت اجرا: <b>{html.escape(report.get("status", ""))}</b></p>'
            f'<p>{signal_count} سیگنال و {fix_count} تلاش اصلاح</p>'
            f'<a href="{html.escape(link)}">مشاهده گزارش کامل</a></article>'
        )
    body = "".join(cards) or "<p>هنوز گزارشی ساخته نشده است.</p>"
    target = dashboard_dir / "index.html"
    target.write_text(_shell("داشبورد عامل BulkAddWithAI", body), encoding="utf-8")
    return target


def _run_html(report: dict, run_dir: Path) -> str:
    sections: list[str] = []
    for candidate in report.get("candidates", []):
        status_key = candidate.get("status", "detected")
        icon, label = STATUS.get(status_key, ("⚪", status_key))
        evidence = html.escape(json.dumps(candidate.get("evidence", []), ensure_ascii=False, indent=2))
        sections.append(
            f'<article><h2>{icon} {html.escape(candidate.get("title_fa", candidate.get("event", "مشکل")))}</h2>'
            f'<p class="badge">{html.escape(label)}</p>'
            f'<p>{html.escape(candidate.get("problem_fa", candidate.get("summary_fa", "")))}</p>'
            f'<details><summary>شواهد فنی پاک‌سازی‌شده</summary><pre>{evidence}</pre></details>'
            f'{_media(run_dir, candidate.get("fingerprint", ""))}</article>'
        )
    for fix in report.get("fixes", []):
        status_key = fix.get("status", "insufficient_evidence")
        icon, label = STATUS.get(status_key, ("⚪", status_key))
        pr_link = fix.get("pr_url")
        sections.append(
            f'<article><h2>{icon} {html.escape(fix.get("title_fa", "نتیجه اصلاح"))}</h2>'
            f'<p class="badge">{html.escape(label)}</p><p>{html.escape(fix.get("summary_fa", ""))}</p>'
            f'<p>نظر بازبین: {html.escape(fix.get("review_fa", "هنوز بررسی نشده"))}</p>'
            f'{f"<a href=\"{html.escape(pr_link, quote=True)}\">مشاهده PR</a>" if pr_link else ""}</article>'
        )
    if not sections:
        sections.append("<p>در این اجرا مشکل قابل اقدامی پیدا نشد.</p>")
    heading = f'<p>مرحله: {html.escape(report.get("phase", ""))} — وضعیت: {html.escape(report.get("status", ""))}</p>'
    sources = "، ".join(f"{html.escape(k)}: {html.escape(v)}" for k, v in report.get("source_health", {}).items())
    return _shell(f'گزارش {report.get("run_id", "")}', heading + f"<p>منابع: {sources}</p>" + "".join(sections))


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


def _shell(title: str, body: str) -> str:
    return f"""<!doctype html><html lang="fa" dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(title)}</title>
<style>body{{font-family:Tahoma,sans-serif;background:#f5f7f8;color:#182321;margin:0;padding:24px;line-height:1.8}}main{{max-width:960px;margin:auto}}article{{background:white;border:1px solid #dfe7e5;border-radius:16px;padding:20px;margin:16px 0;box-shadow:0 4px 18px #0000000b}}h1,h2{{color:#126b5c}}a{{color:#075fbc}}.badge{{display:inline-block;background:#edf6f4;border-radius:20px;padding:2px 12px}}pre{{direction:ltr;text-align:left;white-space:pre-wrap;background:#10201d;color:#d8eee9;padding:12px;border-radius:10px}}.media{{display:grid;grid-template-columns:repeat(auto-fit,minmax(250px,1fr));gap:12px}}img,video{{max-width:100%;border-radius:10px;border:1px solid #ddd}}figure{{margin:0}}</style></head><body><main><h1>{html.escape(title)}</h1>{body}</main></body></html>"""
