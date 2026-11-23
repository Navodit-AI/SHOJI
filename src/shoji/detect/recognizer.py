"""The recognizer interface, a regex-based helper, and the registry that runs them all."""

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Iterator

from shoji.detect.entity import Entity
from shoji.detect.resolve import resolve


class Recognizer(ABC):
    """Finds one or more entity types in text. Subclasses set ``name`` and ``entity_types``."""

    name: str
    entity_types: frozenset[str]

    @abstractmethod
    def analyze(self, text: str) -> Iterable[Entity]:
        """Yield every candidate span; overlaps are fine, the registry resolves them."""


class PatternRecognizer(Recognizer):
    """A regex plus an optional validator (e.g. a checksum) for one entity type.

    If the pattern has a group named ``value``, that group is the entity span, so the
    surrounding context (word boundaries, prefixes) can be matched without being redacted.
    A validator receives the matched value and returns False to reject it.

    Note: in Python ``\\d`` also matches non-ASCII digits (e.g. Devanagari ``४``); use
    ``[0-9]`` or ``re.ASCII`` where only ASCII digits are meant.
    """

    def __init__(
        self,
        name: str,
        entity_type: str,
        pattern: str | re.Pattern[str],
        score: float,
        validator: Callable[[str], bool] | None = None,
    ) -> None:
        self.name = name
        self.entity_type = entity_type
        self.entity_types = frozenset({entity_type})
        self.pattern = re.compile(pattern) if isinstance(pattern, str) else pattern
        self.score = score
        self.validator = validator

    def analyze(self, text: str) -> Iterator[Entity]:
        group = "value" if "value" in self.pattern.groupindex else 0
        for m in self.pattern.finditer(text):
            start, end = m.span(group)
            if start == end:
                continue
            value = text[start:end]
            if self.validator is not None and not self.validator(value):
                continue
            yield Entity(self.entity_type, start, end, value, self.score, self.name)


class Registry:
    """An ordered set of recognizers; ``detect`` runs them all and resolves overlaps."""

    def __init__(self, recognizers: Iterable[Recognizer] = ()) -> None:
        self._recognizers: dict[str, Recognizer] = {}
        for r in recognizers:
            self.register(r)

    def register(self, recognizer: Recognizer) -> Recognizer:
        if recognizer.name in self._recognizers:
            raise ValueError(f"recognizer {recognizer.name!r} is already registered")
        self._recognizers[recognizer.name] = recognizer
        return recognizer

    @property
    def recognizers(self) -> tuple[Recognizer, ...]:
        return tuple(self._recognizers.values())

    def analyze(self, text: str) -> list[Entity]:
        """All candidate spans from every recognizer, before overlap resolution."""
        found: list[Entity] = []
        for r in self._recognizers.values():
            for e in r.analyze(text):
                # A wrong span would redact the wrong characters, so fail loudly.
                if text[e.start : e.end] != e.text:
                    raise ValueError(
                        f"recognizer {r.name!r} returned span [{e.start}, {e.end}) "
                        f"that does not match its text"
                    )
                found.append(e)
        return found

    def detect(self, text: str) -> list[Entity]:
        return resolve(self.analyze(text))


def default_registry() -> Registry:
    """A fresh registry with the built-in recognizers (added by the Stage 2 issues)."""
    return Registry()


def detect(text: str, registry: Registry | None = None) -> list[Entity]:
    return (registry or default_registry()).detect(text)
