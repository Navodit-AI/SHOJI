"""Server-sent events (SSE) relay.

Upstream bytes arrive in arbitrary network chunks that can cut an event in half. We re-split
them into whole events so later stages (placeholder restoration in Stage 3) can transform
each event's text safely. In Stage 1 events are relayed unchanged.
"""

import re
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable

# An SSE event ends with a blank line; the spec allows \n, \r\n or \r line endings.
_EVENT_END = re.compile(rb"\r\n\r\n|\n\n|\r\r")


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


async def relay(
    chunks: AsyncIterable[bytes], close: Callable[[], Awaitable[None]]
) -> AsyncIterator[bytes]:
    """Relay events to the client; always close the upstream, including on client disconnect."""
    try:
        async for event in sse_events(chunks):
            yield event
    finally:
        await close()
