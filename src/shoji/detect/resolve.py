"""Overlap resolution: turn the raw output of all recognizers into non-overlapping spans."""

from bisect import bisect_left
from collections.abc import Iterable

from shoji.detect.entity import Entity


def _priority(e: Entity) -> tuple:
    # Longer span first, then higher score. The rest only makes the result deterministic
    # (independent of recognizer order): earlier start, then type and recognizer by name.
    return (-e.length, -e.score, e.start, e.type, e.recognizer)


def resolve(entities: Iterable[Entity]) -> list[Entity]:
    """Keep a maximal set of non-overlapping entities, sorted by start offset.

    Entities are taken greedily in priority order (see ``_priority``); one that overlaps an
    already kept entity is dropped. Spans that merely touch (``a.end == b.start``) do not
    overlap. Identical spans from different recognizers collapse to the best-scoring one.
    """
    kept: list[Entity] = []  # non-overlapping, so sorted by start is also sorted by end
    starts: list[int] = []
    for e in sorted(entities, key=_priority):
        i = bisect_left(starts, e.start)
        if i > 0 and kept[i - 1].end > e.start:
            continue
        if i < len(kept) and kept[i].start < e.end:
            continue
        kept.insert(i, e)
        starts.insert(i, e.start)
    return kept
