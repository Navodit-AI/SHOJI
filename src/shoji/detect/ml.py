"""Named-entity recognition with a small model, for data that has no fixed format.

``NerRecognizer`` turns a model's predictions into ``Entity`` objects like any other
recognizer. The model sits behind a tiny backend interface, so tests use a fake and the real
model (GLiNER) is only imported, and downloaded, when it is first used. Nothing here imports
torch at module load: ``import shoji.detect`` stays fast and works without the ``[ml]`` extra.

Install the model dependencies with ``pip install -e ".[ml]"``.
"""

import re
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from shoji.detect.entity import Entity, EntityType
from shoji.detect.recognizer import Recognizer

# Chosen by eval/ner_models.py (results/ner_models.md): best exact F1 of the candidates, and
# per-type thresholds that maximise F2 (recall-weighted: a miss leaks data).
DEFAULT_MODEL = "urchade/gliner_multi_pii-v1"
DEFAULT_THRESHOLDS: dict[str, float] = {
    EntityType.PERSON: 0.2,
    EntityType.ADDRESS: 0.3,
    EntityType.ORG: 0.9,
}

# Natural-language labels the model is asked for, and the entity type each one becomes.
DEFAULT_LABELS: dict[str, str] = {
    "person": EntityType.PERSON,
    "address": EntityType.ADDRESS,
    "organization": EntityType.ORG,
}


@dataclass(frozen=True, slots=True)
class RawSpan:
    """One model prediction, with offsets into the text the backend was given."""

    start: int
    end: int
    label: str
    score: float


class NerBackend(Protocol):
    def predict(self, text: str, labels: Sequence[str], threshold: float) -> list[RawSpan]: ...


_WORD = re.compile(r"\S+")


def windows(text: str, max_words: int, overlap: int) -> Iterator[tuple[int, int]]:
    """Character ranges of overlapping windows of at most ``max_words`` words.

    Windows start and end on word boundaries, so no word is cut. Consecutive windows share
    ``overlap`` words, so an entity cut by one window's edge is whole in the next.
    """
    if not 0 <= overlap < max_words:
        raise ValueError("need 0 <= overlap < max_words")
    words = [m.span() for m in _WORD.finditer(text)]
    if not words:
        return
    i = 0
    while True:
        j = min(i + max_words, len(words))
        yield words[i][0], words[j - 1][1]
        if j == len(words):
            return
        i = j - overlap


class NerRecognizer(Recognizer):
    """Runs an NER backend over (windows of) the text and maps labels to entity types.

    ``thresholds`` is one score for every type, or a score per entity type; predictions
    below it are dropped. Each window is sent to the backend separately and offsets are
    mapped back to the full text, in code points like every other recognizer.

    Models tend to return an address as pieces ("Flat 12", "MG Road", "411001"). For the
    types in ``join_types``, neighbouring spans separated only by spaces, commas or hyphens
    are joined into one, scored by their lowest piece.
    """

    def __init__(
        self,
        backend: NerBackend,
        labels: Mapping[str, str] = DEFAULT_LABELS,
        thresholds: float | Mapping[str, float] = DEFAULT_THRESHOLDS,
        max_words: int = 200,
        overlap: int = 40,
        join_types: frozenset[str] = frozenset({EntityType.ADDRESS}),
        name: str = "ner",
    ) -> None:
        self.backend = backend
        self.labels = dict(labels)
        self.name = name
        self.entity_types = frozenset(self.labels.values())
        if isinstance(thresholds, Mapping):
            self.thresholds = {t: float(thresholds.get(t, 0.5)) for t in self.entity_types}
        else:
            self.thresholds = dict.fromkeys(self.entity_types, float(thresholds))
        self.max_words = max_words
        self.overlap = overlap
        self.join_types = join_types

    def analyze(self, text: str) -> Iterator[Entity]:
        best: dict[tuple[str, int, int], float] = {}
        floor = min(self.thresholds.values())
        for w_start, w_end in windows(text, self.max_words, self.overlap):
            chunk = text[w_start:w_end]
            for raw in self.backend.predict(chunk, list(self.labels), floor):
                entity_type = self.labels.get(raw.label)
                if entity_type is None or raw.score < self.thresholds[entity_type]:
                    continue
                if not 0 <= raw.start < raw.end <= len(chunk):
                    raise ValueError(
                        f"backend returned span [{raw.start}, {raw.end}) outside its text"
                    )
                start, end = _strip(chunk, raw.start, raw.end)
                if start == end:
                    continue
                key = (entity_type, w_start + start, w_start + end)
                best[key] = max(best.get(key, 0.0), raw.score)
        spans = sorted(best.items(), key=lambda kv: kv[0][1:])
        for entity_type, start, end, score in _join(text, spans, self.join_types):
            yield Entity(entity_type, start, end, text[start:end], round(score, 4), self.name)


_JOINABLE_GAP = re.compile(r"[\s,\-–]*")


def _join(text, spans, join_types):
    """Merge neighbouring same-type spans of the given types across separator-only gaps."""
    out: list[list] = []
    for (entity_type, start, end), score in spans:
        prev = out[-1] if out else None
        if (
            prev is not None
            and entity_type in join_types
            and prev[0] == entity_type
            and prev[2] <= start
            and _JOINABLE_GAP.fullmatch(text, prev[2], start)
        ):
            prev[2] = max(prev[2], end)
            prev[3] = min(prev[3], score)
        else:
            out.append([entity_type, start, end, score])
    return [tuple(x) for x in out]


def _strip(text: str, start: int, end: int) -> tuple[int, int]:
    """Trim surrounding whitespace and trailing sentence punctuation from a span."""
    while start < end and text[start].isspace():
        start += 1
    while end > start and (text[end - 1].isspace() or text[end - 1] in ",;:!?"):
        end -= 1
    return start, end


class GlinerBackend:
    """A GLiNER checkpoint from the Hugging Face hub, run on CPU, loaded on first use."""

    def __init__(self, model_id: str = DEFAULT_MODEL) -> None:
        self.model_id = model_id
        self._model: Any = None

    def warm_up(self) -> None:
        """Load (and, the first time, download) the model now instead of on first use."""
        if self._model is not None:
            return
        try:
            from gliner import GLiNER
        except ImportError as exc:
            raise RuntimeError(
                'GLiNER is not installed; install the ML extra: pip install -e ".[ml]"'
            ) from exc
        self._model = GLiNER.from_pretrained(self.model_id, map_location="cpu")
        self._model.eval()

    def predict(self, text: str, labels: Sequence[str], threshold: float) -> list[RawSpan]:
        self.warm_up()
        found = self._model.predict_entities(text, list(labels), threshold=threshold)
        return [RawSpan(p["start"], p["end"], p["label"], float(p["score"])) for p in found]
