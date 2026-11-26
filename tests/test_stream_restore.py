"""Restoring placeholders in streamed replies, including placeholders cut across chunks."""

import json
from itertools import combinations

import httpx
import pytest

from shoji.redact import Mapping, StreamRestorer, restore
from shoji.streaming import MID_STREAM_ERROR, SseRestorer, relay


@pytest.fixture
def mapping():
    m = Mapping()
    m.placeholder_for("PHONE", "+91 98765 43210")  # <PHONE_1>
    m.placeholder_for("PAN", "ABCPD1234F")  # <PAN_1>
    m.placeholder_for("PERSON", "राहुल शर्मा")  # <PERSON_1>
    m.placeholder_for("CARD_NUMBER", "4111 1111 1111 1111")  # <CARD_NUMBER_1>
    return m


REPLY = "Dear <PERSON_1>, call <PHONE_1> or pay <CARD_NUMBER_1>; PAN <PAN_1> < 5 <PHONE_2> ✓"


# --- StreamRestorer -----------------------------------------------------------------------------


def run(restorer, pieces):
    return "".join(restorer.feed(p) for p in pieces) + restorer.flush()


def test_split_placeholder(mapping):
    r = StreamRestorer(mapping)
    assert r.feed("call <PHO") == "call "
    assert r.held == "<PHO"
    assert r.feed("NE_1> today") == "+91 98765 43210 today"
    assert r.held == ""


def test_ordinary_text_not_delayed(mapping):
    r = StreamRestorer(mapping)
    assert r.feed("x < 5 and a<b") == "x < 5 and a<b"
    assert r.feed("ends with <") == "ends with "  # could still become a placeholder
    assert r.feed(" 3") == "< 3"


def test_only_issued_placeholders_are_held(mapping):
    r = StreamRestorer(mapping)
    assert r.feed("<EMAIL_") == "<EMAIL_"  # no EMAIL placeholder was issued
    assert r.feed("<PHONE_2") == "<PHONE_2"  # only <PHONE_1> exists
    assert r.feed("<phone") == "<phone"


def test_nothing_held_with_empty_mapping():
    r = StreamRestorer(Mapping())
    assert r.feed("<PHO") == "<PHO"


def test_held_text_is_bounded(mapping):
    longest = max(len(p) for p, _ in mapping.items())
    r = StreamRestorer(mapping)
    for piece in "<CARD_NUMBER_1 and then it never closes":
        r.feed(piece)
        assert len(r.held) < longest


def test_unclosed_placeholder_released_on_flush(mapping):
    r = StreamRestorer(mapping)
    assert r.feed("cut off <PAN_") == "cut off "
    assert r.flush() == "<PAN_"
    assert r.flush() == ""


def test_restored_value_containing_angle_bracket(mapping):
    m = Mapping()
    m.placeholder_for("PERSON", "a <PHO")
    m.placeholder_for("PHONE", "9876543210")
    r = StreamRestorer(m)
    assert r.feed("<PERSON_1>") == "a <PHO"
    assert r.held == ""


@pytest.mark.parametrize("cuts", [1, 2])
def test_every_split_matches_non_streaming(mapping, cuts):
    expected = restore(REPLY, mapping)
    for points in combinations(range(1, len(REPLY)), cuts):
        bounds = [0, *points, len(REPLY)]
        pieces = [REPLY[a:b] for a, b in zip(bounds, bounds[1:], strict=False)]
        assert run(StreamRestorer(mapping), pieces) == expected, pieces


# --- SSE ----------------------------------------------------------------------------------------


def chunk_event(content=None, index=0, finish=None, role=None):
    delta = {}
    if role:
        delta["role"] = role
    if content is not None:
        delta["content"] = content
    chunk = {
        "id": "chatcmpl-1",
        "object": "chat.completion.chunk",
        "created": 1,
        "model": "m",
        "choices": [{"index": index, "delta": delta, "finish_reason": finish}],
    }
    return f"data: {json.dumps(chunk)}\n\n".encode()


DONE = b"data: [DONE]\n\n"


async def from_list(items):
    for item in items:
        yield item


async def noop():
    pass


async def relayed(events, mapping):
    return [e async for e in relay(from_list(events), noop, SseRestorer(mapping))]


def content_of(events, index=0):
    text = []
    for e in events:
        payload = e.decode().removeprefix("data: ").strip()
        if payload == "[DONE]" or payload.startswith('{"error"'):
            continue
        for c in json.loads(payload)["choices"]:
            if c["index"] == index:
                text.append(c["delta"].get("content") or "")
    return "".join(text)


@pytest.mark.parametrize("cuts", [1, 2])
async def test_sse_every_split_matches_non_streaming(mapping, cuts):
    expected = restore(REPLY, mapping)
    for points in combinations(range(1, len(REPLY)), cuts):
        bounds = [0, *points, len(REPLY)]
        events = [chunk_event(role="assistant")]
        events += [chunk_event(REPLY[a:b]) for a, b in zip(bounds, bounds[1:], strict=False)]
        events += [chunk_event(finish="stop"), DONE]
        out = await relayed(events, mapping)
        assert content_of(out) == expected
        assert out[-1] == DONE


async def test_unchanged_events_pass_byte_for_byte(mapping):
    events = [
        b": keep-alive comment\n\n",
        chunk_event(role="assistant"),
        chunk_event("no placeholders here"),
        b'event: ping\ndata: {"type": "ping"}\n\n',
        b"data: not json\n\n",
        chunk_event(finish="stop"),
        DONE,
    ]
    assert await relayed(events, mapping) == events


async def test_rewritten_event_keeps_other_fields(mapping):
    (out, done) = await relayed([chunk_event("call <PHONE_1>"), DONE], mapping)
    chunk = json.loads(out.decode().removeprefix("data: "))
    assert chunk["id"] == "chatcmpl-1" and chunk["model"] == "m"
    assert chunk["choices"][0]["delta"]["content"] == "call +91 98765 43210"
    assert done == DONE


async def test_held_text_released_on_finish_reason(mapping):
    out = await relayed([chunk_event("bye <PAN_"), chunk_event(finish="stop"), DONE], mapping)
    assert content_of(out[:1]) == "bye "
    assert content_of(out[1:2]) == "<PAN_"
    assert json.loads(out[1].decode()[6:])["choices"][0]["finish_reason"] == "stop"


async def test_held_text_released_before_done(mapping):
    out = await relayed([chunk_event("bye <PAN_"), DONE], mapping)
    assert content_of(out) == "bye <PAN_" and out[-1] == DONE


async def test_held_text_released_at_end_without_done(mapping):
    out = await relayed([chunk_event("bye <PAN_")], mapping)
    assert content_of(out) == "bye <PAN_"
    assert json.loads(out[-1].decode()[6:])["id"] == "chatcmpl-1"


async def test_choices_restored_independently(mapping):
    events = [
        chunk_event("A <PHO", index=0),
        chunk_event("B <PA", index=1),
        chunk_event("NE_1>", index=0),
        chunk_event("N_1>", index=1),
        DONE,
    ]
    out = await relayed(events, mapping)
    assert content_of(out, 0) == "A +91 98765 43210"
    assert content_of(out, 1) == "B ABCPD1234F"


async def test_tool_calls_and_role_untouched(mapping):
    tool = {
        "id": "c",
        "object": "chat.completion.chunk",
        "choices": [
            {
                "index": 0,
                "delta": {"tool_calls": [{"function": {"arguments": "<PHONE_1>"}}]},
                "finish_reason": None,
            }
        ],
    }
    event = f"data: {json.dumps(tool)}\n\n".encode()
    assert await relayed([event, DONE], mapping) == [event, DONE]


async def test_multibyte_content(mapping):
    out = await relayed([chunk_event("नमस्ते <PERSON_"), chunk_event("1> 🙏"), DONE], mapping)
    assert content_of(out) == "नमस्ते राहुल शर्मा 🙏"


async def test_mid_stream_error_flushes_held_text_first(mapping):
    async def dropping():
        yield chunk_event("partial <PHO")
        raise httpx.ReadError("connection reset")

    out = [e async for e in relay(dropping(), noop, SseRestorer(mapping))]
    assert out[-1] is MID_STREAM_ERROR
    assert content_of(out[:-1]) == "partial <PHO"


async def test_relay_without_restorer_unchanged(mapping):
    events = [chunk_event("<PHONE_1>"), DONE]
    assert [e async for e in relay(from_list(events), noop)] == events
