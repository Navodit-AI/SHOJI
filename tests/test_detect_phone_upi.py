"""Indian phone and UPI recognizers: formats, boundaries, UPI vs email, synthetic corpus."""

import pytest

from shoji.detect import EntityType, Registry, default_registry, detect
from shoji.detect.checksums import verhoeff_check_digit
from shoji.detect.recognizers import AadhaarRecognizer, IndianPhoneRecognizer, UpiRecognizer
from shoji.synthetic import generate

PHONE, UPI = IndianPhoneRecognizer(), UpiRecognizer()


def found(recognizer, text):
    return [(e.text, e.start, e.end) for e in recognizer.analyze(text)]


# --- Phones --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "score"),
    [
        ("9876543210", IndianPhoneRecognizer.PLAIN_SCORE),
        ("98765 43210", IndianPhoneRecognizer.PLAIN_SCORE),
        ("98765-43210", IndianPhoneRecognizer.PLAIN_SCORE),
        ("987 654 3210", IndianPhoneRecognizer.PLAIN_SCORE),
        ("+91 98765 43210", IndianPhoneRecognizer.PLUS91_SCORE),
        ("+91-98765-43210", IndianPhoneRecognizer.PLUS91_SCORE),
        ("+91-9876543210", IndianPhoneRecognizer.PLUS91_SCORE),
        ("+919876543210", IndianPhoneRecognizer.PLUS91_SCORE),
        ("+91 987 654 3210", IndianPhoneRecognizer.PLUS91_SCORE),
        ("919876543210", IndianPhoneRecognizer.PREFIX_SCORE),
        ("91 98765 43210", IndianPhoneRecognizer.PREFIX_SCORE),
        ("09876543210", IndianPhoneRecognizer.PREFIX_SCORE),
        ("098765 43210", IndianPhoneRecognizer.PREFIX_SCORE),
        ("6000000000", IndianPhoneRecognizer.PLAIN_SCORE),
    ],
)
def test_phone_formats_exact_span_including_prefix(value, score):
    text = f"Call me on {value}, thanks"
    (e,) = PHONE.analyze(text)
    assert (e.text, e.start, e.end, e.score) == (value, 11, 11 + len(value), score)


@pytest.mark.parametrize(
    "text",
    [
        "invoice 5876543210",  # starts with 5: not a mobile
        "98765432",  # too short
        "987654321012345",  # inside a longer run
        "1" + "9876543210",
        "9876543210" + "7",
        "card 4111 98765 43210",  # tail of a grouped sequence
        "98765 43210 1234",  # head of a grouped sequence
        "ID9876543210",  # glued to letters
        "98765 43210".replace(" ", "  "),  # double space
        "9876 543 210",  # unusual grouping
        "98765-432 10",
        "022 2345 6789",  # landline: out of scope
        "+91 22 2345 6789",
        "+1 650 555 0100",
        "९८७६५४३२१०",  # Devanagari digits
        "2026-12-01 10:42",
    ],
)
def test_phone_not_matched(text):
    assert found(PHONE, text) == []


def test_phone_offsets_after_non_ascii():
    prefix = "मेरा नंबर 🙏🏽 "
    assert found(PHONE, prefix + "+91 98765 43210 है") == [
        ("+91 98765 43210", len(prefix), len(prefix) + 15)
    ]


def test_two_phones_in_one_sentence():
    text = "Primary 98765 43210, alternate +91-70000-12345."
    assert [t for t, *_ in found(PHONE, text)] == ["98765 43210", "+91-70000-12345"]


def test_91_number_that_also_passes_verhoeff_resolves_to_phone():
    payload = "91987654321"
    value = payload + verhoeff_check_digit(payload)
    reg = Registry([AadhaarRecognizer(), IndianPhoneRecognizer()])
    assert [(e.type, e.text) for e in reg.detect(f"call {value}")] == [(EntityType.PHONE, value)]


# --- UPI -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    ["rahul.sharma@okaxis", "priya997@ybl", "9876543210@paytm", "a_b-c@upi", "Rahul@OKHDFCBANK"],
)
def test_upi_ids(value):
    text = f"Pay to {value}."
    assert found(UPI, text) == [(value, 7, 7 + len(value))]


@pytest.mark.parametrize(
    "text",
    [
        "rahul@gmail.com",  # email
        "rahul@example.in",
        "rahul@upi.com",  # known handle, but followed by a domain
        "rahul@ybl.co.in",
        "rahul@unknownbank",  # not a known PSP
        "Thanks @paytm for the cashback",  # a mention, no user part
        "r@ybl",  # user part too short
        "rahul@@ybl",
        "rahul@ybl@okaxis",
    ],
)
def test_upi_not_matched(text):
    assert found(UPI, text) == []


def test_upi_handles_come_from_the_data_file():
    assert found(UpiRecognizer(handles=frozenset({"mybank"})), "pay x1@mybank or x2@ybl") == [
        ("x1@mybank", 4, 13)
    ]


def test_upi_with_phone_user_part_is_one_upi_entity():
    text = "Send to 9876543210@ybl please"
    assert [(e.type, e.text) for e in detect(text)] == [(EntityType.UPI_ID, "9876543210@ybl")]


def test_upi_hinglish_sentence():
    text = "Paise priya.nair@oksbi pe bhej do"
    assert [(e.type, e.text) for e in detect(text)] == [(EntityType.UPI_ID, "priya.nair@oksbi")]


# --- Registry and synthetic corpus ---------------------------------------------------------------


def test_registered_by_default():
    names = {r.name for r in default_registry().recognizers}
    assert {"phone_in", "upi"} <= names


TYPES = (
    EntityType.AADHAAR,
    EntityType.PAN,
    EntityType.GSTIN,
    EntityType.IFSC,
    EntityType.PHONE,
    EntityType.UPI_ID,
)


def test_synthetic_corpus_exact_spans_all_indian_types():
    reg = default_registry()
    counts = dict.fromkeys(TYPES, 0)
    for s in generate(3000, seed=15):
        detected = reg.detect(s.text)
        for t in TYPES:
            gold = {(g.start, g.end) for g in s.spans if g.type == t}
            got = {(e.start, e.end) for e in detected if e.type == t}
            assert got == gold, (t, s.text)
            counts[t] += len(gold)
        for d in s.decoys:
            assert not any(e.start < d.end and d.start < e.end for e in detected), s.text
    assert all(n > 100 for n in counts.values()), counts
