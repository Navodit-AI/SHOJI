"""Personal-data detection: recognizers produce candidate spans, the resolver de-overlaps them."""

from shoji.detect.entity import Entity
from shoji.detect.recognizer import (
    PatternRecognizer,
    Recognizer,
    Registry,
    default_registry,
    detect,
)
from shoji.detect.resolve import resolve

__all__ = [
    "Entity",
    "PatternRecognizer",
    "Recognizer",
    "Registry",
    "default_registry",
    "detect",
    "resolve",
]
