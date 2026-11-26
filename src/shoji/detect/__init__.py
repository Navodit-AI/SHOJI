"""Personal-data detection: recognizers produce candidate spans, the resolver de-overlaps them."""

from shoji.detect.entity import NER_TYPES, Entity, EntityType
from shoji.detect.recognizer import (
    PatternRecognizer,
    Recognizer,
    Registry,
    default_registry,
    detect,
)
from shoji.detect.resolve import resolve

__all__ = [
    "NER_TYPES",
    "Entity",
    "EntityType",
    "PatternRecognizer",
    "Recognizer",
    "Registry",
    "default_registry",
    "detect",
    "resolve",
]
