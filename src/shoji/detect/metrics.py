"""Per-entity-type precision/recall against gold spans.

Two ways to count a hit: ``exact`` (same type and both offsets) and ``overlap`` (same type
and the spans share at least one character, matched one-to-one). Exact is the strict
headline; overlap shows how much of the gap is only about boundaries ("Dr. Priya Nair" vs
"Priya Nair").
"""

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


def _overlap_matches(gold: set[Span], predicted: set[Span]) -> set[tuple[Span, Span]]:
    """One-to-one (gold, predicted) pairs of the same type that share a character. Exact
    matches are paired first, then the remaining spans greedily by largest overlap."""
    pairs = {(g, g) for g in gold & predicted}
    free_gold, free_pred = gold - predicted, predicted - gold
    candidates = sorted(
        (
            (min(g[2], p[2]) - max(g[1], p[1]), g, p)
            for g in free_gold
            for p in free_pred
            if g[0] == p[0] and g[1] < p[2] and p[1] < g[2]
        ),
        reverse=True,
    )
    for _, g, p in candidates:
        if g in free_gold and p in free_pred:
            pairs.add((g, p))
            free_gold.discard(g)
            free_pred.discard(p)
    return pairs


def score_spans(
    pairs: Iterable[tuple[set[Span], set[Span]]], match: str = "exact"
) -> dict[str, TypeScore]:
    """Score ``(gold, predicted)`` span sets, one pair per text. ``match`` is ``"exact"``
    (type and both offsets) or ``"overlap"`` (type, and at least one shared character)."""
    if match not in ("exact", "overlap"):
        raise ValueError(f"match must be 'exact' or 'overlap', not {match!r}")
    scores: dict[str, TypeScore] = {}
    for gold, predicted in pairs:
        for t, *_ in gold | predicted:
            scores.setdefault(t, TypeScore())
        if match == "exact":
            hits = {(g, g) for g in gold & predicted}
        else:
            hits = _overlap_matches(gold, predicted)
        matched_gold = {g for g, _ in hits}
        matched_pred = {p for _, p in hits}
        for g, _ in hits:
            scores[g[0]].tp += 1
        for t, *_ in predicted - matched_pred:
            scores[t].fp += 1
        for t, *_ in gold - matched_gold:
            scores[t].fn += 1
    return dict(sorted(scores.items()))


def evaluate(samples: Iterable, registry: Registry, match: str = "exact") -> dict[str, TypeScore]:
    """Score ``registry.detect`` on samples with ``.text`` and gold ``.spans`` (see
    ``shoji.synthetic.Sample``)."""
    return score_spans(
        (
            (
                {(g.type, g.start, g.end) for g in s.spans},
                {(str(e.type), e.start, e.end) for e in registry.detect(s.text)},
            )
            for s in samples
        ),
        match=match,
    )


def format_report(scores: dict[str, TypeScore]) -> str:
    lines = [f"{'type':<12} {'tp':>5} {'fp':>5} {'fn':>5} {'prec':>6} {'recall':>6} {'f1':>6}"]
    for t, s in scores.items():
        lines.append(
            f"{t:<12} {s.tp:>5} {s.fp:>5} {s.fn:>5} "
            f"{s.precision:>6.3f} {s.recall:>6.3f} {s.f1:>6.3f}"
        )
    return "\n".join(lines)
