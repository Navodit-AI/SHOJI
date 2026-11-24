"""Generic formats: email addresses, payment card numbers and IP addresses."""

import ipaddress
import re
from collections.abc import Iterator

from shoji.detect.checksums import luhn_valid
from shoji.detect.entity import Entity, EntityType
from shoji.detect.recognizer import PatternRecognizer, Recognizer

# --- Email ------------------------------------------------------------------------------------
# Pragmatic, not RFC 5322: a local part, "@", and a domain with at least one dot and a
# letters-only top-level domain. A trailing sentence period is not part of the match.
_EMAIL = re.compile(
    r"(?<![A-Za-z0-9._%+@-])"
    r"(?P<value>[A-Za-z0-9][A-Za-z0-9._%+-]{0,63}@"  # local part
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+"  # domain labels
    r"[A-Za-z]{2,24})"  # top-level domain
    r"(?![A-Za-z0-9@_-])"
)


def email_recognizer() -> PatternRecognizer:
    return PatternRecognizer("email", EntityType.EMAIL, _EMAIL, score=0.9)


# --- Payment cards ----------------------------------------------------------------------------
# 13-19 digits, plain or grouped with one separator kind: 4-4-4-4(-1..3), 4-4-4-1..4, 4-6-5
# (Amex) or 4-6-4 (Diners). The Luhn check digit must be valid.
_CARD = re.compile(
    r"(?<![0-9A-Za-z+])"
    r"(?<![0-9][ -])"  # not the tail of a grouped digit sequence
    r"(?P<value>"
    r"[0-9]{13,19}"
    r"|[0-9]{4}(?P<s1>[ -])[0-9]{4}(?P=s1)[0-9]{4}(?P=s1)[0-9]{1,4}(?:(?P=s1)[0-9]{1,3})?"
    r"|[0-9]{4}(?P<s2>[ -])[0-9]{6}(?P=s2)[0-9]{4,5}"
    r")"
    r"(?![0-9A-Za-z])"
    r"(?![ -][0-9])"  # not the head of a grouped digit sequence
)


class CardNumberRecognizer(Recognizer):
    """Luhn-valid card numbers. Grouped numbers score higher: one random 16-digit number in
    ten passes Luhn, but long digit runs written in card groups are rarely anything else."""

    name = "card"
    entity_types = frozenset({EntityType.CARD_NUMBER})

    GROUPED_SCORE = 0.9
    PLAIN_SCORE = 0.8

    def analyze(self, text: str) -> Iterator[Entity]:
        for m in _CARD.finditer(text):
            value = m.group("value")
            digits = value.replace(" ", "").replace("-", "")
            if not 13 <= len(digits) <= 19 or not luhn_valid(digits):
                continue
            score = self.PLAIN_SCORE if digits == value else self.GROUPED_SCORE
            start, end = m.span("value")
            yield Entity(EntityType.CARD_NUMBER, start, end, value, score, self.name)


# --- IP addresses -----------------------------------------------------------------------------
_OCTET = r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])"
_IPV4 = re.compile(
    r"(?<![0-9A-Za-z.])"
    rf"(?P<value>{_OCTET}(?:\.{_OCTET}){{3}})"
    r"(?![0-9A-Za-z]|\.[0-9])"  # "1.2.3.4.5" is not an address; a sentence period is fine
)
# Candidate IPv6 tokens; ``ipaddress`` decides. Requiring three or more hex groups skips
# times like 10:42 and bare "::".
_IPV6 = re.compile(
    r"(?<![0-9A-Za-z:.])"
    r"(?P<value>[0-9A-Fa-f]{0,4}(?::[0-9A-Fa-f]{0,4}){2,7})"
    r"(?![0-9A-Za-z:])"
)


class IpAddressRecognizer(Recognizer):
    """IPv4 dotted quads and IPv6 addresses (no zone ids or embedded IPv4)."""

    name = "ip_address"
    entity_types = frozenset({EntityType.IP_ADDRESS})

    IPV4_SCORE = 0.75  # four-part version numbers ("1.2.3.4") look the same
    IPV6_SCORE = 0.9

    def analyze(self, text: str) -> Iterator[Entity]:
        for m in _IPV4.finditer(text):
            start, end = m.span("value")
            yield Entity(
                EntityType.IP_ADDRESS, start, end, m.group("value"), self.IPV4_SCORE, self.name
            )
        for m in _IPV6.finditer(text):
            value = m.group("value")
            if sum(1 for g in value.split(":") if g) < 3:
                continue
            try:
                ipaddress.IPv6Address(value)
            except ValueError:
                continue
            start, end = m.span("value")
            yield Entity(EntityType.IP_ADDRESS, start, end, value, self.IPV6_SCORE, self.name)
