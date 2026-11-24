"""Aadhaar recognizer: forms, checksum, boundaries, and exact spans on the synthetic corpus."""

import pytest

from shoji.detect import EntityType, default_registry, detect
from shoji.detect.checksums import verhoeff_check_digit
from shoji.detect.recognizers import AadhaarRecognizer
from shoji.synthetic import generate

R = AadhaarRecognizer()


def valid(payload11: str) -> str:
    return payload11 + verhoeff_check_digit(payload11)


def invalid(payload11: str) -> str:
    good = verhoeff_check_digit(payload11)
    return payload11 + str((int(good) + 1) % 10)


A = valid("23456789012")  # a fixed valid Aadhaar-shaped number
A_SPACED = f"{A[:4]} {A[4:8]} {A[8:]}"
A_HYPHEN = f"{A[:4]}-{A[4:8]}-{A[8:]}"


def found(text):
    return [(e.text, e.start, e.end) for e in R.analyze(text)]


@pytest.mark.parametrize("value", [A, A_SPACED, A_HYPHEN])
def test_finds_each_form_with_exact_span(value):
    text = f"My Aadhaar is {value}, thanks."
    start = text.index(value)
    assert found(text) == [(value, start, start + len(value))]
    (e,) = R.analyze(text)
    assert e.type == EntityType.AADHAAR and e.score == AadhaarRecognizer.SCORE


@pytest.mark.parametrize("value", [A, A_SPACED])
def test_at_start_and_end_of_text(value):
    assert found(value) == [(value, 0, len(value))]


def test_rejects_failed_checksum():
    bad = invalid("23456789012")
    assert found(f"order {bad}") == []
    assert found(f"order {bad[:4]} {bad[4:8]} {bad[8:]}") == []


@pytest.mark.parametrize("first", "01")
def test_rejects_first_digit_0_or_1(first):
    assert found(valid(first + "3456789012")) == []


@pytest.mark.parametrize(
    "text",
    [
        "card 4" + A + "000",  # inside a longer plain run
        "1" + A,
        A + "7",
        f"card 4111 {A_SPACED}",  # tail of a grouped sequence
        f"card {A_SPACED} 4111",  # head of a grouped sequence
        f"ref 4111-{A_HYPHEN}",
        f"ORD{A}",  # glued to letters
        f"{A}xyz",
        f"+{A}",  # "+" prefix: an international phone, not an Aadhaar
        f"{A[:4]} {A[4:8]}-{A[8:]}",  # mixed separators
        f"{A[:4]}  {A[4:8]}  {A[8:]}",  # double spaces
        "XXXX XXXX " + A[8:],  # masked: out of scope
        A.translate(str.maketrans("0123456789", "०१२३४५६७८९")),  # Devanagari digits
    ],
)
def test_not_matched(text):
    assert found(text) == []


def test_card_number_containing_a_valid_aadhaar_is_not_matched():
    # Find a Luhn-valid card whose middle 12 digits also pass Verhoeff.
    from shoji.detect.checksums import luhn_check_digit, verhoeff_valid

    for n in range(10_000):
        payload = f"41{2_000_000_000_000 + n}"  # digits 3-14 start with 2
        card = payload + luhn_check_digit(payload)
        if card[2] in "23456789" and verhoeff_valid(card[2:14]):
            break
    assert verhoeff_valid(card[2:14]), "no suitable card found"
    grouped = " ".join(card[i : i + 4] for i in range(0, 16, 4))
    assert found(f"card {card} please") == []
    assert found(f"card {grouped} please") == []


def test_offsets_after_devanagari_and_emoji():
    prefix = "आधार नंबर 🙏🏽 "
    text = prefix + A_SPACED + " है"
    assert found(text) == [(A_SPACED, len(prefix), len(prefix) + len(A_SPACED))]


@pytest.mark.parametrize(
    ("text", "count"),
    [(f"({A})", 1), (f"Aadhaar:{A}.", 1), (f"'{A_SPACED}'", 1), (f"{A},{valid('98765432101')}", 2)],
)
def test_punctuation_boundaries(text, count):
    assert len(found(text)) == count


def test_91_plus_mobile_gets_low_score():
    # "91" + a mobile number, written without "+", is also 12 digits.
    value = valid("91987654321")
    (e,) = R.analyze(f"call {value}")
    assert e.score == AadhaarRecognizer.PHONE_LIKE_SCORE
    # Grouped 4-4-4 is how Aadhaar is written, not phones: normal score.
    (e,) = R.analyze(f"{value[:4]} {value[4:8]} {value[8:]}")
    assert e.score == AadhaarRecognizer.SCORE


def test_registered_by_default():
    assert any(isinstance(r, AadhaarRecognizer) for r in default_registry().recognizers)
    assert [(e.type, e.text) for e in detect(f"Aadhaar {A_SPACED}")] == [
        (EntityType.AADHAAR, A_SPACED)
    ]


# --- Synthetic corpus ---------------------------------------------------------------------------


def test_synthetic_corpus_exact_spans():
    samples = generate(2000, seed=13)
    gold_total = 0
    for s in samples:
        gold = {(g.start, g.end) for g in s.spans if g.type == EntityType.AADHAAR}
        gold_total += len(gold)
        got = {(e.start, e.end): e for e in R.analyze(s.text)}
        assert gold <= got.keys(), s.text  # every Aadhaar found, with its exact span
        for span, e in got.items():
            if span in gold:
                continue
            # The only allowed extra: a "91..." phone that happens to pass Verhoeff,
            # reported with a low score so the phone recognizer wins.
            phones = {(g.start, g.end) for g in s.spans if g.type == EntityType.PHONE}
            assert span in phones and e.score < 0.5, s.text
        for d in s.decoys:  # look-alikes are never reported
            assert (d.start, d.end) not in got, s.text
    assert gold_total > 100  # the corpus actually exercised the recognizer
