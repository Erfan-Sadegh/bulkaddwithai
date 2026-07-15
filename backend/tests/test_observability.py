import logging
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Batch, BatchItem, PlatformConnection, PublishJob, PublishedProduct, Seller, OperationalEvent
from app.observability import JsonLogFormatter, _before_send, redact_text


def test_every_http_response_has_a_safe_request_id(client):
    response = client.get("/health", headers={"X-Request-ID": "clarity-session-123"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "clarity-session-123"

    generated = client.get("/health", headers={"X-Request-ID": "x" * 200}).headers["X-Request-ID"]
    assert len(generated) == 32
    assert generated != "x" * 200


def test_unhandled_http_failure_logs_request_context_without_query_string(client, caplog):
    @client.app.get("/_test_failure")
    def fail_for_test():
        raise RuntimeError("intentional test failure")

    with caplog.at_level(logging.ERROR, logger="app.http"):
        with pytest.raises(RuntimeError):
            client.get(
                "/_test_failure?code=oauth-secret-code",
                headers={"X-Request-ID": "request-test-42"},
            )

    assert "http_request_failed request_id=request-test-42 method=GET path=/_test_failure" in caplog.text
    assert "oauth-secret-code" not in caplog.text


def test_json_log_formatter_emits_searchable_safe_fields():
    formatter = JsonLogFormatter("production", "build-abc123")
    record = logging.LogRecord(
        "app.jobs",
        logging.ERROR,
        __file__,
        1,
        "processing_job_failed job_id=%s batch_id=%s stage=%s code=%s attempts=%s",
        (12, 8, "vision_extracting", "provider_temporary", 3),
        None,
    )

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "processing_job_failed"
    assert payload["job_id"] == 12
    assert payload["stage"] == "vision_extracting"
    assert payload["release"] == "build-abc123"


def test_json_log_formatter_redacts_sensitive_key_value_pairs_from_message():
    formatter = JsonLogFormatter("production", None)
    record = logging.LogRecord(
        "app.jobs",
        logging.ERROR,
        __file__,
        1,
        "processing_job_failed mobile=%s payload=%s",
        ("09120000000", "private-product-data"),
        None,
    )

    serialized = formatter.format(record)

    assert "09120000000" not in serialized
    assert "private-product-data" not in serialized
    assert serialized.count("[REDACTED]") == 2


def test_sentry_payload_and_text_are_redacted():
    event = {
        "user": {"phone": "09120000000"},
        "request": {
            "url": "https://example.test/callback?code=one-time-code",
            "query_string": "code=one-time-code",
            "headers": {"Authorization": "Bearer secret", "Accept": "application/json"},
            "data": {"mobile": "09120000000"},
        },
        "extra": {"access_token": "secret-token", "safe": "ok"},
    }

    scrubbed = _before_send(event, {})

    assert scrubbed is not None
    assert "user" not in scrubbed
    assert "query_string" not in scrubbed["request"]
    assert scrubbed["request"]["url"] == "https://example.test/callback"
    assert "Authorization" not in scrubbed["request"]["headers"]
    assert scrubbed["extra"]["access_token"] == "[REDACTED]"
    assert redact_text("Authorization: Bearer abcdefghijklmnop") == "Authorization: Bearer [REDACTED]"
    assert redact_text("access_token=abcdefghijk") == "access_token=[REDACTED]"


def test_production_event_feed_requires_its_own_read_only_token(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'events.db'}",
            upload_dir=tmp_path / "uploads",
            AI_PROVIDER="fake",
            OBSERVABILITY_READ_TOKEN="collector-only-token",
        )
    )

    with TestClient(app) as test_client:
        assert test_client.get("/observability/events").status_code == 401
        assert test_client.get(
            "/observability/events",
            headers={"Authorization": "Bearer wrong-token"},
        ).status_code == 401


def test_important_events_are_persisted_and_exported_without_sensitive_text(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'events.db'}",
            upload_dir=tmp_path / "uploads",
            AI_PROVIDER="fake",
            OBSERVABILITY_READ_TOKEN="collector-only-token",
        )
    )

    with TestClient(app) as test_client:
        logging.getLogger("app.jobs").error(
            "processing_job_failed job_id=%s batch_id=%s stage=%s code=%s "
            "mobile=%s access_token=%s",
            12,
            8,
            "vision_extracting",
            "provider_temporary",
            "09120000000",
            "super-secret-token",
        )
        logging.getLogger("app.jobs").info("ordinary_debug_message payload=private")

        response = test_client.get(
            "/observability/events",
            headers={"Authorization": "Bearer collector-only-token"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload) == 1
    assert payload[0]["event"] == "processing_job_failed"
    assert payload[0]["job_id"] == 12
    assert payload[0]["batch_id"] == 8
    assert payload[0]["stage"] == "vision_extracting"
    serialized = json.dumps(payload)
    assert "09120000000" not in serialized
    assert "super-secret-token" not in serialized
    assert "message" not in serialized


def test_rejected_image_feed_keeps_safe_diagnostic_fields(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'events.db'}",
            upload_dir=tmp_path / "uploads",
            AI_PROVIDER="fake",
            OBSERVABILITY_READ_TOKEN="collector-only-token",
        )
    )

    with TestClient(app) as test_client:
        logging.getLogger("app.uploads").warning(
            "image_upload_rejected batch_id=5 suffix=.heic declared_mime=image/heic "
            "input_bytes=2048 error_type=InvalidProductImageError"
        )
        response = test_client.get(
            "/observability/events",
            headers={"Authorization": "Bearer collector-only-token"},
        )

    event = response.json()[0]
    assert event["suffix"] == ".heic"
    assert event["declared_mime"] == "image/heic"
    assert event["input_bytes"] == 2048
    assert event["error_type"] == "InvalidProductImageError"


def test_public_ux_event_accepts_only_an_allowlisted_blocked_upload_signal(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'events.db'}",
            upload_dir=tmp_path / "uploads",
            AI_PROVIDER="fake",
            OBSERVABILITY_READ_TOKEN="collector-only-token",
        )
    )

    with TestClient(app) as test_client:
        accepted = test_client.post(
            "/observability/ux-events",
            json={
                "event": "image_picker_blocked",
                "control": "add_photo_button",
                "reason": "list_exists",
            },
        )
        rejected = test_client.post(
            "/observability/ux-events",
            json={"event": "arbitrary_event", "control": "secret", "reason": "anything"},
        )
        opened = test_client.post(
            "/observability/ux-events",
            json={
                "event": "image_picker_opened",
                "control": "photo_drop_zone",
                "attempt_id": "11111111-1111-4111-8111-111111111111",
            },
        )
        selected = test_client.post(
            "/observability/ux-events",
            json={
                "event": "image_files_selected",
                "control": "photo_drop_zone",
                "attempt_id": "11111111-1111-4111-8111-111111111111",
                "file_count": 2,
            },
        )
        invalid_selected = test_client.post(
            "/observability/ux-events",
            json={"event": "image_files_selected", "control": "photo_drop_zone", "file_count": 2},
        )
        rage = test_client.post(
            "/observability/ux-events",
            json={"event": "ui_rage_click", "control": "build_product_list", "click_count": 4},
        )
        invalid_rage = test_client.post(
            "/observability/ux-events",
            json={"event": "ui_rage_click", "control": "private_user_text", "click_count": 4},
        )
        action_started = test_client.post(
            "/observability/ux-events",
            json={
                "event": "ui_action_started",
                "control": "publish_basalam",
                "attempt_id": "22222222-2222-4222-8222-222222222222",
            },
        )
        action_failed = test_client.post(
            "/observability/ux-events",
            json={
                "event": "ui_action_failed",
                "control": "publish_basalam",
                "attempt_id": "22222222-2222-4222-8222-222222222222",
                "outcome": "server",
            },
        )
        invalid_action = test_client.post(
            "/observability/ux-events",
            json={
                "event": "ui_action_failed",
                "control": "publish_basalam",
                "attempt_id": "22222222-2222-4222-8222-222222222222",
                "outcome": "private provider message",
            },
        )
        feed = test_client.get(
            "/observability/events",
            headers={"Authorization": "Bearer collector-only-token"},
        )

    assert accepted.status_code == 204
    assert rejected.status_code == 422
    assert opened.status_code == 204
    assert selected.status_code == 204
    assert invalid_selected.status_code == 422
    assert rage.status_code == 204
    assert invalid_rage.status_code == 422
    assert action_started.status_code == 204
    assert action_failed.status_code == 204
    assert invalid_action.status_code == 422
    events = {item["event"]: item for item in feed.json()}
    assert events["image_picker_blocked"]["control"] == "add_photo_button"
    assert events["image_picker_blocked"]["reason"] == "list_exists"
    assert events["image_picker_opened"]["attempt_id"] == "11111111-1111-4111-8111-111111111111"
    assert events["image_files_selected"]["file_count"] == 2
    assert events["ui_rage_click"]["control"] == "build_product_list"
    assert events["ui_rage_click"]["click_count"] == 4
    assert events["ui_action_started"]["attempt_id"] == "22222222-2222-4222-8222-222222222222"
    assert events["ui_action_failed"]["control"] == "publish_basalam"
    assert events["ui_action_failed"]["outcome"] == "server"


def test_failed_published_product_is_exported_safely_even_without_transient_log_event(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'events.db'}",
            upload_dir=tmp_path / "uploads",
            AI_PROVIDER="fake",
            OBSERVABILITY_READ_TOKEN="collector-only-token",
        )
    )
    with app.state.session_factory() as session:
        seller = Seller(name="test", mobile="", shop_name="test")
        session.add(seller)
        session.flush()
        batch = Batch(seller_id=seller.id)
        session.add(batch)
        session.flush()
        item = BatchItem(batch_id=batch.id, title="private product title")
        connection = PlatformConnection(
            seller_id=seller.id,
            platform="basalam",
            external_shop_id="test-shop",
            external_shop_name="private shop",
            access_token="secret-token",
        )
        session.add_all([item, connection])
        session.flush()
        job = PublishJob(batch_id=batch.id, connection_id=connection.id, platform="basalam")
        session.add(job)
        session.flush()
        session.add(
            PublishedProduct(
                batch_item_id=item.id,
                publish_job_id=job.id,
                connection_id=connection.id,
                platform="basalam",
                status="failed",
                error="private provider error and product title",
                response_metadata={
                    "http_status": 422,
                    "response_text": '{"messages":[{"fields":["package_weight"],"message":"private value"}]}',
                    "request_payload_category_id": 485,
                    "request_payload_photo_count": 1,
                },
            )
        )
        session.commit()

    with TestClient(app) as test_client:
        response = test_client.get(
            "/observability/events",
            headers={"Authorization": "Bearer collector-only-token"},
        )

    assert response.status_code == 200
    event = response.json()[0]
    assert event["event"] == "basalam_product_failed"
    assert event["failure_field"] == "package_weight"
    assert event["http_status"] == 422
    assert event["category_id"] == 485
    assert event["photo_count"] == 1
    serialized = json.dumps(event)
    assert "private" not in serialized
    assert "secret-token" not in serialized


def test_operational_event_store_removes_expired_records(tmp_path):
    app = create_app(
        Settings(
            database_url=f"sqlite:///{tmp_path / 'events.db'}",
            upload_dir=tmp_path / "uploads",
            AI_PROVIDER="fake",
            OBSERVABILITY_READ_TOKEN="collector-only-token",
        )
    )
    with app.state.session_factory() as session:
        session.add(
            OperationalEvent(
                event="processing_job_failed",
                severity="error",
                environment="production",
                created_at=datetime.now(timezone.utc) - timedelta(days=31),
            )
        )
        session.commit()

    logging.getLogger("app.jobs").error(
        "processing_job_failed job_id=13 stage=vision_extracting code=provider_temporary"
    )

    with app.state.session_factory() as session:
        events = session.query(OperationalEvent).all()
    assert len(events) == 1
    assert events[0].job_id == 13
