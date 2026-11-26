"""Replace detected spans with placeholders, and put the original values back."""

from collections.abc import Iterable

from shoji.detect.entity import Entity
from shoji.redact.mapping import PLACEHOLDER, Mapping


def redact(text: str, entities: Iterable[Entity], mapping: Mapping) -> str:
    """Replace each entity's span in ``text`` with its placeholder.

    ``entities`` must not overlap (``detect`` already resolves overlaps). Placeholders are
    issued in order of position, after reserving any placeholder-shaped tokens already in
    ``text``. When redacting several texts that share one mapping, reserve all of them first
    (``redact_messages`` does this).
    """
    spans = sorted(entities, key=lambda e: e.start)
    for a, b in zip(spans, spans[1:], strict=False):
        if b.start < a.end:
            raise ValueError(f"overlapping entities [{a.start}, {a.end}) and [{b.start}, {b.end})")
    mapping.reserve(text)
    out: list[str] = []
    pos = 0
    for e in spans:
        if text[e.start : e.end] != e.text:
            raise ValueError(f"entity [{e.start}, {e.end}) does not match the text")
        out.append(text[pos : e.start])
        out.append(mapping.placeholder_for(e.type, e.text))
        pos = e.end
    out.append(text[pos:])
    return "".join(out)


def restore(text: str, mapping: Mapping) -> str:
    """Replace every placeholder issued by ``mapping`` with its original value.

    Only exact tokens are restored. Placeholders the mapping never issued (including ones a
    user typed) are left as they are. One pass, so a restored value is never re-scanned.
    """

    def swap(m):
        original = mapping.original(m.group(0))
        return m.group(0) if original is None else original

    return PLACEHOLDER.sub(swap, text)
