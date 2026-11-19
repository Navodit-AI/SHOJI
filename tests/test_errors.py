"""Upstream errors, timeouts and retries. The upstream is always mocked."""

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from shoji.app import create_app
from shoji.config import PROVIDER_BASE_URLS, Settings
from shoji.streaming import relay

URL = f"{PROVIDER_BASE_URLS['groq']}/chat/completions"
PAYLOAD = {"model": "m", "messages": [{"role": "user", "content": "Hi"}]}
OK = {"id": "chatcmpl-1", "choices": []}
OPENAI_ERROR = {"error": {"message": "Service unavailable", "type": "server_error"}}


@pytest.fixture
def client():
    settings = Settings(
        _env_file=None,
        groq_api_key="test-key",
        shoji_retry_backoff=0,
        shoji_upstream_timeout=5,
    )
    with TestClient(create_app(settings)) as c:
        yield c


def assert_openai_error(resp, status, err_type):
    assert resp.status_code == status
    error = resp.json()["error"]
    assert error["type"] == err_type
    assert error["message"]


# --- Retries -------------------------------------------------------------------------------


@respx.mock
def test_5xx_is_retried_once_then_succeeds(client):
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(503, json=OPENAI_ERROR), httpx.Response(200, json=OK)]
    )
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert resp.status_code == 200
    assert route.call_count == 2


@respx.mock
def test_persistent_5xx_returned_after_one_retry(client):
    route = respx.post(URL).mock(return_value=httpx.Response(503, json=OPENAI_ERROR))
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert resp.status_code == 503
    assert resp.json() == OPENAI_ERROR
    assert route.call_count == 2


@pytest.mark.parametrize("status", [400, 401, 404, 429])
@respx.mock
def test_4xx_is_not_retried(client, status):
    route = respx.post(URL).mock(return_value=httpx.Response(status, json=OPENAI_ERROR))
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert resp.status_code == status
    assert route.call_count == 1


@respx.mock
def test_connection_error_is_retried_then_succeeds(client):
    route = respx.post(URL).mock(
        side_effect=[httpx.ConnectError("refused"), httpx.Response(200, json=OK)]
    )
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert resp.status_code == 200
    assert route.call_count == 2


@respx.mock
def test_persistent_connection_error_returns_502(client):
    route = respx.post(URL).mock(side_effect=httpx.ConnectError("refused"))
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert_openai_error(resp, 502, "upstream_unavailable")
    assert route.call_count == 2


# --- Timeouts ------------------------------------------------------------------------------


@respx.mock
def test_read_timeout_returns_504_without_retry(client):
    route = respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert_openai_error(resp, 504, "upstream_timeout")
    assert "5s" in resp.json()["error"]["message"]
    assert route.call_count == 1


@respx.mock
def test_connect_timeout_is_retried_then_returns_504(client):
    route = respx.post(URL).mock(side_effect=httpx.ConnectTimeout("no route"))
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert_openai_error(resp, 504, "upstream_timeout")
    assert route.call_count == 2


# --- Error shape ---------------------------------------------------------------------------


@respx.mock
def test_non_json_upstream_error_is_wrapped(client):
    respx.post(URL).mock(
        return_value=httpx.Response(502, text="<html>Bad Gateway</html>", headers={})
    )
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert_openai_error(resp, 502, "upstream_error")


@respx.mock
def test_json_without_error_key_is_wrapped(client):
    respx.post(URL).mock(return_value=httpx.Response(400, json={"detail": "bad"}))
    resp = client.post("/v1/chat/completions", json=PAYLOAD)
    assert_openai_error(resp, 400, "upstream_error")


# --- Streaming -----------------------------------------------------------------------------


@respx.mock
def test_stream_5xx_before_start_is_retried(client):
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(503, json=OPENAI_ERROR),
            httpx.Response(
                200,
                content=b"data: [DONE]\n\n",
                headers={"content-type": "text/event-stream"},
            ),
        ]
    )
    with client.stream("POST", "/v1/chat/completions", json={**PAYLOAD, "stream": True}) as resp:
        assert resp.status_code == 200
        assert b"".join(resp.iter_bytes()) == b"data: [DONE]\n\n"
    assert route.call_count == 2


@respx.mock
def test_stream_timeout_before_start_returns_504(client):
    respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    resp = client.post("/v1/chat/completions", json={**PAYLOAD, "stream": True})
    assert_openai_error(resp, 504, "upstream_timeout")


async def test_mid_stream_failure_ends_with_error_event_and_closes_upstream():
    closed = False

    async def close():
        nonlocal closed
        closed = True

    async def dropping_upstream():
        yield b"data: first\n\n"
        yield b"data: partial-ev"
        raise httpx.ReadError("connection reset")

    events = [e async for e in relay(dropping_upstream(), close)]

    assert events[0] == b"data: first\n\n"
    assert len(events) == 2  # the half-received event is dropped, not sent broken
    assert b'"type": "upstream_error"' in events[1]
    assert closed
