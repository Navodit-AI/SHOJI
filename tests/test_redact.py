"""Placeholders, redact/restore on text and on OpenAI messages."""

import copy

import pytest

from shoji.detect import NER_TYPES, Entity, detect
from shoji.redact import PLACEHOLDER, Mapping, redact, redact_messages, restore, value_key
from shoji.synthetic import generate

PHONE = "+91 98765 43210"
PAN = "ABCPD1234F"
AADHAAR = "2345 6789 0124"
CARD = "4111 1111 1111 1111"


def redacted(text, mapping=None):
    mapping = mapping if mapping is not None else Mapping()
    return redact(text, detect(text), mapping), mapping


# --- Mapping ------------------------------------------------------------------------------------


def test_placeholders_numbered_per_type_in_order():
    m = Mapping()
    assert m.placeholder_for("PHONE", "9876543210") == "<PHONE_1>"
    assert m.placeholder_for("PAN", PAN) == "<PAN_1>"
    assert m.placeholder_for("PHONE", "9123456780") == "<PHONE_2>"
    assert m.placeholder_for("UPI_ID", "a@ybl") == "<UPI_ID_1>"
    assert [p for p, _ in m.items()] == ["<PHONE_1>", "<PAN_1>", "<PHONE_2>", "<UPI_ID_1>"]


@pytest.mark.parametrize(
    ("entity_type", "a", "b"),
    [
        ("PHONE", "98765 43210", "+91-98765-43210"),
        ("PHONE", "098765 43210", "919876543210"),
        ("AADHAAR", "2345 6789 0124", "2345-6789-0124"),
        ("CARD_NUMBER", "4111 1111 1111 1111", "4111111111111111"),
        ("PAN", "abcpd1234f", "ABCPD1234F"),
        ("EMAIL", "Rahul@Example.com", "rahul@example.com"),
        ("UPI_ID", "Rahul@YBL", "rahul@ybl"),
        ("IP_ADDRESS", "2001:db8:0:0::1", "2001:DB8::1"),
        ("PERSON", "Rahul  Sharma", "rahul sharma"),
    ],
)
def test_same_value_different_spelling(entity_type, a, b):
    assert value_key(entity_type, a) == value_key(entity_type, b)
    m = Mapping()
    assert m.placeholder_for(entity_type, a) == m.placeholder_for(entity_type, b)
    assert m.original(m.placeholder_for(entity_type, b)) == a  # first spelling wins


def test_same_value_different_type_gets_different_placeholders():
    m = Mapping()
    assert m.placeholder_for("PHONE", "9876543210") != m.placeholder_for("AADHAAR", "9876543210")


def test_reserved_placeholders_are_skipped():
    m = Mapping()
    m.reserve("I literally typed <PHONE_1> and <PHONE_3>")
    assert m.placeholder_for("PHONE", "9876543210") == "<PHONE_2>"
    assert m.placeholder_for("PHONE", "9123456780") == "<PHONE_4>"


@pytest.mark.parametrize("bad", ["phone", "PHONE-NUMBER", "", "1PHONE"])
def test_bad_type_names_rejected(bad):
    with pytest.raises(ValueError):
        Mapping().placeholder_for(bad, "x")


def test_repr_hides_values():
    m = Mapping()
    m.placeholder_for("PAN", PAN)
    assert PAN not in repr(m) and PAN not in str(m)


# --- redact / restore ---------------------------------------------------------------------------


def test_redact_and_restore():
    text = f"Call Rahul on {PHONE}, PAN {PAN}. Again: {PHONE}."
    out, m = redacted(text)
    assert out == "Call Rahul on <PHONE_1>, PAN <PAN_1>. Again: <PHONE_1>."
    assert restore(out, m) == text


def test_reformatted_value_restores_first_spelling():
    out, m = redacted("Call 98765 43210 or +91-98765-43210")
    assert out == "Call <PHONE_1> or <PHONE_1>"
    assert restore(out, m) == "Call 98765 43210 or 98765 43210"


def test_unknown_placeholders_left_alone():
    out, m = redacted(f"PAN {PAN}")
    assert restore("<PAN_1> <PAN_2> <PHONE_1> <pan_1> <PAN_01>", m) == (
        f"{PAN} <PAN_2> <PHONE_1> <pan_1> <PAN_01>"
    )


def test_typed_placeholder_survives_round_trip():
    text = f"Template uses <PHONE_1>; my real number is {PHONE}."
    out, m = redacted(text)
    assert out == "Template uses <PHONE_1>; my real number is <PHONE_2>."
    assert restore(out, m) == text
    # The model echoing the literal token gets it back unchanged.
    assert restore("Use <PHONE_1> as before.", m) == "Use <PHONE_1> as before."


def test_restore_is_single_pass():
    m = Mapping()
    tricky = m.placeholder_for("PERSON", "<PHONE_1>")  # a value that looks like a placeholder
    m.placeholder_for("PHONE", "9876543210")
    assert restore(tricky, m) == "<PHONE_1>"


def test_unicode_offsets():
    text = f"नमस्ते 🙏 मेरा आधार {AADHAAR} है और फ़ोन {PHONE} 🙂"
    out, m = redacted(text)
    assert out == "नमस्ते 🙏 मेरा आधार <AADHAAR_1> है और फ़ोन <PHONE_1> 🙂"
    assert restore(out, m) == text


def test_no_entities():
    out, m = redacted("nothing personal here")
    assert out == "nothing personal here" and len(m) == 0


def test_overlapping_entities_rejected():
    a = Entity("PHONE", 0, 5, "12345", 0.9, "t")
    b = Entity("PAN", 3, 8, "45678", 0.9, "t")
    with pytest.raises(ValueError, match="overlapping"):
        redact("12345678", [a, b], Mapping())


def test_mismatched_entity_rejected():
    with pytest.raises(ValueError, match="does not match"):
        redact("abcdef", [Entity("PAN", 0, 3, "xyz", 0.9, "t")], Mapping())


def test_round_trip_on_synthetic_set():
    checked = 0
    for s in generate(2000, seed=23):
        entities = detect(s.text)
        keys: dict[tuple[str, str], set[str]] = {}
        for e in entities:
            keys.setdefault((e.type, value_key(e.type, e.text)), set()).add(e.text)
        if any(len(spellings) > 1 for spellings in keys.values()):
            continue  # restore uses the first spelling; covered by its own test
        m = Mapping()
        out = redact(s.text, entities, m)
        assert restore(out, m) == s.text, s.template_id
        for g in s.spans:
            if g.type not in NER_TYPES:  # names, addresses, orgs: ML from Stage 4
                assert g.text not in out, (s.template_id, g)
        checked += 1
    assert checked >= 1900


# --- OpenAI messages ----------------------------------------------------------------------------


def test_redact_messages_all_roles_and_parts():
    messages = [
        {"role": "system", "content": "You are helpful."},
        {"role": "user", "content": f"My PAN is {PAN}."},
        {"role": "assistant", "content": f"Noted, PAN {PAN}."},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": f"Call {PHONE}"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                {"type": "text", "text": f"card {CARD}"},
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": f"Aadhaar {AADHAAR}"},
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1"}]},
    ]
    original = copy.deepcopy(messages)
    result = redact_messages(messages)
    assert messages == original  # input untouched
    out = result.messages
    assert out[0] == messages[0]
    assert out[1]["content"] == "My PAN is <PAN_1>."
    assert out[2]["content"] == "Noted, PAN <PAN_1>."
    assert out[3]["content"][0] == {"type": "text", "text": "Call <PHONE_1>"}
    assert out[3]["content"][1] == messages[3]["content"][1]
    assert out[3]["content"][2]["text"] == "card <CARD_NUMBER_1>"
    assert out[4]["content"] == "Aadhaar <AADHAAR_1>" and out[4]["tool_call_id"] == "c1"
    assert out[5] == messages[5]
    assert result.counts == {"PAN": 2, "PHONE": 1, "CARD_NUMBER": 1, "AADHAAR": 1}


def test_redact_messages_is_deterministic_across_turns():
    turn1 = [{"role": "user", "content": f"PAN {PAN}, phone {PHONE}"}]
    turn2 = [
        *turn1,
        {"role": "assistant", "content": f"Got PAN {PAN}."},
        {"role": "user", "content": "Also phone 91234 56780, and my old one 98765-43210."},
    ]
    r1, r2 = redact_messages(turn1), redact_messages(turn2)
    assert r2.messages[0] == r1.messages[0]
    assert r2.messages[1]["content"] == "Got PAN <PAN_1>."
    assert r2.messages[2]["content"] == "Also phone <PHONE_2>, and my old one <PHONE_1>."


def test_typed_placeholder_in_a_later_message_is_reserved_first():
    messages = [
        {"role": "user", "content": f"phone {PHONE}"},
        {"role": "user", "content": "the form field is called <PHONE_1>"},
    ]
    result = redact_messages(messages)
    assert result.messages[0]["content"] == "phone <PHONE_2>"
    assert result.messages[1]["content"] == "the form field is called <PHONE_1>"


def test_redact_messages_custom_detector_and_mapping():
    m = Mapping()
    m.placeholder_for("PAN", PAN)
    result = redact_messages(
        [{"role": "user", "content": f"{PAN} {PHONE}"}],
        detector=lambda t: [e for e in detect(t) if e.type == "PHONE"],
        mapping=m,
    )
    assert result.mapping is m
    assert result.messages[0]["content"] == f"{PAN} <PHONE_1>"


def test_malformed_messages_pass_through():
    messages = ["not a dict", {"role": "user"}, {"role": "user", "content": 42}]
    assert redact_messages(messages).messages == messages


def test_placeholder_pattern():
    assert PLACEHOLDER.fullmatch("<CARD_NUMBER_12>")
    assert not PLACEHOLDER.fullmatch("<PHONE_0>")
