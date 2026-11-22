"""Request capture and structured logging. The upstream is always mocked."""

import asyncio
import json
import logging

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from shoji.app import create_app
from shoji.capture import Capture, RequestRecord, log_sink, request_id_from
from shoji.config import PROVIDER_BASE_URLS, Settings

URL = f"{PROVIDER_BASE_URLS['groq']}/chat/completions"

# Synthetic marker strings: they must never appear in any record or log line.
SECRET_PROMPT = "synthetic-prompt-Ravi-Kumar-9876543210"
SECRET_REPLY = "synthetic-reply-ABCDE1234F"
PAYLOAD = {"model": "test-model", "messages": [{"role": "user", "content": SECRET_PROMPT}]}
COMPLETION = {"choices": [{"message": {"role": "assistant", "content": SECRET_REPLY}}]}

FIELDS = {
    "request_id",
    "provider",
    "started_at",
    "model",
    "stream",
    "status",
    "upstream_latency_ms",
    "total_latency_ms",
    "error_type",
}


@pytest.fixture
def records():
    return []


@pytest.fixture
def client(records):
    settings = Settings(_env_file=None, groq_api_key="k", shoji_retry_backoff=0)
    capture = Capture(sinks=[records.append, log_sink])
    with TestClient(create_app(settings, capture)) as c:
        yield c


@respx.mock
def test_one_record_per_request_with_all_fields(client, records):
    respx.post(URL).mock(return_value=httpx.Response(200, json=COMPLETION))

    resp = client.post("/v1/chat/completions", json=PAYLOAD)

    assert len(records) == 1
    record = records[0].to_dict()
    assert set(record) == FIELDS
    assert record["request_id"] == resp.headers["X-Request-ID"]
    assert record["provider"] == "groq"
    assert record["model"] == "test-model"
    assert record["stream"] is False
    assert record["status"] == 200
    assert record["error_type"] is None
    assert 0 <= record["upstream_latency_ms"] <= record["total_latency_ms"]


@respx.mock
def test_content_never_reaches_records_or_logs(client, records, caplog):
    respx.post(URL).mock(return_value=httpx.Response(200, json=COMPLETION))

    with caplog.at_level(logging.INFO, logger="shoji.requests"):
        client.post("/v1/chat/completions", json=PAYLOAD)

    dumped = json.dumps([r.to_dict() for r in records])
    for secret in (SECRET_PROMPT, SECRET_REPLY):
        assert secret not in dumped
        assert secret not in caplog.text


@respx.mock
def test_log_line_is_one_json_object(client, caplog):
    respx.post(URL).mock(return_value=httpx.Response(200, json=COMPLETION))

    with caplog.at_level(logging.INFO, logger="shoji.requests"):
        client.post("/v1/chat/completions", json=PAYLOAD)

    lines = [r.getMessage() for r in caplog.records if r.name == "shoji.requests"]
    assert len(lines) == 1
    assert set(json.loads(lines[0])) == FIELDS


@respx.mock
def test_stream_record_finishes_when_stream_ends(client, records):
    respx.post(URL).mock(
        return_value=httpx.Response(
            200,
            content=b"data: {}\n\ndata: [DONE]\n\n",
            headers={"content-type": "text/event-stream"},
        )
    )
    with client.stream("POST", "/v1/chat/completions", json={**PAYLOAD, "stream": True}) as resp:
        rid = resp.headers["X-Request-ID"]
        b"".join(resp.iter_bytes())

    assert len(records) == 1
    record = records[0]
    assert record.request_id == rid
    assert record.stream is True
    assert record.status == 200
    assert record.error_type is None
    assert record.total_latency_ms >= record.upstream_latency_ms


@respx.mock
def test_mid_stream_failure_is_recorded(client, records):
    async def dropping():
        yield b"data: {}\n\n"
        raise httpx.ReadError("reset")

    respx.post(URL).mock(
        return_value=httpx.Response(
            200, content=dropping(), headers={"content-type": "text/event-stream"}
        )
    )
    with client.stream("POST", "/v1/chat/completions", json={**PAYLOAD, "stream": True}) as resp:
        b"".join(resp.iter_bytes())

    assert records[0].error_type == "upstream_error_mid_stream"


@pytest.mark.parametrize(
    ("mock", "status", "error_type"),
    [
        (httpx.Response(429, json={"error": {"message": "slow down"}}), 429, "upstream_error"),
        (httpx.ReadTimeout("slow"), 504, "upstream_timeout"),
        (httpx.ConnectError("refused"), 502, "upstream_unavailable"),
    ],
)
@respx.mock
def test_failures_are_recorded(client, records, mock, status, error_type):
    if isinstance(mock, Exception):
        respx.post(URL).mock(side_effect=mock)
    else:
        respx.post(URL).mock(return_value=mock)

    resp = client.post("/v1/chat/completions", json=PAYLOAD)

    assert resp.status_code == status
    assert "X-Request-ID" in resp.headers
    assert (records[0].status, records[0].error_type) == (status, error_type)


def test_invalid_request_is_recorded(client, records):
    resp = client.post(
        "/v1/chat/completions", content=b"nope", headers={"Content-Type": "application/json"}
    )
    assert resp.status_code == 400
    assert "X-Request-ID" in resp.headers
    assert (records[0].status, records[0].error_type, records[0].model) == (
        400,
        "invalid_request",
        None,
    )


@respx.mock
def test_safe_client_request_id_is_reused(client, records):
    respx.post(URL).mock(return_value=httpx.Response(200, json=COMPLETION))
    resp = client.post(
        "/v1/chat/completions", json=PAYLOAD, headers={"X-Request-ID": "trace-123.abc"}
    )
    assert resp.headers["X-Request-ID"] == "trace-123.abc"
    assert records[0].request_id == "trace-123.abc"


@pytest.mark.parametrize("value", [None, "", "has space", "x" * 129, "inject\nline"])
def test_unsafe_or_missing_request_id_is_replaced(value):
    rid = request_id_from(value)
    assert rid != value
    assert len(rid) == 32


def test_failing_sink_does_not_break_others():
    seen = []

    def broken(record):
        raise RuntimeError("sink down")

    Capture(sinks=[broken, seen.append]).finish(RequestRecord("r1", "groq"), 200)
    assert len(seen) == 1


@respx.mock
async def test_client_disconnect_mid_stream_is_recorded(records):
    """Drive the ASGI app directly so the client can hang up after two events."""

    async def endless():
        while True:
            yield b"data: {}\n\n"
            await asyncio.sleep(0.005)

    respx.post(URL).mock(
        return_value=httpx.Response(
            200, content=endless(), headers={"content-type": "text/event-stream"}
        )
    )
    app = create_app(Settings(_env_file=None, groq_api_key="k"), Capture([records.append]))
    sent = []
    pending = [
        {
            "type": "http.request",
            "body": json.dumps({**PAYLOAD, "stream": True}).encode(),
            "more_body": False,
        }
    ]

    async def receive():
        if pending:
            return pending.pop(0)
        while sum(m["type"] == "http.response.body" for m in sent) < 2:
            await asyncio.sleep(0.005)
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "path": "/v1/chat/completions",
        "raw_path": b"/v1/chat/completions",
        "query_string": b"",
        "headers": [(b"content-type", b"application/json")],
        "scheme": "http",
        "server": ("test", 80),
        "client": ("client", 1),
        "root_path": "",
    }
    async with app.router.lifespan_context(app):
        await asyncio.wait_for(app(scope, receive, send), timeout=5)

    assert len(records) == 1
    assert records[0].error_type == "client_disconnected"
