"""Per-entity-type precision/recall against gold spans (exact type + span match)."""

from collections.abc import Iterable
from dataclasses import dataclass

from shoji.detect.recognizer import Registry


@dataclass
class TypeScore:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0


Span = tuple[str, int, int]  # (type, start, end)


def score_spans(pairs: Iterable[tuple[set[Span], set[Span]]]) -> dict[str, TypeScore]:
    """Score ``(gold, predicted)`` span sets, one pair per text. A prediction counts only if
    its type and both offsets match a gold span exactly."""
    scores: dict[str, TypeScore] = {}
    for gold, predicted in pairs:
        for t, *_ in gold | predicted:
            scores.setdefault(t, TypeScore())
        for t, *_ in gold & predicted:
            scores[t].tp += 1
        for t, *_ in predicted - gold:
            scores[t].fp += 1
        for t, *_ in gold - predicted:
            scores[t].fn += 1
    return dict(sorted(scores.items()))


def evaluate(samples: Iterable, registry: Registry) -> dict[str, TypeScore]:
    """Score ``registry.detect`` on samples with ``.text`` and gold ``.spans`` (see
    ``shoji.synthetic.Sample``)."""
    return score_spans(
        (
            {(g.type, g.start, g.end) for g in s.spans},
            {(str(e.type), e.start, e.end) for e in registry.detect(s.text)},
        )
        for s in samples
    )


def format_report(scores: dict[str, TypeScore]) -> str:
    lines = [f"{'type':<12} {'tp':>5} {'fp':>5} {'fn':>5} {'prec':>6} {'recall':>6} {'f1':>6}"]
    for t, s in scores.items():
        lines.append(
            f"{t:<12} {s.tp:>5} {s.fp:>5} {s.fn:>5} "
            f"{s.precision:>6.3f} {s.recall:>6.3f} {s.f1:>6.3f}"
        )
    return "\n".join(lines)
