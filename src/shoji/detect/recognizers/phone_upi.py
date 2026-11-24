"""Indian mobile numbers and UPI IDs.

Phones: a 10-digit mobile starting 6-9, written plain (``9876543210``), as 5-5
(``98765 43210``, ``98765-43210``) or 3-3-4 (``987 654 3210``), optionally prefixed by
``+91``/``91`` (with or without a space or hyphen) or a trunk ``0``. The span includes the
prefix. Landlines (``022 2345 6789``) are out of scope for now.

UPI IDs: ``user@psp`` where ``psp`` is a known payment-provider handle from
``data/upi_handles.txt``. Anything with a dot after the ``@`` (``name@gmail.com``) is an
email, never a UPI ID. A UPI ID whose user part is a phone number (``9876543210@ybl``) also
yields a phone candidate; overlap resolution keeps the longer UPI span.
"""

import re
from collections.abc import Iterator

from shoji.detect.entity import Entity, EntityType
from shoji.detect.formats import upi_psp_handles
from shoji.detect.recognizer import Recognizer

_PHONE = re.compile(
    r"(?<![0-9A-Za-z+])"  # not glued to a word or a longer number
    r"(?<![0-9][ -])"  # not the tail of a grouped digit sequence
    r"(?P<value>"
    r"(?P<prefix>\+91[ -]?|91[ -]?|0)?"
    r"(?:[6-9][0-9]{9}"  # 9876543210
    r"|[6-9][0-9]{4}(?P<s1>[ -])[0-9]{5}"  # 98765 43210
    r"|[6-9][0-9]{2}(?P<s2>[ -])[0-9]{3}(?P=s2)[0-9]{4})"  # 987 654 3210
    r")"
    r"(?![0-9A-Za-z])"
    r"(?![ -][0-9])"  # not the head of a grouped digit sequence
)

_UPI = re.compile(
    r"(?<![A-Za-z0-9._@-])"
    r"(?P<value>[A-Za-z0-9][A-Za-z0-9._-]{1,63}@(?P<psp>[A-Za-z][A-Za-z0-9]{1,31}))"
    r"(?![A-Za-z0-9_@-])"
    r"(?!\.[A-Za-z0-9])"  # "name@upi.com" is a domain, not a UPI handle
)


class IndianPhoneRecognizer(Recognizer):
    name = "phone_in"
    entity_types = frozenset({EntityType.PHONE})

    PLUS91_SCORE = 0.9  # "+91" makes it unambiguous
    PREFIX_SCORE = 0.75  # "91" or "0": also how some account numbers start
    PLAIN_SCORE = 0.7  # any 10-digit number starting 6-9

    def analyze(self, text: str) -> Iterator[Entity]:
        for m in _PHONE.finditer(text):
            prefix = m.group("prefix") or ""
            if prefix.startswith("+"):
                score = self.PLUS91_SCORE
            elif prefix:
                score = self.PREFIX_SCORE
            else:
                score = self.PLAIN_SCORE
            start, end = m.span("value")
            yield Entity(EntityType.PHONE, start, end, m.group("value"), score, self.name)


class UpiRecognizer(Recognizer):
    name = "upi"
    entity_types = frozenset({EntityType.UPI_ID})

    SCORE = 0.9

    def __init__(self, handles: frozenset[str] | None = None) -> None:
        self.handles = upi_psp_handles() if handles is None else handles

    def analyze(self, text: str) -> Iterator[Entity]:
        for m in _UPI.finditer(text):
            if m.group("psp").lower() not in self.handles:
                continue
            start, end = m.span("value")
            yield Entity(EntityType.UPI_ID, start, end, m.group("value"), self.SCORE, self.name)
