"""Non-streaming pass-through. The upstream is always mocked; no real API calls."""

import json

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from shoji.app import create_app
from shoji.config import PROVIDER_BASE_URLS, Settings

GROQ = PROVIDER_BASE_URLS["groq"]

COMPLETION = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "model": "test-model",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello there."},
            "finish_reason": "stop",
        }
    ],
}


def make_settings(**overrides) -> Settings:
    values = {"shoji_provider": "groq", "groq_api_key": "test-key", **overrides}
    return Settings(_env_file=None, **values)


@pytest.fixture
def client():
    with TestClient(create_app(make_settings())) as c:
        yield c


@respx.mock
def test_forwards_body_and_proxy_key(client):
    route = respx.post(f"{GROQ}/chat/completions").mock(
        return_value=httpx.Response(200, json=COMPLETION)
    )
    payload = {"model": "test-model", "messages": [{"role": "user", "content": "Hi"}]}

    resp = client.post(
        "/v1/chat/completions",
        json=payload,
        headers={"Authorization": "Bearer client-key-must-not-leak"},
    )

    assert resp.status_code == 200
    assert resp.json() == COMPLETION
    sent = route.calls.last.request
    assert json.loads(sent.content) == payload
    assert sent.headers["Authorization"] == "Bearer test-key"


@respx.mock
def test_upstream_error_status_and_body_pass_through(client):
    error = {"error": {"message": "Rate limit reached", "type": "rate_limit"}}
    respx.post(f"{GROQ}/chat/completions").mock(return_value=httpx.Response(429, json=error))

    resp = client.post("/v1/chat/completions", json={"model": "m", "messages": []})

    assert resp.status_code == 429
    assert resp.json() == error


@respx.mock
def test_default_model_fills_missing_model():
    route = respx.post(f"{GROQ}/chat/completions").mock(
        return_value=httpx.Response(200, json=COMPLETION)
    )
    app = create_app(make_settings(shoji_default_model="fallback-model"))
    with TestClient(app) as c:
        c.post("/v1/chat/completions", json={"messages": []})

    assert json.loads(route.calls.last.request.content)["model"] == "fallback-model"


@respx.mock
def test_explicit_model_is_not_overridden():
    route = respx.post(f"{GROQ}/chat/completions").mock(
        return_value=httpx.Response(200, json=COMPLETION)
    )
    app = create_app(make_settings(shoji_default_model="fallback-model"))
    with TestClient(app) as c:
        c.post("/v1/chat/completions", json={"model": "chosen", "messages": []})

    assert json.loads(route.calls.last.request.content)["model"] == "chosen"


def test_invalid_json_returns_openai_style_error(client):
    resp = client.post(
        "/v1/chat/completions",
        content=b"not json",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert "message" in resp.json()["error"]


def test_non_object_body_rejected(client):
    resp = client.post("/v1/chat/completions", json=[1, 2])
    assert resp.status_code == 400


SSE_EVENTS = [
    b'data: {"choices":[{"delta":{"content":"Hel"}}]}\n\n',
    b'data: {"choices":[{"delta":{"content":"lo"}}]}\n\n',
    b"data: [DONE]\n\n",
]


@respx.mock
def test_stream_relays_events_in_order_with_done(client):
    # Network chunks deliberately cut events in half.
    raw = b"".join(SSE_EVENTS)
    chunks = [raw[:10], raw[10:60], raw[60:]]

    async def upstream_body():
        for chunk in chunks:
            yield chunk

    route = respx.post(f"{GROQ}/chat/completions").mock(
        return_value=httpx.Response(
            200, content=upstream_body(), headers={"content-type": "text/event-stream"}
        )
    )
    payload = {"model": "m", "messages": [], "stream": True}

    with client.stream("POST", "/v1/chat/completions", json=payload) as resp:
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/event-stream")
        received = b"".join(resp.iter_bytes())

    assert received == raw
    assert received.endswith(b"data: [DONE]\n\n")
    assert json.loads(route.calls.last.request.content)["stream"] is True


@respx.mock
def test_stream_request_upstream_error_returns_json(client):
    error = {"error": {"message": "Invalid model", "type": "invalid_request_error"}}
    respx.post(f"{GROQ}/chat/completions").mock(return_value=httpx.Response(400, json=error))

    resp = client.post("/v1/chat/completions", json={"model": "x", "messages": [], "stream": True})

    assert resp.status_code == 400
    assert resp.json() == error


def test_health(client):
    assert client.get("/health").json() == {"status": "ok", "provider": "groq"}


def test_switching_provider_is_config_only():
    gemini = make_settings(shoji_provider="gemini", gemini_api_key="g-key").provider()
    assert gemini.base_url == PROVIDER_BASE_URLS["gemini"]
    assert gemini.api_key == "g-key"


def test_unknown_provider_fails_fast():
    with pytest.raises(ValueError, match="Unknown provider"):
        make_settings(shoji_provider="nope").provider()
