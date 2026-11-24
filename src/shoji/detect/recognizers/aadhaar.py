"""Aadhaar numbers: 12 digits, first digit 2-9, last digit a Verhoeff checksum.

Accepted forms: ``234567890123``, ``2345 6789 0123``, ``2345-6789-0123`` (one separator kind).
Not matched: masked forms such as ``XXXX XXXX 1234`` (out of scope for now), numbers inside
longer digit runs or grouped digit sequences (e.g. a 16-digit card number), numbers glued to
letters (``ORD234567890123``) and numbers written with non-ASCII digits.
"""

import re
from collections.abc import Iterator

from shoji.detect.checksums import verhoeff_valid
from shoji.detect.entity import Entity, EntityType
from shoji.detect.recognizer import Recognizer

_PATTERN = re.compile(
    r"(?<![0-9A-Za-z+])"  # not glued to a word, a longer number or a "+91" prefix
    r"(?<![0-9][ -])"  # not the tail of a grouped digit sequence ("4278 6838 7380 6954")
    r"(?P<value>[2-9][0-9]{3}(?P<sep>[ -]?)[0-9]{4}(?P=sep)[0-9]{4})"
    r"(?![0-9A-Za-z])"
    r"(?![ -][0-9])"  # not the head of a grouped digit sequence
)

# "91" + a 10-digit mobile written without a plus is also 12 digits. One in ten of those
# passes Verhoeff by chance, so such numbers get a low score and the phone recognizer's
# span (same length, higher score) wins in overlap resolution.
_PHONE_LIKE = re.compile(r"91[6-9][0-9]{9}")


class AadhaarRecognizer(Recognizer):
    name = "aadhaar"
    entity_types = frozenset({EntityType.AADHAAR})

    SCORE = 0.9
    PHONE_LIKE_SCORE = 0.4

    def analyze(self, text: str) -> Iterator[Entity]:
        for m in _PATTERN.finditer(text):
            value = m.group("value")
            digits = value.replace(" ", "").replace("-", "")
            if not verhoeff_valid(digits):
                continue
            score = self.PHONE_LIKE_SCORE if _PHONE_LIKE.fullmatch(value) else self.SCORE
            start, end = m.span("value")
            yield Entity(EntityType.AADHAAR, start, end, value, score, self.name)
