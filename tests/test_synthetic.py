"""Synthetic generator: values are format/checksum valid, look-alikes are not, spans are exact."""

import json
import random
import re

import pytest

from shoji.detect import EntityType
from shoji.detect.checksums import gstin_valid, luhn_valid, verhoeff_valid
from shoji.detect.formats import GST_STATE_CODES, PAN_HOLDER_TYPES, upi_psp_handles
from shoji.synthetic import (
    DECOY_TYPES,
    TEMPLATES,
    SyntheticCorpus,
    Template,
    ValueFactory,
    generate,
    render,
)

N = 300


@pytest.fixture
def factory():
    return ValueFactory(random.Random(42))


def digits_only(s):
    return re.sub(r"[^0-9]", "", s)


# --- Valid values ---------------------------------------------------------------------------


def test_aadhaar(factory):
    for _ in range(N):
        value = factory.aadhaar()
        assert re.fullmatch(r"[2-9][0-9]{3}([ -]?)[0-9]{4}\1[0-9]{4}", value), value
        assert verhoeff_valid(digits_only(value))


def test_pan(factory):
    for _ in range(N):
        value = factory.pan(surname="Sharma")
        assert re.fullmatch(r"[A-Z]{3}PS[0-9]{4}[A-Z]", value), value
        assert value[3] in PAN_HOLDER_TYPES
        assert value[5:9] != "0000"


def test_gstin(factory):
    for _ in range(N):
        value = factory.gstin()
        assert re.fullmatch(r"[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]", value), value
        assert value[:2] in GST_STATE_CODES
        assert value[5] in PAN_HOLDER_TYPES  # embedded PAN's holder type
        assert gstin_valid(value)


def test_ifsc(factory):
    for _ in range(N):
        assert re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", factory.ifsc())


def test_upi_id(factory):
    handles = upi_psp_handles()
    person = factory.persona()
    for _ in range(N):
        value = factory.upi_id(person)
        user, handle = value.split("@")
        assert handle in handles
        assert "." not in handle  # never email-like
        assert re.fullmatch(r"[a-z0-9.]+", user), value


def test_phone(factory):
    seen_shapes = set()
    for _ in range(N):
        value = factory.phone()
        national = digits_only(value)
        if len(national) == 12:
            assert national.startswith("91")
            national = national[2:]
        elif len(national) == 11:
            assert national.startswith("0")
            national = national[1:]
        assert re.fullmatch(r"[6-9][0-9]{9}", national), value
        seen_shapes.add(re.sub(r"[0-9]", "9", value))
    assert len(seen_shapes) >= 8  # varied formatting, not one shape


def test_email(factory):
    for _ in range(N):
        value = factory.email()
        assert re.fullmatch(r"[a-z0-9.]+@([a-z]+\.)*example\.[a-z.]+", value), value


def test_card_number(factory):
    for _ in range(N):
        value = factory.card_number()
        assert re.fullmatch(r"[0-9]{4}([ -]?)[0-9]{4}\1[0-9]{4}\1[0-9]{4}", value), value
        assert luhn_valid(digits_only(value))


# --- Look-alikes ----------------------------------------------------------------------------


def test_order_id_is_aadhaar_shaped_but_fails_verhoeff(factory):
    for _ in range(N):
        value = factory.order_id()
        assert re.fullmatch(r"[2-9][0-9]{11}", value)
        assert not verhoeff_valid(value)


def test_non_mobile_number_is_not_a_mobile(factory):
    for _ in range(N):
        assert re.fullmatch(r"[1-5][0-9]{9}", factory.non_mobile_number())


def test_non_card_number_fails_luhn(factory):
    for _ in range(N):
        value = factory.non_card_number()
        assert re.fullmatch(r"[0-9]{16}", value)
        assert not luhn_valid(value)


# --- Corpus ----------------------------------------------------------------------------------


def test_same_seed_same_output_different_seed_different_output():
    assert generate(100, seed=7) == generate(100, seed=7)
    assert generate(100, seed=7) != generate(100, seed=8)


def test_every_template_renders_and_round_robin_covers_all():
    samples = generate(len(TEMPLATES), seed=3)
    assert {s.template_id for s in samples} == {t.id for t in TEMPLATES}
    assert len({t.id for t in TEMPLATES}) == len(TEMPLATES)  # ids are unique


def test_spans_are_exact_sorted_and_disjoint():
    for s in generate(500, seed=5):
        assert "{" not in s.text and "}" not in s.text  # every slot was filled
        all_spans = sorted(s.spans + s.decoys, key=lambda g: g.start)
        for g in all_spans:
            assert s.text[g.start : g.end] == g.text
        for a, b in zip(all_spans, all_spans[1:], strict=False):
            assert a.end <= b.start


def test_span_types():
    entity_types = set(EntityType)
    for s in generate(500, seed=6):
        assert {g.type for g in s.spans} <= entity_types
        assert {g.type for g in s.decoys} <= DECOY_TYPES


def test_corpus_has_negatives_decoys_and_all_languages():
    samples = generate(len(TEMPLATES) * 3, seed=9)
    assert any(not s.spans and s.decoys for s in samples)  # look-alikes only
    assert any(not s.spans and not s.decoys for s in samples)  # nothing at all
    assert any(s.spans and s.decoys for s in samples)  # mixed
    assert {s.lang for s in samples} == {"en", "hinglish", "hi"}
    covered = {g.type for s in samples for g in s.spans}
    assert covered == set(EntityType)


def test_offsets_after_devanagari_and_emoji():
    t = Template("t", "hi", "आधार 🙏🏽 {AADHAAR} और {PHONE}")
    s = render(t, ValueFactory(random.Random(0)))
    aadhaar, phone = s.spans
    assert aadhaar.start == len("आधार 🙏🏽 ")
    assert s.text[phone.start : phone.end] == phone.text


def test_persona_ties_name_to_email_and_pan():
    t = Template("t", "en", "{PERSON} <{EMAIL}> PAN {PAN}")
    for seed in range(20):
        s = render(t, ValueFactory(random.Random(seed)))
        person, email, pan = s.spans
        first, last = person.text.lower().split()
        assert last in email.text or first in email.text
        assert pan.text[4] == last[0].upper()


def test_unknown_slot_raises():
    with pytest.raises(KeyError, match="NOPE"):
        render(Template("bad", "en", "x {NOPE}"), ValueFactory(random.Random(0)))


def test_samples_are_json_serialisable():
    s = SyntheticCorpus(seed=1).samples(1)[0]
    data = json.loads(json.dumps(s.to_dict(), ensure_ascii=False))
    assert data["text"] == s.text
    assert len(data["spans"]) == len(s.spans)
