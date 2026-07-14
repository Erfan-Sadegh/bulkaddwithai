import logging
import re
import time
import uuid

from fastapi import Request, Response


logger = logging.getLogger("app.http")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,64}$")


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
