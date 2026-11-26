"""Redaction wired into /v1/chat/completions. Upstream mocked; synthetic data only."""

import json

import httpx
import pytest
import respx
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from shoji.app import CONVERSATION_HEADER, create_app
from shoji.config import PROVIDER_BASE_URLS, Settings

URL = f"{PROVIDER_BASE_URLS['groq']}/chat/completions"

PAN, PHONE, AADHAAR = "ABCPD1234F", "+91 98765 43210", "2345 6789 0124"
UPI, CARD, GSTIN = "priya@okaxis", "4111 1111 1111 1111", "27ABCPD1234F1ZC"
PROMPT = (
    f"Remind Rahul (PAN {PAN}, Aadhaar {AADHAAR}) to pay via {UPI} or card {CARD}. Call {PHONE}."
)
VALUES = [PAN, PHONE, AADHAAR, UPI, CARD]


def settings(**overrides):
    values = {"groq_api_key": "k", "shoji_retry_backoff": 0, **overrides}
    return Settings(_env_file=None, **values)


@pytest.fixture
def client():
    with TestClient(create_app(settings())) as c:
        yield c


def completion(content):
    return {
        "id": "chatcmpl-1",
        "object": "chat.completion",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }


def chat(content, **extra):
    return {"model": "m", "messages": [{"role": "user", "content": content}], **extra}


def sent_body(route, call=-1):
    return json.loads(route.calls[call].request.content)


def sse(*pieces):
    events = []
    for p in pieces:
        choice = {"index": 0, "delta": {"content": p}, "finish_reason": None}
        chunk = {"id": "c", "object": "chat.completion.chunk", "choices": [choice]}
        events.append(f"data: {json.dumps(chunk)}\n\n")
    events.append("data: [DONE]\n\n")
    return "".join(events).encode()


def streamed_text(resp):
    text = []
    for line in resp.text.splitlines():
        if line.startswith("data: {"):
            for c in json.loads(line[6:])["choices"]:
                text.append(c["delta"].get("content") or "")
    return "".join(text)


@respx.mock
def test_upstream_sees_placeholders_client_gets_values(client):
    reply = "Sure. I'll message <PHONE_1> and mention PAN <PAN_1>; card <CARD_NUMBER_1>."
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=completion(reply)))

    resp = client.post("/v1/chat/completions", json=chat(PROMPT))

    sent = json.dumps(sent_body(route))
    for value in VALUES:
        assert value not in sent
    assert sent_body(route)["messages"][0]["content"] == (
        "Remind Rahul (PAN <PAN_1>, Aadhaar <AADHAAR_1>) to pay via <UPI_ID_1> or card "
        "<CARD_NUMBER_1>. Call <PHONE_1>."
    )
    assert resp.status_code == 200
    assert resp.json()["choices"][0]["message"]["content"] == (
        f"Sure. I'll message {PHONE} and mention PAN {PAN}; card {CARD}."
    )
    assert resp.json()["id"] == "chatcmpl-1"


@respx.mock
def test_streaming_restores_split_placeholders(client):
    upstream = sse("Calling <PHO", "NE_1> now, PAN <", "PAN_1", ">.")
    route = respx.post(URL).mock(
        return_value=httpx.Response(
            200, content=upstream, headers={"content-type": "text/event-stream"}
        )
    )

    resp = client.post("/v1/chat/completions", json=chat(PROMPT, stream=True))

    assert all(v not in route.calls.last.request.content.decode() for v in VALUES)
    assert streamed_text(resp) == f"Calling {PHONE} now, PAN {PAN}."
    assert resp.text.endswith("data: [DONE]\n\n")


@respx.mock
def test_reply_without_placeholders_passes_byte_for_byte(client):
    body = b'{"choices": [{"message": {"content": "No IDs here."}}], "x":  1}'
    respx.post(URL).mock(return_value=httpx.Response(200, content=body))
    resp = client.post("/v1/chat/completions", json=chat(f"PAN {PAN}"))
    assert resp.content == body


@respx.mock
def test_no_personal_data_forwards_body_unchanged(client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=completion("Hi")))
    payload = chat("Hello there", temperature=0.2)
    client.post("/v1/chat/completions", json=payload)
    assert sent_body(route) == payload


@respx.mock
def test_all_roles_and_text_parts_are_redacted(client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=completion("ok")))
    payload = {
        "model": "m",
        "messages": [
            {"role": "system", "content": f"The customer's UPI is {UPI}."},
            {"role": "user", "content": [{"type": "text", "text": f"PAN {PAN}"}]},
            {"role": "assistant", "content": f"Got PAN {PAN}."},
            {"role": "user", "content": f"And phone {PHONE}"},
        ],
    }
    client.post("/v1/chat/completions", json=payload)
    messages = sent_body(route)["messages"]
    assert messages[0]["content"] == "The customer's UPI is <UPI_ID_1>."
    assert messages[1]["content"] == [{"type": "text", "text": "PAN <PAN_1>"}]
    assert messages[2]["content"] == "Got PAN <PAN_1>."
    assert messages[3]["content"] == "And phone <PHONE_1>"


@respx.mock
def test_redaction_off_is_pass_through():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=completion("<PAN_1>")))
    with TestClient(create_app(settings(shoji_redact=False))) as client:
        resp = client.post("/v1/chat/completions", json=chat(PROMPT))
    assert sent_body(route)["messages"][0]["content"] == PROMPT
    assert resp.json()["choices"][0]["message"]["content"] == "<PAN_1>"


@respx.mock
def test_min_score_threshold():
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=completion("ok")))
    with TestClient(create_app(settings(shoji_min_score=0.92))) as client:
        client.post("/v1/chat/completions", json=chat(f"GSTIN {GSTIN}, PAN {PAN}"))
    # GSTIN scores 0.95, a standalone PAN 0.85.
    assert sent_body(route)["messages"][0]["content"] == f"GSTIN <GSTIN_1>, PAN {PAN}"


@respx.mock
def test_weak_aadhaar_reading_of_phone_ignored_by_default(client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=completion("ok")))
    client.post("/v1/chat/completions", json=chat("call 919876543210"))
    assert sent_body(route)["messages"][0]["content"] == "call <PHONE_1>"


@respx.mock
def test_upstream_error_passes_through_unchanged(client):
    error = {"error": {"message": "rate limited", "type": "rate_limit", "code": None}}
    respx.post(URL).mock(return_value=httpx.Response(429, json=error))
    resp = client.post("/v1/chat/completions", json=chat(PROMPT))
    assert resp.status_code == 429 and resp.json() == error


@respx.mock
def test_non_list_messages_forwarded_as_is(client):
    route = respx.post(URL).mock(return_value=httpx.Response(400, json={"error": {}}))
    client.post("/v1/chat/completions", json={"model": "m", "messages": f"PAN {PAN}"})
    assert sent_body(route)["messages"] == f"PAN {PAN}"


# --- Vault ---------------------------------------------------------------------------------------


@pytest.fixture
def vault_client(tmp_path):
    s = settings(shoji_vault_key=Fernet.generate_key().decode(),
                 shoji_vault_path=str(tmp_path / "v.db"))  # fmt: skip
    with TestClient(create_app(s)) as c:
        yield c


@respx.mock
def test_conversation_header_keeps_placeholders_when_history_is_trimmed(vault_client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=completion("ok")))
    headers = {CONVERSATION_HEADER: "conv-42"}
    vault_client.post(
        "/v1/chat/completions", json=chat(f"PAN {PAN}, phone {PHONE}"), headers=headers
    )
    # Second turn: the client trimmed the history; the phone still gets its old placeholder.
    vault_client.post("/v1/chat/completions", json=chat("call 98765 43210"), headers=headers)
    assert sent_body(route, 1)["messages"][0]["content"] == "call <PHONE_1>"
    # Without the header each request starts from scratch.
    vault_client.post("/v1/chat/completions", json=chat(f"UPI {UPI}, phone {PHONE}"))
    assert sent_body(route, 2)["messages"][0]["content"] == "UPI <UPI_ID_1>, phone <PHONE_1>"


@respx.mock
def test_vault_restores_placeholders_from_an_earlier_turn(vault_client):
    respx.post(URL).mock(
        side_effect=[
            httpx.Response(200, json=completion("ok")),
            httpx.Response(200, json=completion("Your PAN is <PAN_1>.")),
        ]
    )
    headers = {CONVERSATION_HEADER: "c"}
    vault_client.post("/v1/chat/completions", json=chat(f"PAN {PAN}"), headers=headers)
    resp = vault_client.post("/v1/chat/completions", json=chat("what was my PAN?"), headers=headers)
    assert resp.json()["choices"][0]["message"]["content"] == f"Your PAN is {PAN}."


@respx.mock
def test_conversation_header_without_vault_is_ignored(client):
    route = respx.post(URL).mock(return_value=httpx.Response(200, json=completion("ok")))
    client.post("/v1/chat/completions", json=chat(f"PAN {PAN}"), headers={CONVERSATION_HEADER: "c"})
    assert sent_body(route)["messages"][0]["content"] == "PAN <PAN_1>"
