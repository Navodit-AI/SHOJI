"""Synthetic Indian personal data for tests and evaluation. Fake values only, never real people."""

from shoji.synthetic.corpus import (
    DECOY_TYPES,
    SLOT_TYPES,
    TEMPLATES,
    GoldSpan,
    Sample,
    SyntheticCorpus,
    Template,
    generate,
    render,
)
from shoji.synthetic.values import Persona, ValueFactory

__all__ = [
    "DECOY_TYPES",
    "SLOT_TYPES",
    "TEMPLATES",
    "GoldSpan",
    "Persona",
    "Sample",
    "SyntheticCorpus",
    "Template",
    "ValueFactory",
    "generate",
    "render",
]
