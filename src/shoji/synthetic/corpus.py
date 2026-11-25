"""Sentence templates that embed generated values and record their exact spans as ground truth."""

import random
import re
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass

from shoji.detect.entity import EntityType
from shoji.synthetic.values import Persona, ValueFactory


@dataclass(frozen=True, slots=True)
class GoldSpan:
    """A ground-truth span: ``text[start:end] == span.text`` (code-point offsets).

    The span covers the value as written, including separators and prefixes
    (``+91 98765 43210``, ``2345 6789 0123``), but not surrounding words.
    """

    type: str
    start: int
    end: int
    text: str


@dataclass(frozen=True, slots=True)
class Sample:
    text: str
    spans: tuple[GoldSpan, ...]  # personal data a detector should find
    decoys: tuple[GoldSpan, ...]  # look-alikes a detector must NOT report
    lang: str  # "en", "hinglish" (Latin-script Hindi-English) or "hi" (Devanagari)
    template_id: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class Template:
    id: str
    lang: str
    text: str  # slots like {PHONE}; see SLOTS


# Look-alike slot names. Their spans are recorded as decoys, never as personal data.
ORDER_ID = "ORDER_ID"
NON_MOBILE = "NON_MOBILE"
NON_CARD = "NON_CARD"
DECOY_TYPES = frozenset({ORDER_ID, NON_MOBILE, NON_CARD})

_Fill = Callable[[ValueFactory, Persona], str]

SLOTS: dict[str, _Fill] = {
    EntityType.AADHAAR: lambda f, p: f.aadhaar(),
    EntityType.PAN: lambda f, p: f.pan(surname=p.last),
    EntityType.GSTIN: lambda f, p: f.gstin(),
    EntityType.IFSC: lambda f, p: f.ifsc(),
    EntityType.UPI_ID: lambda f, p: f.upi_id(p),
    EntityType.PHONE: lambda f, p: f.phone(),
    EntityType.EMAIL: lambda f, p: f.email(p),
    EntityType.CARD_NUMBER: lambda f, p: f.card_number(),
    EntityType.PERSON: lambda f, p: p.full_name,
    EntityType.IP_ADDRESS: lambda f, p: f.ip_address(),
    ORDER_ID: lambda f, p: f.order_id(),
    NON_MOBILE: lambda f, p: f.non_mobile_number(),
    NON_CARD: lambda f, p: f.non_card_number(),
}

TEMPLATES: tuple[Template, ...] = (
    # English
    Template("kyc", "en", "Please update my KYC. My Aadhaar number is {AADHAAR} and PAN is {PAN}."),
    Template(
        "loan_reminder",
        "en",
        "Write a polite reminder to {PERSON}, phone {PHONE}, PAN {PAN}, about the overdue loan.",
    ),
    Template(
        "refund_upi", "en", "Refund the amount to my UPI ID {UPI_ID}. Registered mobile: {PHONE}."
    ),
    Template(
        "neft",
        "en",
        "Transfer the deposit to {PERSON}'s account at IFSC {IFSC}; confirm on {EMAIL}.",
    ),
    Template(
        "vendor_gst",
        "en",
        "Vendor {PERSON} (GSTIN {GSTIN}) has not been paid yet. Email them at {EMAIL}.",
    ),
    Template(
        "card_dispute",
        "en",
        "I want to dispute a charge on my card {CARD_NUMBER}. Call me on {PHONE}.",
    ),
    Template("contact", "en", "Summarize this contact: {PERSON}, {EMAIL}, {PHONE}."),
    Template("aadhaar_check", "en", "Is {AADHAAR} a valid Aadhaar number format?"),
    Template(
        "invoice_upi",
        "en",
        "Draft an invoice for {PERSON}, GSTIN {GSTIN}, payable by UPI to {UPI_ID}.",
    ),
    Template(
        "support_ticket",
        "en",
        "Customer {PERSON} reported a failed payment on card {CARD_NUMBER}. "
        "Reach them at {EMAIL} or {PHONE}.",
    ),
    Template("ifsc_lookup", "en", "Which bank branch does IFSC {IFSC} belong to?"),
    Template("pan_link", "en", "How do I link PAN {PAN} with Aadhaar {AADHAAR}?"),
    Template("two_phones", "en", "Primary contact {PHONE}, alternate {PHONE}."),
    Template("resume", "en", "Rewrite this resume header: {PERSON} | {EMAIL} | {PHONE}"),
    # Hinglish (Latin script)
    Template(
        "hi_aadhaar", "hinglish", "Bhai mera Aadhaar {AADHAAR} hai, isko form mein daal dena."
    ),
    Template(
        "hi_upi",
        "hinglish",
        "Paise {UPI_ID} pe bhej do, aur screenshot {PHONE} pe WhatsApp kar dena.",
    ),
    Template("hi_call", "hinglish", "Mera number {PHONE} hai, kal subah call karna please."),
    Template("hi_pan", "hinglish", "{PERSON} ka PAN {PAN} hai, ITR file karna hai."),
    Template("hi_gst", "hinglish", "Supplier ka GSTIN {GSTIN} hai, bill pe galat print ho gaya."),
    Template("hi_bank", "hinglish", "Account IFSC {IFSC} wala hai, {PERSON} ke naam pe."),
    Template("hi_email", "hinglish", "Mujhe {EMAIL} pe details bhej do yaar."),
    Template(
        "hi_card", "hinglish", "Card {CARD_NUMBER} se double payment kat gaya, refund kab aayega?"
    ),
    # Devanagari, to exercise non-ASCII offsets
    Template("dev_phone", "hi", "मेरा नंबर {PHONE} है, कल फ़ोन करना।"),
    Template("dev_aadhaar", "hi", "आधार नंबर {AADHAAR} है 🙏"),
    # Personal data next to look-alikes
    Template("order_and_phone", "en", "Order ID {ORDER_ID} has not arrived. Call me on {PHONE}."),
    Template(
        "tracking_and_email",
        "en",
        "Tracking number {NON_MOBILE} shows delivered, but nothing came. Email {EMAIL}.",
    ),
    Template("hi_order_upi", "hinglish", "Order {ORDER_ID} ka refund {UPI_ID} pe chahiye."),
    Template(
        "txn_and_card",
        "en",
        "Transaction reference {NON_CARD} failed, so please charge card {CARD_NUMBER} instead.",
    ),
    # Negatives: look-alikes only, or no personal data at all
    Template("neg_order", "en", "My order {ORDER_ID} was placed on 12/03/2026 for Rs 4,999."),
    Template("neg_tracking", "en", "Courier tracking number {NON_MOBILE}, expected in 3-5 days."),
    Template("neg_txn", "en", "Transaction reference {NON_CARD} failed at 10:42 AM."),
    Template(
        "neg_invoice",
        "en",
        "Invoice {NON_MOBILE} totals Rs 1,23,456 including 18% GST, order {ORDER_ID}.",
    ),
    Template(
        "neg_hi_order", "hinglish", "Order number {ORDER_ID} abhi tak ship nahi hua, kya scene hai?"
    ),
    Template("ip_ssh", "en", "Server {IP_ADDRESS} refuses SSH from my laptop; how do I debug it?"),
    Template(
        "hi_ip", "hinglish", "Mera router ka IP {IP_ADDRESS} hai, port forwarding kaise karu?"
    ),
    Template("neg_version", "en", "Upgrade from version 2.14.3 to 3.0.1 before 2026-12-01."),
    Template("neg_plain", "en", "Explain the difference between a PAN card and an Aadhaar card."),
    Template("neg_hi_plain", "hinglish", "UPI se payment karna safe hai kya? Thoda explain karo."),
)

_SLOT = re.compile(r"\{([A-Z_]+)\}")


def render(template: Template, factory: ValueFactory) -> Sample:
    """Fill every slot in ``template`` and record where each value landed."""
    person = factory.persona()
    parts: list[str] = []
    length = 0
    spans: list[GoldSpan] = []
    decoys: list[GoldSpan] = []
    last = 0
    for m in _SLOT.finditer(template.text):
        literal = template.text[last : m.start()]
        parts.append(literal)
        length += len(literal)
        slot = m.group(1)
        if slot not in SLOTS:
            raise KeyError(f"template {template.id!r} has unknown slot {{{slot}}}")
        value = SLOTS[slot](factory, person)
        span = GoldSpan(slot, length, length + len(value), value)
        (decoys if slot in DECOY_TYPES else spans).append(span)
        parts.append(value)
        length += len(value)
        last = m.end()
    parts.append(template.text[last:])
    return Sample("".join(parts), tuple(spans), tuple(decoys), template.lang, template.id)


class SyntheticCorpus:
    """A reproducible stream of samples: the same seed always gives the same samples.

    Templates are used in a shuffled round-robin, so any ``len(TEMPLATES)`` consecutive
    samples cover every template once.
    """

    def __init__(self, seed: int = 0, templates: tuple[Template, ...] = TEMPLATES) -> None:
        self._rng = random.Random(seed)
        self._factory = ValueFactory(self._rng)
        self._templates = templates

    def __iter__(self) -> Iterator[Sample]:
        while True:
            order = list(self._templates)
            self._rng.shuffle(order)
            for t in order:
                yield render(t, self._factory)

    def samples(self, n: int) -> list[Sample]:
        it = iter(self)
        return [next(it) for _ in range(n)]


def generate(n: int, seed: int = 0) -> list[Sample]:
    return SyntheticCorpus(seed).samples(n)
