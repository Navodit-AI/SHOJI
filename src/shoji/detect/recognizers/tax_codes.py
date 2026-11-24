"""PAN, GSTIN and IFSC codes.

Case policy (all three): codes are officially uppercase. An all-lowercase code is accepted
with a lower score, because people type ``abcpd1234f`` in chat. Mixed case
(``AbCpD1234f``) is rejected: it is far more likely to be some other token.

A PAN is always embedded in a GSTIN (characters 3-12). The PAN recognizer also reports that
inner PAN, so a GSTIN with a typo in its check character still has its PAN caught. When the
GSTIN itself is valid, overlap resolution keeps the longer GSTIN span and drops the PAN.
"""

import re
from collections.abc import Iterator

from shoji.detect.checksums import gstin_valid
from shoji.detect.entity import Entity, EntityType
from shoji.detect.formats import GST_STATE_CODES, PAN_HOLDER_TYPES
from shoji.detect.recognizer import Recognizer

_EDGE_BEFORE = r"(?<![0-9A-Za-z])"
_EDGE_AFTER = r"(?![0-9A-Za-z])"
_PAN = r"[A-Za-z]{5}[0-9]{4}[A-Za-z]"


def _case_score(value: str, upper: float, lower: float) -> float | None:
    """Score for a code by its letter case; ``None`` for mixed case."""
    if value == value.upper():
        return upper
    if value == value.lower():
        return lower
    return None


class _CodeRecognizer(Recognizer):
    """A regex whose ``value`` group is validated and scored by letter case."""

    entity_type: EntityType
    patterns: tuple[re.Pattern[str], ...]
    upper_score: float
    lower_score: float

    def __init__(self) -> None:
        self.entity_types = frozenset({self.entity_type})

    def valid(self, code: str) -> bool:
        """Extra checks on the uppercased code."""
        return True

    def analyze(self, text: str) -> Iterator[Entity]:
        seen: set[tuple[int, int]] = set()
        for pattern in self.patterns:
            for m in pattern.finditer(text):
                span = m.span("value")
                if span in seen:
                    continue
                value = m.group("value")
                score = _case_score(value, self.upper_score, self.lower_score)
                if score is None or not self.valid(value.upper()):
                    continue
                seen.add(span)
                yield Entity(self.entity_type, *span, value, score, self.name)


class PanRecognizer(_CodeRecognizer):
    """``AAAAA9999A``; the 4th letter is the holder type (P, C, H, F, A, T, B, L, J, G).

    PAN has no published check character, so the holder type is the only validation.
    """

    name = "pan"
    entity_type = EntityType.PAN
    upper_score = 0.85
    lower_score = 0.6
    patterns = (
        re.compile(_EDGE_BEFORE + f"(?P<value>{_PAN})" + _EDGE_AFTER),
        # The PAN inside a GSTIN-shaped token, whether or not that GSTIN is valid.
        re.compile(_EDGE_BEFORE + f"[0-9]{{2}}(?P<value>{_PAN})[0-9A-Za-z]{{3}}" + _EDGE_AFTER),
    )

    def valid(self, code: str) -> bool:
        return code[3] in PAN_HOLDER_TYPES


class GstinRecognizer(_CodeRecognizer):
    """15 characters: state code + PAN + entity number (1-9, A-Z) + ``Z`` + check character."""

    name = "gstin"
    entity_type = EntityType.GSTIN
    upper_score = 0.95  # the check character makes a chance match very unlikely
    lower_score = 0.85
    patterns = (
        re.compile(
            _EDGE_BEFORE + f"(?P<value>[0-9]{{2}}{_PAN}[1-9A-Za-z][Zz][0-9A-Za-z])" + _EDGE_AFTER
        ),
    )

    def valid(self, code: str) -> bool:
        return code[:2] in GST_STATE_CODES and code[5] in PAN_HOLDER_TYPES and gstin_valid(code)


class IfscRecognizer(_CodeRecognizer):
    """Bank branch code: 4 letters (bank) + ``0`` + 6 alphanumerics (branch)."""

    name = "ifsc"
    entity_type = EntityType.IFSC
    upper_score = 0.85
    lower_score = 0.6
    patterns = (re.compile(_EDGE_BEFORE + r"(?P<value>[A-Za-z]{4}0[0-9A-Za-z]{6})" + _EDGE_AFTER),)
