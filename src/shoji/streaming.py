"""Server-sent events (SSE) relay.

Upstream bytes arrive in arbitrary network chunks that can cut an event in half. We re-split
them into whole events so each event's text can be transformed safely: ``SseRestorer`` swaps
placeholders back to the original values, including ones cut across events.
"""

import json
import re
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable

import httpx

from shoji.redact import Mapping, StreamRestorer

# An SSE event ends with a blank line; the spec allows \n, \r\n or \r line endings.
_EVENT_END = re.compile(rb"\r\n\r\n|\n\n|\r\r")

MID_STREAM_ERROR = (
    b"data: "
    + json.dumps(
        {
            "error": {
                "message": "Upstream provider connection failed mid-stream.",
                "type": "upstream_error",
                "code": None,
            }
        }
    ).encode()
    + b"\n\n"
)


async def sse_events(chunks: AsyncIterable[bytes]) -> AsyncIterator[bytes]:
    """Yield each complete SSE event (including its terminating blank line) as soon as it ends."""
    buffer = b""
    async for chunk in chunks:
        buffer += chunk
        start = 0
        for match in _EVENT_END.finditer(buffer):
            yield buffer[start : match.end()]
            start = match.end()
        buffer = buffer[start:]
    if buffer:
        # Upstream closed without a final blank line; pass on whatever is left.
        yield buffer


class SseRestorer:
    """Restores placeholders in ``chat.completion.chunk`` events, one restorer per choice.

    Only ``choices[i].delta.content`` is rewritten. Events that are not JSON chunks (comments,
    ``[DONE]``, other providers' extras) and events whose text did not change are passed on
    byte for byte. Held-back text is released on that choice's ``finish_reason``, before
    ``[DONE]``, and by ``flush_events`` at the end of the stream or before an error.
    """

    def __init__(self, mapping: Mapping) -> None:
        self.mapping = mapping
        self._choices: dict[int, StreamRestorer] = {}
        self._last: dict = {}  # id/model/created of the last chunk, for synthetic chunks

    def _restorer(self, index: int) -> StreamRestorer:
        if index not in self._choices:
            self._choices[index] = StreamRestorer(self.mapping)
        return self._choices[index]

    def event(self, event: bytes) -> list[bytes]:
        try:
            lines = event.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            return [event]
        data = [ln[5:].removeprefix(" ") for ln in lines if ln.startswith("data:")]
        if not data:
            return [event]
        payload = "\n".join(data)
        if payload.strip() == "[DONE]":
            return [*self.flush_events(), event]
        try:
            chunk = json.loads(payload)
        except ValueError:
            return [event]
        if not isinstance(chunk, dict) or not isinstance(chunk.get("choices"), list):
            return [event]
        self._last = {k: chunk[k] for k in ("id", "object", "created", "model") if k in chunk}

        changed = False
        for choice in chunk["choices"]:
            if not isinstance(choice, dict) or not isinstance(choice.get("index", 0), int):
                continue
            restorer = self._restorer(choice.get("index", 0))
            delta = choice.get("delta")
            content = delta.get("content") if isinstance(delta, dict) else None
            text = restorer.feed(content) if isinstance(content, str) else ""
            if choice.get("finish_reason") is not None:
                text += restorer.flush()
            if text != (content if isinstance(content, str) else ""):
                if not isinstance(delta, dict):
                    delta = choice["delta"] = {}
                delta["content"] = text
                changed = True
        if not changed:
            return [event]
        other = [ln for ln in lines if ln and not ln.startswith("data:")]
        return [_encode_event(other, chunk)]

    def flush_events(self) -> list[bytes]:
        """One synthetic chunk carrying all held-back text, or nothing if none is held."""
        choices = []
        for index, restorer in sorted(self._choices.items()):
            held = restorer.flush()
            if held:
                choices.append({"index": index, "delta": {"content": held}, "finish_reason": None})
        if not choices:
            return []
        chunk = {"object": "chat.completion.chunk", **self._last, "choices": choices}
        return [_encode_event([], chunk)]


def _encode_event(other_lines: list[str], chunk: dict) -> bytes:
    data = "data: " + json.dumps(chunk, ensure_ascii=False, separators=(",", ":"))
    return ("\n".join([*other_lines, data]) + "\n\n").encode("utf-8")


async def relay(
    chunks: AsyncIterable[bytes],
    close: Callable[[], Awaitable[None]],
    restorer: SseRestorer | None = None,
) -> AsyncIterator[bytes]:
    """Relay events to the client; always close the upstream, including on client disconnect.

    With a ``restorer``, placeholders in the streamed text are swapped back to the original
    values on the way through.

    If the upstream fails mid-stream, the HTTP status has already been sent, so the failure is
    reported as a final SSE error event (the shape OpenAI uses) instead of a silent cut-off.
    """
    try:
        async for event in sse_events(chunks):
            for out in restorer.event(event) if restorer else [event]:
                yield out
        if restorer:
            for out in restorer.flush_events():
                yield out
    except httpx.TransportError:
        if restorer:
            for out in restorer.flush_events():
                yield out
        yield MID_STREAM_ERROR
    finally:
        await close()
