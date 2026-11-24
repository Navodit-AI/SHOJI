"""Seeded generators for fake, format- and checksum-valid personal data (and look-alikes).

Everything is random: no value is taken from a real person. Randomly generated phone,
Aadhaar or card numbers can coincide with numbers that exist, but nothing ties them to
anyone. Emails use reserved ``example`` domains so they cannot reach a real mailbox.
"""

import random
import string
from dataclasses import dataclass

from shoji.detect.checksums import gstin_check_char, luhn_check_digit, verhoeff_check_digit
from shoji.detect.formats import GST_STATE_CODES

FIRST_NAMES = (
    "Aarav", "Aditi", "Amit", "Ananya", "Arjun", "Deepa", "Divya", "Farhan", "Gaurav",
    "Harpreet", "Ishaan", "Kavya", "Lakshmi", "Manoj", "Meera", "Neha", "Nikhil", "Pooja",
    "Priya", "Rahul", "Rohan", "Sana", "Sandeep", "Sneha", "Suresh", "Tanvi", "Varun",
    "Vikram", "Zoya", "Karthik", "Anjali", "Imran", "Gurpreet", "Swati", "Arnav", "Riya",
)  # fmt: skip
SURNAMES = (
    "Sharma", "Verma", "Gupta", "Iyer", "Reddy", "Nair", "Patel", "Shah", "Singh", "Kaur",
    "Das", "Banerjee", "Chatterjee", "Mukherjee", "Joshi", "Kulkarni", "Deshpande", "Khan",
    "Ansari", "Menon", "Pillai", "Rao", "Naidu", "Mehta", "Agarwal", "Bose", "Yadav",
    "Mishra", "Pandey", "Fernandes", "Gill", "Chauhan", "Hegde", "Shetty",
)  # fmt: skip

# Real bank codes (public, not personal); branch codes are random.
IFSC_BANK_CODES = (
    "SBIN", "HDFC", "ICIC", "UTIB", "PUNB", "KKBK", "BARB", "CNRB", "UBIN", "IDIB",
    "IOBA", "YESB", "INDB", "FDRL", "IDFB",
)  # fmt: skip

# A subset of shoji/detect/data/upi_handles.txt, weighted towards the common apps.
UPI_HANDLES = ("okaxis", "okhdfcbank", "okicici", "oksbi", "ybl", "ibl", "axl", "paytm", "upi")

EMAIL_DOMAINS = ("example.com", "example.in", "example.org", "mail.example.co.in")


@dataclass(frozen=True, slots=True)
class Persona:
    """A fake person, so a name, email and UPI ID in one sample can belong together."""

    first: str
    last: str

    @property
    def full_name(self) -> str:
        return f"{self.first} {self.last}"


class ValueFactory:
    """Generates one value at a time from a seeded ``random.Random``."""

    def __init__(self, rng: random.Random) -> None:
        self.rng = rng

    # --- helpers --------------------------------------------------------------------

    def _digits(self, n: int) -> str:
        return "".join(self.rng.choice(string.digits) for _ in range(n))

    def _letters(self, n: int) -> str:
        return "".join(self.rng.choice(string.ascii_uppercase) for _ in range(n))

    def persona(self) -> Persona:
        return Persona(self.rng.choice(FIRST_NAMES), self.rng.choice(SURNAMES))

    # --- valid values ---------------------------------------------------------------

    def aadhaar_digits(self) -> str:
        payload = self.rng.choice("23456789") + self._digits(10)
        return payload + verhoeff_check_digit(payload)

    def aadhaar(self) -> str:
        d = self.aadhaar_digits()
        sep = self.rng.choices([" ", "", "-"], weights=[6, 3, 1])[0]
        return sep.join((d[:4], d[4:8], d[8:]))

    def pan(self, holder: str = "P", surname: str | None = None) -> str:
        # 5th character: first letter of the surname for individuals, of the name otherwise.
        fifth = surname[0].upper() if surname else self._letters(1)
        return (
            self._letters(3)
            + holder
            + fifth
            + f"{self.rng.randint(1, 9999):04d}"
            + (self._letters(1))
        )

    def gstin(self) -> str:
        state = self.rng.choice(list(GST_STATE_CODES))
        pan = self.pan(holder=self.rng.choice("CFP"))
        entity = self.rng.choices(["1", "2", "3"], weights=[8, 1, 1])[0]
        payload = state + pan + entity + "Z"
        return payload + gstin_check_char(payload)

    def ifsc(self) -> str:
        if self.rng.random() < 0.85:
            branch = self._digits(6)
        else:
            branch = "".join(
                self.rng.choice(string.ascii_uppercase + string.digits) for _ in range(6)
            )
        return self.rng.choice(IFSC_BANK_CODES) + "0" + branch

    def upi_id(self, person: Persona | None = None) -> str:
        handle = self.rng.choice(UPI_HANDLES)
        if person is None or self.rng.random() < 0.25:
            return self.mobile_digits() + "@" + handle
        first, last = person.first.lower(), person.last.lower()
        user = self.rng.choice(
            [f"{first}.{last}", f"{first}{last}", f"{first}{self.rng.randint(1, 999)}"]
        )
        return f"{user}@{handle}"

    def mobile_digits(self) -> str:
        return self.rng.choice("6789") + self._digits(9)

    def phone(self) -> str:
        n = self.mobile_digits()
        formats = (
            n,
            f"{n[:5]} {n[5:]}",
            f"{n[:5]}-{n[5:]}",
            f"+91 {n[:5]} {n[5:]}",
            f"+91-{n[:5]}-{n[5:]}",
            f"+91-{n}",
            f"+91{n}",
            f"+91 {n}",
            f"91{n}",
            f"0{n}",
            f"0{n[:5]} {n[5:]}",
        )
        return self.rng.choice(formats)

    def email(self, person: Persona | None = None) -> str:
        person = person or self.persona()
        first, last = person.first.lower(), person.last.lower()
        user = self.rng.choice(
            [f"{first}.{last}", f"{first}{last}{self.rng.randint(1, 99)}", f"{first[0]}{last}"]
        )
        return f"{user}@{self.rng.choice(EMAIL_DOMAINS)}"

    def card_digits(self) -> str:
        prefix = self.rng.choice(["4", "51", "53", "55", "60", "65", "81", "82"])
        payload = prefix + self._digits(15 - len(prefix))
        return payload + luhn_check_digit(payload)

    def card_number(self) -> str:
        d = self.card_digits()
        sep = self.rng.choices([" ", "", "-"], weights=[6, 3, 1])[0]
        return sep.join(d[i : i + 4] for i in range(0, 16, 4))

    # --- look-alikes that must NOT be detected ------------------------------------------

    def order_id(self) -> str:
        """12 digits starting 2-9 (Aadhaar-shaped) whose Verhoeff check digit is wrong.

        Never ``91`` + 6-9: that is also "91" + a mobile number, which a phone detector
        rightly reports, so it would not be a fair look-alike.
        """
        payload = self.rng.choice("23456789") + self._digits(10)
        while payload[:2] == "91" and payload[2] in "6789":
            payload = self.rng.choice("23456789") + self._digits(10)
        good = verhoeff_check_digit(payload)
        return payload + self.rng.choice([d for d in string.digits if d != good])

    def non_mobile_number(self) -> str:
        """10 digits starting 1-5: phone-shaped, but no Indian mobile starts that way."""
        return self.rng.choice("12345") + self._digits(9)

    def non_card_number(self) -> str:
        """16 digits with a card-like prefix whose Luhn check digit is wrong."""
        payload = self.rng.choice(["4", "51", "60"])
        payload += self._digits(15 - len(payload))
        good = luhn_check_digit(payload)
        return payload + self.rng.choice([d for d in string.digits if d != good])
