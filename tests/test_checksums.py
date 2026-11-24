"""Check-digit algorithms: published reference vectors plus error-detection properties."""

import random

import pytest

from shoji.detect.checksums import (
    gstin_check_char,
    gstin_valid,
    luhn_check_digit,
    luhn_valid,
    verhoeff_check_digit,
    verhoeff_valid,
)
from shoji.detect.formats import GST_STATE_CODES, PAN_HOLDER_TYPES, upi_psp_handles

# --- Verhoeff ---------------------------------------------------------------------------


@pytest.mark.parametrize(("payload", "check"), [("236", "3"), ("12345", "1")])
def test_verhoeff_reference_vectors(payload, check):
    assert verhoeff_check_digit(payload) == check
    assert verhoeff_valid(payload + check)


def test_verhoeff_catches_every_single_digit_error_and_adjacent_swap():
    rng = random.Random(0)
    for _ in range(200):
        payload = "".join(rng.choice("0123456789") for _ in range(11))
        number = payload + verhoeff_check_digit(payload)
        assert verhoeff_valid(number)
        for i in range(12):
            for d in "0123456789":
                if d != number[i]:
                    assert not verhoeff_valid(number[:i] + d + number[i + 1 :])
        for i in range(11):
            if number[i] != number[i + 1]:
                swapped = number[:i] + number[i + 1] + number[i] + number[i + 2 :]
                assert not verhoeff_valid(swapped)


# --- Luhn -------------------------------------------------------------------------------


def test_luhn_reference_vectors():
    assert luhn_check_digit("7992739871") == "3"
    assert luhn_valid("79927398713")
    assert not luhn_valid("79927398710")
    assert luhn_valid("4111111111111111")  # the well-known Visa test number


def test_luhn_catches_single_digit_errors():
    rng = random.Random(1)
    for _ in range(200):
        payload = "".join(rng.choice("0123456789") for _ in range(15))
        number = payload + luhn_check_digit(payload)
        assert luhn_valid(number)
        i = rng.randrange(16)
        wrong = next(d for d in "0123456789" if d != number[i])
        assert not luhn_valid(number[:i] + wrong + number[i + 1 :])


def test_luhn_single_digit_is_invalid():
    assert not luhn_valid("0")


# --- GSTIN ------------------------------------------------------------------------------


def test_gstin_reference_vector():
    # A widely published sample GSTIN (Maharashtra).
    assert gstin_check_char("27AAPFU0939F1Z") == "V"
    assert gstin_valid("27AAPFU0939F1ZV")
    assert not gstin_valid("27AAPFU0939F1ZW")


@pytest.mark.parametrize("bad", ["", "27AAPFU0939F1Z", "27aapfu0939f1zv", "27AAPFU0939F1ZV0"])
def test_gstin_valid_rejects_wrong_shape(bad):
    assert not gstin_valid(bad)


# --- Input validation ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "func", [verhoeff_check_digit, verhoeff_valid, luhn_check_digit, luhn_valid]
)
@pytest.mark.parametrize("bad", ["", "12 34", "12a4", "१२३४"])  # Devanagari digits are rejected
def test_digit_checks_reject_non_ascii_digits(func, bad):
    with pytest.raises(ValueError):
        func(bad)


def test_gstin_check_char_rejects_bad_payload():
    with pytest.raises(ValueError):
        gstin_check_char("27aapfu0939f1z")


# --- Reference data ---------------------------------------------------------------------


def test_reference_data():
    assert GST_STATE_CODES["27"] == "Maharashtra"
    assert all(len(code) == 2 and code.isdigit() for code in GST_STATE_CODES)
    assert set(PAN_HOLDER_TYPES) == set("PCHFATBLJG")
    handles = upi_psp_handles()
    assert {"okaxis", "ybl", "paytm", "upi"} <= handles
    assert all(h == h.lower() and "." not in h and " " not in h for h in handles)
