import logging

import pytest


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
