"""PAN, GSTIN and IFSC recognizers: formats, validation, case policy, GSTIN-vs-PAN overlap."""

import pytest

from shoji.detect import EntityType, Registry, default_registry, detect
from shoji.detect.checksums import gstin_check_char
from shoji.detect.recognizers import GstinRecognizer, IfscRecognizer, PanRecognizer
from shoji.synthetic import generate

PAN, GSTIN, IFSC = PanRecognizer(), GstinRecognizer(), IfscRecognizer()


def found(recognizer, text):
    return [(e.text, e.start, e.end, e.score) for e in recognizer.analyze(text)]


def gstin(state="27", pan="AAPFU0939F", entity="1"):
    payload = f"{state}{pan}{entity}Z"
    return payload + gstin_check_char(payload)


VALID_GSTIN = "27AAPFU0939F1ZV"  # widely published sample


# --- PAN -----------------------------------------------------------------------------------


@pytest.mark.parametrize("holder", list("PCHFATBLJG"))
def test_pan_every_holder_type(holder):
    value = f"ABC{holder}D1234F"
    text = f"PAN: {value}."
    assert found(PAN, text) == [(value, 5, 15, PanRecognizer.upper_score)]


@pytest.mark.parametrize("holder", list("DEIKMNOQRSUVWXYZ"))
def test_pan_rejects_invalid_holder_type(holder):
    assert found(PAN, f"code ABC{holder}D1234F") == []


def test_pan_lowercase_lower_score_mixed_case_rejected():
    assert found(PAN, "pan abcpd1234f hai") == [("abcpd1234f", 4, 14, PanRecognizer.lower_score)]
    assert found(PAN, "pan AbCpD1234f") == []
    assert found(PAN, "pan ABCPD1234f") == []


@pytest.mark.parametrize(
    "text",
    [
        "XABCPD1234F",  # glued to a letter
        "ABCPD1234F9",  # glued to a digit
        "ABCPD12345F",  # too many digits
        "ABCPD123F",
        "ABCP1D234F",
        "ABCPD१२३४F",  # Devanagari digits
        "1ABCPD1234F1Z",  # GSTIN-shaped but wrong length
    ],
)
def test_pan_not_matched(text):
    assert found(PAN, text) == []


def test_pan_offsets_after_non_ascii():
    prefix = "मेरा PAN 🙂 "
    assert found(PAN, prefix + "ABCPD1234F है")[0][1] == len(prefix)


# --- GSTIN ---------------------------------------------------------------------------------


def test_gstin_valid():
    text = f"GSTIN {VALID_GSTIN}, Pune"
    assert found(GSTIN, text) == [(VALID_GSTIN, 6, 21, GstinRecognizer.upper_score)]


def test_gstin_lowercase():
    assert found(GSTIN, VALID_GSTIN.lower()) == [
        (VALID_GSTIN.lower(), 0, 15, GstinRecognizer.lower_score)
    ]


def test_gstin_rejects_wrong_check_character():
    assert found(GSTIN, VALID_GSTIN[:-1] + "W") == []


def test_gstin_rejects_unknown_state_code():
    # The check character is recomputed, so only the state code is wrong.
    assert found(GSTIN, gstin(state="27")) != []
    assert found(GSTIN, gstin(state="99")) == []
    assert found(GSTIN, gstin(state="00")) == []


def test_gstin_rejects_invalid_embedded_pan_and_entity_number():
    assert found(GSTIN, gstin(pan="AAPXU0939F")) == []  # X is not a holder type
    assert found(GSTIN, gstin(entity="0")) == []


@pytest.mark.parametrize("text", ["X" + VALID_GSTIN, VALID_GSTIN + "1", "1" + VALID_GSTIN])
def test_gstin_glued_not_matched(text):
    assert found(GSTIN, text) == []


def test_valid_gstin_reported_once_as_gstin():
    reg = Registry([PanRecognizer(), GstinRecognizer()])
    text = f"Vendor GSTIN {VALID_GSTIN} pending"
    assert len(reg.analyze(text)) == 2  # PAN inside + GSTIN, before resolution
    assert [(e.type, e.text) for e in reg.detect(text)] == [(EntityType.GSTIN, VALID_GSTIN)]


def test_gstin_with_typo_still_leaks_its_pan():
    reg = Registry([PanRecognizer(), GstinRecognizer()])
    bad = VALID_GSTIN[:-1] + "W"
    assert [(e.type, e.text) for e in reg.detect(f"GSTIN {bad}")] == [
        (EntityType.PAN, "AAPFU0939F")
    ]


# --- IFSC ----------------------------------------------------------------------------------


def test_ifsc():
    assert found(IFSC, "IFSC SBIN0001234 please") == [
        ("SBIN0001234", 5, 16, IfscRecognizer.upper_score)
    ]
    assert found(IFSC, "HDFC0ABC123") == [("HDFC0ABC123", 0, 11, IfscRecognizer.upper_score)]
    assert found(IFSC, "sbin0001234") == [("sbin0001234", 0, 11, IfscRecognizer.lower_score)]


@pytest.mark.parametrize(
    "text",
    ["SBIN1001234", "SBI00001234", "SBIN000123", "XSBIN0001234", "SBIN00012345", "SbIn0001234"],
)
def test_ifsc_not_matched(text):
    assert found(IFSC, text) == []


# --- Registry and synthetic corpus ---------------------------------------------------------------


def test_registered_by_default():
    names = {r.name for r in default_registry().recognizers}
    assert {"pan", "gstin", "ifsc"} <= names
    text = f"PAN ABCPD1234F, GSTIN {VALID_GSTIN}, IFSC SBIN0001234"
    assert [e.type for e in detect(text)] == [EntityType.PAN, EntityType.GSTIN, EntityType.IFSC]


TYPES = (EntityType.PAN, EntityType.GSTIN, EntityType.IFSC)


def test_synthetic_corpus_exact_spans():
    counts = dict.fromkeys(TYPES, 0)
    for s in generate(2000, seed=14):
        detected = default_registry().detect(s.text)
        for t in TYPES:
            gold = {(g.start, g.end) for g in s.spans if g.type == t}
            got = {(e.start, e.end) for e in detected if e.type == t}
            assert got == gold, (t, s.text)  # all found, exact spans, nothing extra
            counts[t] += len(gold)
    assert all(n > 100 for n in counts.values()), counts
