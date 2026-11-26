"""The detection result type shared by every recognizer (rule-based now, ML from Stage 4)."""

from dataclasses import dataclass
from enum import StrEnum


class EntityType(StrEnum):
    """Entity type names shared by recognizers, the synthetic data and evaluation.

    A ``StrEnum``, so members compare equal to plain strings (``EntityType.PAN == "PAN"``).
    """

    AADHAAR = "AADHAAR"
    PAN = "PAN"
    GSTIN = "GSTIN"
    IFSC = "IFSC"
    UPI_ID = "UPI_ID"
    PHONE = "PHONE"
    EMAIL = "EMAIL"
    CARD_NUMBER = "CARD_NUMBER"
    IP_ADDRESS = "IP_ADDRESS"
    PERSON = "PERSON"
    ADDRESS = "ADDRESS"
    ORG = "ORG"


# Types with no fixed format, left to the NER model (Stage 4); the rest are rule-based.
NER_TYPES = frozenset({EntityType.PERSON, EntityType.ADDRESS, EntityType.ORG})


@dataclass(frozen=True, slots=True)
class Entity:
    """One detected span of personal data.

    Offsets are Python string indices (Unicode code points) into the analysed text, half-open:
    ``text[start:end] == entity.text``. Code points, not bytes or UTF-16 units, so Devanagari
    and emoji earlier in the text do not shift the span. Anything that reports spans to a
    non-Python consumer (e.g. a JS dashboard, which indexes UTF-16) must convert.
    """

    type: str  # e.g. "AADHAAR", "PAN", "PERSON"
    start: int
    end: int
    text: str
    score: float  # confidence in [0, 1]
    recognizer: str  # name of the recognizer that produced it

    def __post_init__(self) -> None:
        if not 0 <= self.start < self.end:
            raise ValueError(f"invalid span [{self.start}, {self.end})")
        if len(self.text) != self.end - self.start:
            raise ValueError(
                f"text length {len(self.text)} does not match span [{self.start}, {self.end})"
            )
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score {self.score} outside [0, 1]")

    @property
    def length(self) -> int:
        return self.end - self.start

    def overlaps(self, other: "Entity") -> bool:
        return self.start < other.end and other.start < self.end
