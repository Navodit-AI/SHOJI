"""Email, card and IP recognizers; metrics; the per-entity precision/recall regression check."""

import pytest

from shoji.detect import NER_TYPES, EntityType, default_registry, detect
from shoji.detect.checksums import luhn_check_digit
from shoji.detect.metrics import TypeScore, evaluate, format_report, score_spans
from shoji.detect.recognizers import CardNumberRecognizer, IpAddressRecognizer, email_recognizer
from shoji.synthetic import generate

EMAIL, CARD, IP = email_recognizer(), CardNumberRecognizer(), IpAddressRecognizer()


def found(recognizer, text):
    return [e.text for e in recognizer.analyze(text)]


# --- Email ---------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "rahul@example.com",
        "rahul.sharma+news@mail.example.co.in",
        "a_b-c%d@sub-domain.example.org",
        "Priya.Nair@Example.IN",
    ],
)
def test_email(value):
    text = f"Mail ({value}) or {value}."
    assert found(EMAIL, text) == [value, value]


@pytest.mark.parametrize(
    "text",
    [
        "rahul@ybl",  # UPI, no domain dot
        "rahul@localhost",
        "@example.com",
        "rahul@example.c",  # TLD too short
        "rahul@-example.com",
        "rahul@example.com1",
        "x@y@example.com",
    ],
)
def test_email_not_matched(text):
    assert found(EMAIL, text) == []


# --- Card numbers ---------------------------------------------------------------------------


def luhn(payload):
    return payload + luhn_check_digit(payload)


VISA = "4111111111111111"
AMEX = luhn("37828224631000")  # 15 digits


@pytest.mark.parametrize(
    ("value", "score"),
    [
        (VISA, CardNumberRecognizer.PLAIN_SCORE),
        ("4111 1111 1111 1111", CardNumberRecognizer.GROUPED_SCORE),
        ("4111-1111-1111-1111", CardNumberRecognizer.GROUPED_SCORE),
        (f"{AMEX[:4]} {AMEX[4:10]} {AMEX[10:]}", CardNumberRecognizer.GROUPED_SCORE),
        (luhn("4" * 12), CardNumberRecognizer.PLAIN_SCORE),  # 13 digits
        (luhn("6" * 18), CardNumberRecognizer.PLAIN_SCORE),  # 19 digits
        (" ".join([*[luhn("6" * 18)[i : i + 4] for i in range(0, 16, 4)], luhn("6" * 18)[16:]]),
         CardNumberRecognizer.GROUPED_SCORE),  # 4-4-4-4-3
    ],
)  # fmt: skip
def test_card_formats(value, score):
    text = f"card {value}, thanks"
    (e,) = CARD.analyze(text)
    assert (e.text, e.start, e.score) == (value, 5, score)


@pytest.mark.parametrize(
    "text",
    [
        "4111111111111112",  # fails Luhn
        "4111 1111 1111 1112",
        luhn("4" * 11),  # 12 digits: too short
        luhn("4" * 19),  # 20 digits: too long
        "4111 1111-1111 1111",  # mixed separators
        "4111 1111 1111 1111 1234 5",  # part of a longer grouped run
        "ID4111111111111111",
        "+4111111111111111",
    ],
)
def test_card_not_matched(text):
    assert found(CARD, text) == []


def test_card_and_aadhaar_do_not_collide():
    # A 16-digit card is never also reported as an Aadhaar or a phone.
    assert [e.type for e in detect("card 4111 1111 1111 1111")] == [EntityType.CARD_NUMBER]


# --- IP addresses ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "192.168.1.20",
        "10.0.0.1",
        "203.0.113.255",
        "0.0.0.0",
        "2001:db8::1",
        "2001:db8:a:b:c:d:e:f",
        "fe80::1:2",
    ],
)
def test_ip_addresses(value):
    assert found(IP, f"server {value}.") == [value]


@pytest.mark.parametrize(
    "text",
    [
        "256.1.1.1",
        "1.2.3",  # version number
        "2.14.3",
        "1.2.3.4.5",
        "192.168.1.020x",
        "10:42",  # time
        "10:42:07",
        "::",
        "a::b",  # too few groups
        "2001:db8:::1",  # invalid
        "12:34:56:78:90:ab:cd:ef:01",  # 9 groups
    ],
)
def test_ip_not_matched(text):
    assert found(IP, text) == []


def test_ipv4_scored_below_ipv6():
    (v4,) = IP.analyze("1.2.3.4")
    (v6,) = IP.analyze("2001:db8::1")
    assert v4.score < v6.score


# --- Metrics --------------------------------------------------------------------------------


def test_score_spans_exact_match_only():
    gold = {("PAN", 0, 10), ("PHONE", 20, 30)}
    predicted = {("PAN", 0, 10), ("PHONE", 21, 30), ("EMAIL", 40, 50)}
    scores = score_spans([(gold, predicted)])
    assert scores["PAN"] == TypeScore(tp=1)
    assert scores["PHONE"] == TypeScore(fp=1, fn=1)  # off by one = a miss and a false alarm
    assert scores["EMAIL"] == TypeScore(fp=1)
    assert scores["PAN"].f1 == 1.0
    assert scores["PHONE"].precision == scores["PHONE"].recall == 0.0
    assert "PHONE" in format_report(scores)


def test_type_score_zero_division():
    assert TypeScore().precision == TypeScore().recall == TypeScore().f1 == 0.0


# --- Regression check on the synthetic set --------------------------------------------------------


def test_per_entity_precision_recall_on_synthetic_set():
    """Not the Stage 6 headline numbers (this set is generated by us and the rules were
    written for it); a regression guard so a change that breaks any entity type shows up."""
    scores = evaluate(generate(3000, seed=16), default_registry())
    rule_types = set(EntityType) - NER_TYPES  # names, addresses, orgs: ML from Stage 4
    assert rule_types <= scores.keys()
    for t in rule_types:
        s = scores[t]
        assert s.tp >= 50, (t, s)
        assert (s.precision, s.recall) == (1.0, 1.0), f"{t}\n{format_report(scores)}"
