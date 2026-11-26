"""Restore placeholders in text that arrives piece by piece.

A streamed reply can cut a placeholder in two (``"call <PHO"`` then ``"NE_1> today"``). The
restorer releases text as soon as it cannot be the start of a placeholder and holds back only
a tail that is still a prefix of one this mapping issued. That tail is never longer than the
longest issued placeholder, and nothing is held when the mapping is empty.
"""

from shoji.redact.mapping import Mapping
from shoji.redact.text import restore


class StreamRestorer:
    def __init__(self, mapping: Mapping) -> None:
        self.mapping = mapping
        self._held = ""

    @property
    def held(self) -> str:
        return self._held

    def _could_continue(self, tail: str) -> bool:
        # Placeholders contain exactly one "<", so only the tail from the last "<" can matter.
        return any(p.startswith(tail) and p != tail for p, _ in self.mapping.items())

    def feed(self, text: str) -> str:
        """Add the next piece; return the restored text that is safe to release now."""
        buffer = self._held + text
        i = buffer.rfind("<")
        if i != -1 and self._could_continue(buffer[i:]):
            self._held = buffer[i:]
            buffer = buffer[:i]
        else:
            self._held = ""
        return restore(buffer, self.mapping)

    def flush(self) -> str:
        """End of stream: release whatever is held (it never became a placeholder)."""
        held, self._held = self._held, ""
        return held
