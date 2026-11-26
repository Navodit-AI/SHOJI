"""Placeholder allocation: which code name stands for which value.

Placeholders look like ``<PHONE_1>``: the entity type, an underscore, and a number counted
separately per type. The same value always gets the same placeholder, where "same" ignores
formatting (``98765 43210`` and ``+91-98765-43210`` are one phone number; see ``value_key``).
Numbers are handed out in order of first appearance, so redacting the same message history
twice gives the same placeholders. Chat clients resend the whole history on every turn, which
keeps placeholders stable across a conversation without storing anything.
"""

import ipaddress
import re
from collections.abc import Callable, Iterator

from shoji.detect.entity import EntityType

# Any token shaped like a placeholder, whether or not we issued it.
PLACEHOLDER = re.compile(r"<([A-Z][A-Z_]*)_([1-9][0-9]*)>")
_TYPE_NAME = re.compile(r"[A-Z][A-Z_]*")


def _digits(value: str) -> str:
    return "".join(c for c in value if c.isascii() and c.isdigit())


def _ip(value: str) -> str:
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        return value.lower()


# How each type decides that two spellings are the same value. Types not listed fall back to
# case-folding with whitespace collapsed (names, addresses).
_KEYS: dict[str, Callable[[str], str]] = {
    EntityType.AADHAAR: _digits,
    EntityType.CARD_NUMBER: _digits,
    EntityType.PHONE: lambda v: _digits(v)[-10:],  # drops +91 / 91 / 0 prefixes
    EntityType.PAN: str.upper,
    EntityType.GSTIN: str.upper,
    EntityType.IFSC: str.upper,
    EntityType.EMAIL: str.lower,
    EntityType.UPI_ID: str.lower,
    EntityType.IP_ADDRESS: _ip,
}


def value_key(entity_type: str, value: str) -> str:
    """The normalised form used to decide whether two detections are the same value."""
    key = _KEYS.get(entity_type)
    if key is not None:
        return key(value)
    return " ".join(value.casefold().split())


class Mapping:
    """Placeholders issued so far, in both directions.

    ``reserve`` must see every text before any placeholder is issued for it, so a user who
    literally types ``<PHONE_1>`` never has a real phone number restored into that spot: the
    real number gets ``<PHONE_2>`` instead, and the typed token stays as it was.
    """

    def __init__(self) -> None:
        self._by_key: dict[tuple[str, str], str] = {}
        self._originals: dict[str, str] = {}
        self._types: dict[str, str] = {}
        self._counters: dict[str, int] = {}
        self._reserved: set[str] = set()

    def reserve(self, text: str) -> None:
        """Never issue a placeholder that already appears literally in ``text``."""
        for m in PLACEHOLDER.finditer(text):
            if m.group(0) not in self._originals:
                self._reserved.add(m.group(0))

    def placeholder_for(self, entity_type: str, value: str) -> str:
        if not _TYPE_NAME.fullmatch(entity_type):
            raise ValueError(f"entity type {entity_type!r} cannot be used in a placeholder")
        key = (entity_type, value_key(entity_type, value))
        if key in self._by_key:
            return self._by_key[key]
        n = self._counters.get(entity_type, 0)
        while True:
            n += 1
            placeholder = f"<{entity_type}_{n}>"
            if placeholder not in self._reserved:
                break
        self._counters[entity_type] = n
        self._by_key[key] = placeholder
        self._originals[placeholder] = value  # restore uses the first spelling seen
        self._types[placeholder] = entity_type
        return placeholder

    def original(self, placeholder: str) -> str | None:
        return self._originals.get(placeholder)

    def type_of(self, placeholder: str) -> str | None:
        return self._types.get(placeholder)

    def __len__(self) -> int:
        return len(self._originals)

    def __contains__(self, placeholder: object) -> bool:
        return placeholder in self._originals

    def items(self) -> Iterator[tuple[str, str]]:
        """``(placeholder, original value)`` pairs in the order they were issued."""
        return iter(self._originals.items())

    def __repr__(self) -> str:
        # Never show values: a mapping can end up in a log or a traceback.
        return f"Mapping({len(self)} placeholders)"
