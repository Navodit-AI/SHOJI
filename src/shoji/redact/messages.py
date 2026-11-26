"""Redact the ``messages`` of an OpenAI chat-completions request."""

from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from shoji.detect import Entity, detect
from shoji.redact.mapping import Mapping
from shoji.redact.text import redact

Detector = Callable[[str], list[Entity]]


@dataclass
class RedactedMessages:
    messages: list[Any]
    mapping: Mapping
    # Detections per entity type (every occurrence, not unique values). Safe to log.
    counts: Counter[str] = field(default_factory=Counter)


def _texts(message: Any) -> Iterator[tuple[Any, Any]]:
    """``(container, key)`` for every redactable text in one message, in reading order.

    Covers string ``content`` and ``{"type": "text"}`` parts of list ``content``. Other part
    types (images, audio) and other fields (tool-call arguments, ``name``) are not touched.
    """
    if not isinstance(message, dict):
        return
    content = message.get("content")
    if isinstance(content, str):
        yield message, "content"
    elif isinstance(content, list):
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                if isinstance(part.get("text"), str):
                    yield part, "text"


def _copy(message: Any) -> Any:
    """Copy the parts of a message that redaction writes to; share everything else."""
    if not isinstance(message, dict):
        return message
    out = dict(message)
    if isinstance(out.get("content"), list):
        out["content"] = [dict(p) if isinstance(p, dict) else p for p in out["content"]]
    return out


def redact_messages(
    messages: list[Any], detector: Detector = detect, mapping: Mapping | None = None
) -> RedactedMessages:
    """Detect and redact every message (all roles, earlier assistant turns included).

    The input is not modified. Placeholders are numbered in reading order across the whole
    list, after every placeholder-shaped token already present has been reserved.
    """
    mapping = mapping if mapping is not None else Mapping()
    result = RedactedMessages([_copy(m) for m in messages], mapping)
    slots = [slot for m in result.messages for slot in _texts(m)]
    for container, key in slots:
        mapping.reserve(container[key])
    for container, key in slots:
        entities = detector(container[key])
        result.counts.update(e.type for e in entities)
        container[key] = redact(container[key], entities, mapping)
    return result
