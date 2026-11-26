"""The NER recognizer, with a fake backend; one real-model test runs only locally."""

import subprocess
import sys

import pytest

from shoji.detect import EntityType, Registry
from shoji.detect.ml import GlinerBackend, NerRecognizer, RawSpan, windows


class FakeBackend:
    """Finds fixed phrases; records every call so windowing can be checked."""

    def __init__(self, phrases, score=0.9):
        self.phrases = phrases  # {phrase: label}
        self.score = score
        self.calls = []

    def predict(self, text, labels, threshold):
        self.calls.append((text, tuple(labels), threshold))
        out = []
        for phrase, label in self.phrases.items():
            start = text.find(phrase)
            while start != -1:
                score = self.score[phrase] if isinstance(self.score, dict) else self.score
                if score >= threshold:
                    out.append(RawSpan(start, start + len(phrase), label, score))
                start = text.find(phrase, start + 1)
        return out


def run(recognizer, text):
    return [(e.type, e.text, e.start) for e in recognizer.analyze(text)]


def test_labels_map_to_entity_types():
    backend = FakeBackend({"Neha Sen": "person", "Sharma Traders": "organization"})
    r = NerRecognizer(backend)
    text = "Neha Sen works at Sharma Traders."
    assert run(r, text) == [
        (EntityType.PERSON, "Neha Sen", 0),
        (EntityType.ORG, "Sharma Traders", 18),
    ]
    assert backend.calls[0][1] == ("person", "address", "organization")
    assert r.entity_types == {EntityType.PERSON, EntityType.ADDRESS, EntityType.ORG}


def test_unknown_labels_ignored():
    r = NerRecognizer(FakeBackend({"Pune": "city"}))
    assert run(r, "office in Pune") == []


def test_per_type_thresholds():
    backend = FakeBackend({"Rahul": "person", "Acme Ltd": "organization"},
                          score={"Rahul": 0.6, "Acme Ltd": 0.6})  # fmt: skip
    r = NerRecognizer(backend, thresholds={EntityType.PERSON: 0.5, EntityType.ORG: 0.7})
    assert run(r, "Rahul at Acme Ltd") == [(EntityType.PERSON, "Rahul", 0)]
    assert backend.calls[0][2] == 0.5  # the backend gets the lowest threshold


def test_address_pieces_are_joined():
    text = "Ship to Flat 12, MG Road, Kothrud, Pune - 411038 today."
    pieces = {"Flat 12": "address", "MG Road": "address", "Kothrud": "address",
              "Pune": "address", "411038": "address"}  # fmt: skip
    backend = FakeBackend(pieces, score={"Flat 12": 0.95, "MG Road": 0.9, "Kothrud": 0.8,
                                         "Pune": 0.7, "411038": 0.85})  # fmt: skip
    (e,) = NerRecognizer(backend).analyze(text)
    assert (e.type, e.text, e.score) == (
        EntityType.ADDRESS,
        "Flat 12, MG Road, Kothrud, Pune - 411038",
        0.7,
    )


def test_only_join_types_are_joined():
    backend = FakeBackend({"Rahul": "person", "Sharma": "person"})
    assert len(list(NerRecognizer(backend).analyze("Rahul, Sharma"))) == 2


def test_pieces_with_words_between_are_not_joined():
    backend = FakeBackend({"MG Road": "address", "Pune": "address"})
    assert len(list(NerRecognizer(backend).analyze("MG Road and then Pune"))) == 2


def test_span_edges_are_trimmed():
    class Sloppy:
        def predict(self, text, labels, threshold):
            return [RawSpan(text.index(" Neha"), text.index(",") + 1, "person", 0.9)]

    (e,) = NerRecognizer(Sloppy()).analyze("Hi Neha Sen, welcome")
    assert e.text == "Neha Sen"


def test_out_of_range_span_rejected():
    class Broken:
        def predict(self, text, labels, threshold):
            return [RawSpan(0, len(text) + 5, "person", 0.9)]

    with pytest.raises(ValueError, match="outside its text"):
        list(NerRecognizer(Broken()).analyze("Neha"))


def test_unicode_offsets():
    text = "नमस्ते 🙏 अमित वर्मा जी, Neha Sen 🙂"
    r = NerRecognizer(FakeBackend({"अमित वर्मा": "person", "Neha Sen": "person"}))
    found = list(r.analyze(text))
    assert [text[e.start : e.end] for e in found] == ["अमित वर्मा", "Neha Sen"]


# --- Windowing ----------------------------------------------------------------------------------


def test_windows_cover_text_with_overlap():
    text = " ".join(f"w{i}" for i in range(25))
    spans = list(windows(text, max_words=10, overlap=3))
    words = [text[a:b].split() for a, b in spans]
    assert words[0][0] == "w0" and words[-1][-1] == "w24"
    for left, right in zip(words, words[1:], strict=False):
        assert left[-3:] == right[:3]
    assert all(len(w) <= 10 for w in words)


def test_windows_edge_cases():
    assert list(windows("", 10, 2)) == []
    assert list(windows("   ", 10, 2)) == []
    assert list(windows("one two", 10, 2)) == [(0, 7)]
    with pytest.raises(ValueError):
        list(windows("a b", 5, 5))


def test_entity_cut_by_a_window_edge_is_found_once():
    filler = " ".join(f"word{i}" for i in range(9))
    text = f"{filler} Neha Sen {filler}"  # "Neha" is word 10, "Sen" word 11
    backend = FakeBackend({"Neha Sen": "person"})
    found = list(NerRecognizer(backend, max_words=10, overlap=4).analyze(text))
    assert [(e.text, text[e.start : e.end]) for e in found] == [("Neha Sen", "Neha Sen")]
    assert len(backend.calls) > 1


def test_registry_resolves_ner_with_rules():
    from shoji.detect.recognizers import builtin_recognizers

    backend = FakeBackend({"Neha Sen": "person"})
    registry = Registry([*builtin_recognizers(), NerRecognizer(backend)])
    found = [(e.type, e.text) for e in registry.detect("Neha Sen, PAN ABCPD1234F")]
    assert found == [(EntityType.PERSON, "Neha Sen"), (EntityType.PAN, "ABCPD1234F")]


# --- Optional dependency ------------------------------------------------------------------------


def test_importing_shoji_does_not_import_torch():
    code = "import sys, shoji.detect, shoji.detect.ml, shoji.app; print('torch' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True)
    assert out.stdout.strip() == "False"


def test_missing_gliner_gives_install_hint(monkeypatch):
    monkeypatch.setitem(sys.modules, "gliner", None)  # makes "import gliner" fail
    with pytest.raises(RuntimeError, match=r"pip install -e \"\.\[ml\]\""):
        GlinerBackend().warm_up()


# --- Real model (local only) --------------------------------------------------------------------


@pytest.mark.model
def test_real_model_on_synthetic_sentences():
    r = NerRecognizer(GlinerBackend())
    found = {
        (e.type, e.text) for e in r.analyze("Aarav Dutta ne Dutta Pharma & Co. join kiya hai.")
    }
    assert (EntityType.PERSON, "Aarav Dutta") in found
    assert (EntityType.ORG, "Dutta Pharma & Co.") in found
    text = "Please ship the order to Neha Sen, Flat 1302, Tilak Path, Fort Kochi, Kochi 682887."
    types = {e.type for e in r.analyze(text)}
    assert {EntityType.PERSON, EntityType.ADDRESS} <= types
