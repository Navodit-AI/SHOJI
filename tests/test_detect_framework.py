"""Recognizer framework: Entity, PatternRecognizer, Registry and overlap resolution."""

import itertools
import random

import pytest

from shoji.detect import (
    Entity,
    PatternRecognizer,
    Recognizer,
    Registry,
    default_registry,
    detect,
    resolve,
)

TEXT = "x" * 100  # resolver tests only need spans whose text has the right length


def ent(start, end, score=0.5, type="T", recognizer="r"):
    return Entity(type, start, end, TEXT[start:end], score, recognizer)


def spans(entities):
    return [(e.start, e.end, e.type) for e in entities]


# --- Entity ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "text", "score"),
    [
        (5, 5, "", 0.5),  # empty span
        (5, 3, "xx", 0.5),  # reversed
        (-1, 2, "xxx", 0.5),  # negative
        (0, 3, "xx", 0.5),  # text length mismatch
        (0, 2, "xx", 1.5),  # score out of range
        (0, 2, "xx", -0.1),
    ],
)
def test_entity_rejects_invalid(start, end, text, score):
    with pytest.raises(ValueError):
        Entity("T", start, end, text, score, "r")


def test_entity_overlap_is_half_open():
    assert ent(0, 5).overlaps(ent(4, 8))
    assert not ent(0, 5).overlaps(ent(5, 8))  # touching
    assert ent(0, 10).overlaps(ent(3, 4))  # nested


# --- resolve ----------------------------------------------------------------------------


def test_resolve_empty():
    assert resolve([]) == []


def test_disjoint_and_touching_spans_all_kept_sorted():
    result = resolve([ent(20, 25), ent(0, 5), ent(5, 9)])
    assert spans(result) == [(0, 5, "T"), (5, 9, "T"), (20, 25, "T")]


def test_nested_keeps_outer_even_if_inner_scores_higher():
    outer, inner = ent(0, 12, score=0.4, type="PHONE"), ent(2, 6, score=0.99, type="PIN")
    assert resolve([inner, outer]) == [outer]


def test_partial_overlap_keeps_longer():
    longer, shorter = ent(0, 10, score=0.3), ent(8, 14, score=0.9)
    assert resolve([shorter, longer]) == [longer]


def test_partial_overlap_equal_length_keeps_higher_score():
    a, b = ent(0, 6, score=0.6), ent(3, 9, score=0.8)
    assert resolve([a, b]) == [b]


def test_partial_overlap_equal_length_and_score_keeps_earlier():
    a, b = ent(0, 6), ent(3, 9)
    assert resolve([b, a]) == [a]


def test_identical_spans_keep_higher_score():
    low = ent(0, 6, score=0.5, type="PAN", recognizer="pan")
    high = ent(0, 6, score=0.9, type="GSTIN_FRAGMENT", recognizer="gstin")
    assert resolve([low, high]) == [high]


def test_identical_spans_full_tie_broken_by_type_then_recognizer():
    a = ent(0, 6, type="A", recognizer="z")
    b = ent(0, 6, type="B", recognizer="a")
    c = ent(0, 6, type="A", recognizer="y")
    assert resolve([a, b, c]) == [c]


def test_dropping_a_span_can_keep_its_neighbours():
    # left and right do not overlap each other; the middle one overlaps both but is shorter.
    left, middle, right = ent(0, 10), ent(8, 13), ent(12, 22)
    assert resolve([middle, right, left]) == [left, right]


def test_chain_greedy_by_priority():
    # A beats B, so B is dropped, and C (which only overlapped B) survives.
    a, b, c = ent(0, 10), ent(5, 14), ent(12, 16)
    assert resolve([c, b, a]) == [a, c]


def test_result_is_independent_of_input_order():
    entities = [
        ent(0, 10, 0.5),
        ent(0, 10, 0.5, type="U"),
        ent(5, 15, 0.7),
        ent(14, 18, 0.9),
        ent(16, 30, 0.2),
        ent(30, 31, 0.1),
        ent(2, 4, 1.0),
    ]
    expected = resolve(entities)
    for perm in itertools.permutations(entities):
        assert resolve(perm) == expected


def test_result_never_overlaps_and_is_sorted_random():
    rng = random.Random(0)
    for _ in range(200):
        entities = []
        for _ in range(rng.randint(0, 15)):
            start = rng.randint(0, 90)
            end = start + rng.randint(1, 10)
            entities.append(ent(start, end, round(rng.random(), 2), rng.choice("ABC")))
        result = resolve(entities)
        assert result == sorted(result, key=lambda e: e.start)
        for x, y in itertools.pairwise(result):
            assert x.end <= y.start
        # Maximality: every dropped entity overlaps something that was kept.
        for e in entities:
            if e not in result:
                assert any(e.overlaps(k) for k in result)


# --- PatternRecognizer ------------------------------------------------------------------


def test_pattern_recognizer_basic():
    r = PatternRecognizer("digits", "NUM", r"[0-9]{4}", score=0.6)
    text = "codes 1234 and 5678"
    found = list(r.analyze(text))
    assert [(e.text, e.start, e.end, e.score, e.recognizer) for e in found] == [
        ("1234", 6, 10, 0.6, "digits"),
        ("5678", 15, 19, 0.6, "digits"),
    ]


def test_pattern_recognizer_value_group_excludes_context():
    r = PatternRecognizer("pin", "PIN", r"PIN:\s*(?P<value>[0-9]{6})", score=0.7)
    text = "PIN: 560001"
    (e,) = r.analyze(text)
    assert (e.start, e.end, e.text) == (5, 11, "560001")


def test_pattern_recognizer_validator_filters():
    r = PatternRecognizer("even", "NUM", r"[0-9]+", 0.5, validator=lambda v: int(v) % 2 == 0)
    assert [e.text for e in r.analyze("1 2 33 44")] == ["2", "44"]


@pytest.mark.parametrize(
    "prefix",
    [
        "मेरा नंबर है ",  # Devanagari, including combining vowel signs
        "call me 🙂👍🏽 ",  # emoji incl. a skin-tone modifier (multi-code-point)
        "naam: राहुल, café, 👨‍👩‍👧 ",  # Hinglish, accented Latin, ZWJ sequence
    ],
)
def test_offsets_correct_after_non_ascii(prefix):
    r = PatternRecognizer("digits", "NUM", r"[0-9]{10}", 0.5)
    text = prefix + "9876543210 ठीक है?"
    (e,) = r.analyze(text)
    assert text[e.start : e.end] == "9876543210"
    assert e.start == len(prefix)


def test_ascii_digit_class_ignores_devanagari_digits():
    # The pitfall documented on PatternRecognizer: \d matches Devanagari digits.
    text = "९८७६५४३२१०"
    assert list(PatternRecognizer("d", "N", r"\d{10}", 0.5).analyze(text))
    assert not list(PatternRecognizer("a", "N", r"[0-9]{10}", 0.5).analyze(text))


# --- Registry ---------------------------------------------------------------------------


def test_registry_runs_all_and_resolves():
    phone = PatternRecognizer("phone", "PHONE", r"[0-9]{10}", 0.8)
    four = PatternRecognizer("four", "NUM4", r"[0-9]{4}", 0.9)
    email = PatternRecognizer("email", "EMAIL", r"\S+@\S+", 0.9)
    reg = Registry([phone, four, email])
    text = "ring 9876543210 or a@b.in ref 4321"
    assert [(e.type, e.text) for e in reg.detect(text)] == [
        ("PHONE", "9876543210"),
        ("EMAIL", "a@b.in"),
        ("NUM4", "4321"),
    ]
    # analyze() exposes the raw candidates, before resolution.
    assert len(reg.analyze(text)) > len(reg.detect(text))


def test_registry_rejects_duplicate_names():
    reg = Registry([PatternRecognizer("x", "A", "a", 0.5)])
    with pytest.raises(ValueError, match="already registered"):
        reg.register(PatternRecognizer("x", "B", "b", 0.5))


def test_registry_rejects_span_not_matching_text():
    class OffByOne(Recognizer):
        name = "off_by_one"
        entity_types = frozenset({"T"})

        def analyze(self, text):
            yield Entity("T", 1, 3, text[0:2], 0.5, self.name)

    with pytest.raises(ValueError, match="off_by_one"):
        Registry([OffByOne()]).detect("abcd")


def test_registry_preserves_registration_order():
    a, b = PatternRecognizer("a", "A", "a", 0.5), PatternRecognizer("b", "B", "b", 0.5)
    assert Registry([b, a]).recognizers == (b, a)


def test_default_detect_on_plain_text():
    assert detect("nothing personal here") == []
    assert isinstance(default_registry(), Registry)
