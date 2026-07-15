import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from fastapi import Request, Response

if TYPE_CHECKING:
    from .config import Settings
    from sqlalchemy.orm import Session, sessionmaker


logger = logging.getLogger("app.http")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")
FIELD_PATTERN = re.compile(r"(?P<key>[A-Za-z][A-Za-z0-9_]*)=(?P<value>[^\s]+)")
SENSITIVE_KEY_PATTERN = re.compile(
    r"(token|secret|password|authorization|mobile|phone|transcript|voice|oauth_code|state|payload)",
    re.IGNORECASE,
)
SENSITIVE_VALUE_PATTERNS = (
    re.compile(r"(?i)(bearer\s+)[^\s]+"),
    re.compile(r"(?i)(access_token|refresh_token|client_secret|password)=([^\s&]+)"),
)
SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(token|secret|password|authorization|mobile|phone|transcript|voice|oauth_code|state|payload|access_token|refresh_token|client_secret)=([^\s&]+)"
)
SENTRY_SESSION_ASSIGNMENT_PATTERN = re.compile(r"(?i)\b(request_id|session_key)=([^\s&]+)")
PERSISTED_EVENTS = {
    "http_request_failed",
    "http_response_failed",
    "upload_batch_failed",
    "image_upload_rejected",
    "image_picker_blocked",
    "image_picker_opened",
    "image_files_selected",
    "image_picker_cancelled",
    "ui_rage_click",
    "ui_dead_click",
    "ui_action_started",
    "ui_action_accepted",
    "ui_action_blocked",
    "ui_action_failed",
    "frontend_runtime_failed",
    "processing_job_failed",
    "basalam_oauth_failed",
    "basalam_oauth_restore_started",
    "basalam_oauth_restore_succeeded",
    "basalam_oauth_restore_failed",
    "journey_step",
    "basalam_publish_validation_failed",
    "basalam_product_failed",
    "basalam_publish_failed",
    "torob_publish_failed",
}
PERSISTED_FIELDS = {
    "request_id", "job_id", "batch_id", "stage", "code", "status_code",
    "method", "path", "duration_ms", "attempts", "item_id", "submission_id", "platform",
    # Safe image diagnostics let the read-only agent distinguish a corrupt or
    # unsupported file from a product regression without storing the image/name.
    "suffix", "declared_mime", "input_bytes", "error_type", "control", "reason", "attempt_id", "file_count",
    "session_key",
    "batch_item_id", "connection_id", "http_status", "category_id", "unit_type", "request_status", "photo_count",
    "click_count", "image_number", "outcome", "failure_field", "surface",
    "expected_asset_count", "expected_item_count", "restored_asset_count", "restored_item_count",
    "journey", "journey_id", "actual_asset_count", "actual_item_count",
}


class JsonLogFormatter(logging.Formatter):
    """One JSON object per stdout line, while keeping existing log calls useful."""

    def __init__(self, environment: str, release: str | None):
        super().__init__()
        self.environment = environment
        self.release = release

    def format(self, record: logging.LogRecord) -> str:
        message = redact_text(record.getMessage())
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "severity": record.levelname.lower(),
            "logger": record.name,
            "environment": self.environment,
            "event": message.split(" ", 1)[0] if message else "log",
            "message": message,
        }
        if self.release:
            payload["release"] = self.release
        for match in FIELD_PATTERN.finditer(message):
            key, value = match.group("key"), match.group("value")
            if not SENSITIVE_KEY_PATTERN.search(key):
                payload[key] = _coerce_log_value(value)
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__ if record.exc_info[0] else "Exception"
            payload["traceback"] = redact_text(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_observability(settings: "Settings") -> None:
    if settings.structured_logs:
        root = logging.getLogger()
        handler = next(
            (item for item in root.handlers if getattr(item, "_bulkadd_json_handler", False)),
            None,
        )
        if handler is None:
            handler = logging.StreamHandler(sys.stdout)
            handler._bulkadd_json_handler = True  # type: ignore[attr-defined]
            root.addHandler(handler)
        handler.setFormatter(JsonLogFormatter(settings.environment, settings.release))
        root.setLevel(logging.INFO)

    if settings.sentry_dsn:
        import sentry_sdk
        from sentry_sdk.integrations.logging import LoggingIntegration

        sentry_sdk.init(
            dsn=settings.sentry_dsn,
            environment=settings.environment,
            release=settings.release,
            traces_sample_rate=settings.sentry_traces_sample_rate,
            send_default_pii=False,
            before_send=_before_send,
            before_send_transaction=_before_send,
            integrations=[LoggingIntegration(level=logging.INFO, event_level=logging.WARNING)],
        )


class OperationalEventHandler(logging.Handler):
    """Persist only allowlisted failure metadata; never messages or tracebacks."""

    _bulkadd_event_store = True

    def __init__(self, session_factory: "sessionmaker[Session]", environment: str, release: str | None):
        super().__init__(level=logging.INFO)
        self.session_factory = session_factory
        self.environment = environment
        self.release_name = release

    def emit(self, record: logging.LogRecord) -> None:
        try:
            from .models import OperationalEvent

            message = record.getMessage()
            event = message.split(" ", 1)[0] if message else ""
            if event not in PERSISTED_EVENTS:
                return
            fields = {
                match.group("key"): _coerce_log_value(match.group("value"))
                for match in FIELD_PATTERN.finditer(message)
                if match.group("key") in PERSISTED_FIELDS
            }
            known = {key: fields.pop(key, None) for key in ("request_id", "job_id", "batch_id", "stage", "code")}
            with self.session_factory() as session:
                session.query(OperationalEvent).filter(
                    OperationalEvent.created_at < datetime.now(timezone.utc) - timedelta(days=30)
                ).delete(synchronize_session=False)
                session.add(
                    OperationalEvent(
                        event=event,
                        severity=record.levelname.lower(),
                        environment=self.environment,
                        release=self.release_name,
                        context=fields or None,
                        **known,
                    )
                )
                session.commit()
        except Exception:
            # Observability failure must not break the product or echo sensitive records.
            return


def configure_event_store(
    session_factory: "sessionmaker[Session]", settings: "Settings"
) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_bulkadd_event_store", False):
            root.removeHandler(handler)
            handler.close()
    root.addHandler(OperationalEventHandler(session_factory, settings.environment, settings.release))


def redact_text(value: str) -> str:
    redacted = SENSITIVE_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}=[REDACTED]", value
    )
    for pattern in SENSITIVE_VALUE_PATTERNS:
        redacted = pattern.sub(_redacted_match, redacted)
    return redacted


def _redacted_match(match: re.Match[str]) -> str:
    if match.lastindex and match.lastindex >= 2 and match.group(2):
        return f"{match.group(1)}=[REDACTED]"
    if match.group(1):
        return f"{match.group(1)}[REDACTED]"
    return "[REDACTED]"


def _before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any] | None:
    request = event.get("request")
    if isinstance(request, dict):
        request.pop("data", None)
        request.pop("cookies", None)
        request.pop("query_string", None)
        if isinstance(request.get("url"), str):
            request["url"] = request["url"].split("?", 1)[0].split("#", 1)[0]
        request["headers"] = {
            key: value
            for key, value in (request.get("headers") or {}).items()
            if key.lower() not in {"authorization", "cookie", "x-admin-password", "x-request-id"}
        }
    event.pop("user", None)
    return _redact_sentry_session_ids(_redact_mapping(event))


def _redact_sentry_session_ids(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if str(key).lower() in {"request_id", "session_key"} else _redact_sentry_session_ids(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_sentry_session_ids(item) for item in value]
    if isinstance(value, str):
        return SENTRY_SESSION_ASSIGNMENT_PATTERN.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)
    return value


def _redact_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE_KEY_PATTERN.search(str(key)) else _redact_mapping(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_mapping(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _coerce_log_value(value: str) -> str | int | float | bool | None:
    if value == "None":
        return None
    if value in {"True", "False"}:
        return value == "True"
    try:
        return int(value)
    except ValueError:
        try:
            return float(value)
        except ValueError:
            return value


def safe_request_id(value: str | None) -> str:
    if value and REQUEST_ID_PATTERN.fullmatch(value):
        return value
    return uuid.uuid4().hex


async def observe_http_request(request: Request, call_next) -> Response:
    request_id = safe_request_id(request.headers.get("X-Request-ID"))
    request.state.request_id = request_id
    started = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception(
            "http_request_failed request_id=%s method=%s path=%s duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            _duration_ms(started),
        )
        raise

    response.headers["X-Request-ID"] = request_id
    if response.status_code >= 500:
        logger.error(
            "http_response_failed request_id=%s method=%s path=%s status_code=%s duration_ms=%s",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            _duration_ms(started),
        )
    return response


def _duration_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))
