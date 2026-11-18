"""SSE event splitting and upstream cleanup."""

import asyncio

import pytest

from shoji.streaming import relay, sse_events


async def from_list(chunks):
    for chunk in chunks:
        yield chunk


async def collect(agen):
    return [item async for item in agen]


@pytest.mark.parametrize(
    "chunks",
    [
        [b"data: a\n\ndata: b\n\n"],  # two events in one chunk
        [b"da", b"ta: a\n", b"\ndata: b\n\n"],  # split mid-event and mid-terminator
        [b"data: a\n\n", b"data: b\n\n"],  # one event per chunk
    ],
)
async def test_events_are_rebuilt_regardless_of_chunking(chunks):
    assert await collect(sse_events(from_list(chunks))) == [b"data: a\n\n", b"data: b\n\n"]


async def test_crlf_line_endings():
    events = await collect(sse_events(from_list([b"data: a\r\n\r\ndata: b\r\n\r\n"])))
    assert events == [b"data: a\r\n\r\n", b"data: b\r\n\r\n"]


async def test_trailing_partial_event_is_flushed():
    events = await collect(sse_events(from_list([b"data: a\n\ndata: tail"])))
    assert events == [b"data: a\n\n", b"data: tail"]


async def test_event_is_yielded_before_upstream_sends_more():
    """No buffering of the whole response: event 1 must reach us while upstream is still open."""
    second_chunk_sent = asyncio.Event()

    async def slow_upstream():
        yield b"data: first\n\n"
        second_chunk_sent.set()
        yield b"data: second\n\n"

    events = sse_events(slow_upstream())
    first = await anext(events)
    assert first == b"data: first\n\n"
    assert not second_chunk_sent.is_set()
    await events.aclose()


async def test_upstream_closed_when_client_disconnects():
    closed = False

    async def close():
        nonlocal closed
        closed = True

    async def endless():
        while True:
            yield b"data: x\n\n"

    stream = relay(endless(), close)
    await anext(stream)
    await stream.aclose()  # what Starlette does when the client goes away
    assert closed


async def test_upstream_closed_after_normal_completion():
    closed = False

    async def close():
        nonlocal closed
        closed = True

    await collect(relay(from_list([b"data: [DONE]\n\n"]), close))
    assert closed
