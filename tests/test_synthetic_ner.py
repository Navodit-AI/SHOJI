"""Names, addresses and organisations in the synthetic generator (Stage 4 ground truth)."""

import random
import re
from collections import Counter

import pytest

from shoji.detect import NER_TYPES, EntityType
from shoji.synthetic import Template, ValueFactory, generate, render
from shoji.synthetic.values import (
    CITIES,
    FIRST_NAMES,
    HONORIFICS,
    NAME_WORDS,
    SURNAMES,
    Persona,
)

SAMPLES = generate(3000, seed=33)


@pytest.fixture
def factory():
    return ValueFactory(random.Random(33))


def test_every_ner_type_and_decoy_appears():
    types = Counter(g.type for s in SAMPLES for g in s.spans)
    decoys = Counter(d.type for s in SAMPLES for d in s.decoys)
    for t in NER_TYPES:
        assert types[t] >= 100, (t, types)
    assert decoys["PLACE"] >= 50 and decoys["NAME_WORD"] >= 50


def test_ner_types_in_every_language():
    langs = {(g.type, s.lang) for s in SAMPLES for g in s.spans if g.type in NER_TYPES}
    for lang in ("en", "hinglish", "hi"):
        assert (EntityType.PERSON, lang) in langs
        assert (EntityType.ADDRESS, lang) in langs
    assert (EntityType.ORG, "en") in langs and (EntityType.ORG, "hinglish") in langs


def test_decoys_never_overlap_gold_spans():
    for s in SAMPLES:
        for d in s.decoys:
            assert s.text[d.start : d.end] == d.text
            for g in s.spans:
                assert d.end <= g.start or g.end <= d.start, (s.template_id, d, g)


def test_other_person_is_a_different_person():
    t = Template("t", "en", "{PERSON} and {OTHER_PERSON}")
    differ = 0
    for seed in range(50):
        a, b = render(t, ValueFactory(random.Random(seed))).spans
        assert a.type == b.type == EntityType.PERSON
        differ += a.text != b.text
    assert differ >= 45


def test_name_forms(factory):
    p = Persona("Priya", "Nair")
    forms = Counter()
    for _ in range(500):
        before, value, after = factory.person_name(p)
        assert value in {"Priya Nair", "Priya", "Nair", "P. Nair"}
        assert before in {"", *HONORIFICS}
        assert after in {"", "-ji", " ji"}
        if before:
            assert value == "Priya Nair"  # honorific outside the span
        forms[(bool(before), value, bool(after))] += 1
    assert len(forms) >= 5


def test_honorific_and_ji_are_outside_the_gold_span():
    t = Template("t", "en", "Dear {PERSON}, thanks.")
    seen_outside = 0
    for seed in range(300):
        s = render(t, ValueFactory(random.Random(seed)))
        (g,) = s.spans
        assert s.text[g.start : g.end] == g.text
        assert not any(g.text.startswith(h.strip()) for h in HONORIFICS)
        assert not g.text.endswith("ji")
        seen_outside += s.text[5 : g.start] != "" or s.text[g.end : g.end + 1] != ","
    assert seen_outside > 0


def test_addresses_end_with_the_city_pin(factory):
    prefixes = {city: prefix for city, _, prefix, _ in CITIES}
    for _ in range(500):
        a = factory.address()
        pin = a[-6:]
        assert re.fullmatch(r"[1-9][0-9]{5}", pin), a
        cities = [c for c in prefixes if f", {c}" in a]
        assert len(cities) == 1, a
        assert pin.startswith(prefixes[cities[0]]), a


def test_devanagari_address_and_name(factory):
    for _ in range(50):
        a = factory.address_hi()
        assert re.fullmatch(r"मकान नं\. \d+, .+, .+ [1-9][0-9]{5}", a), a
        _, name, _ = factory.person_name_hi()
        assert re.fullmatch(r"[ऀ-ॿ ]+", name), name


def test_orgs(factory):
    p = Persona("Amit", "Patil")
    orgs = [factory.org(p) for _ in range(300)]
    assert any("Patil" in o for o in orgs)
    assert any(o.endswith("Hospital") for o in orgs)
    assert all(o == o.strip() and "  " not in o for o in orgs)


def test_name_words_are_decoys_not_names():
    t = Template("t", "en", "A [[NAME_WORD:Rose]] for {PERSON}.")
    s = render(t, ValueFactory(random.Random(1)))
    (d,) = s.decoys
    assert (d.type, d.text, s.text[d.start : d.end]) == ("NAME_WORD", "Rose", "Rose")
    assert [g.type for g in s.spans] == ["PERSON"]
    assert {w.lower() for w in NAME_WORDS} >= {"rose", "asha", "kiran"}


def test_literal_must_be_a_decoy_type():
    with pytest.raises(KeyError, match="not a decoy type"):
        render(Template("t", "en", "[[PERSON:Rahul]]"), ValueFactory(random.Random(0)))


def test_name_lists_are_ascii_and_unique():
    for names in (FIRST_NAMES, SURNAMES):
        assert len(set(names)) == len(names)
        assert all(n.isascii() and n.isalpha() for n in names)


def test_rule_recognizers_stay_silent_on_names_and_addresses():
    """No rule-based detection may land on a name, address or organisation."""
    from shoji.detect import detect

    for s in SAMPLES:
        ner_spans = [g for g in s.spans if g.type in NER_TYPES]
        for e in detect(s.text):
            for g in ner_spans:
                assert e.end <= g.start or g.end <= e.start, (s.template_id, e, g)
