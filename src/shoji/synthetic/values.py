"""Seeded generators for fake, format- and checksum-valid personal data (and look-alikes).

Everything is random: no value is taken from a real person. Randomly generated phone,
Aadhaar or card numbers can coincide with numbers that exist, but nothing ties them to
anyone. Emails use reserved ``example`` domains so they cannot reach a real mailbox, and IP
addresses come from private or documentation ranges.
"""

import random
import string
from dataclasses import dataclass

from shoji.detect.checksums import gstin_check_char, luhn_check_digit, verhoeff_check_digit
from shoji.detect.formats import GST_STATE_CODES

# Common given names and surnames from many regions and communities, combined at random.
# ASCII only, since emails and UPI IDs are built from them.
FIRST_NAMES = (
    "Aarav", "Aditi", "Amit", "Ananya", "Arjun", "Deepa", "Divya", "Farhan", "Gaurav",
    "Harpreet", "Ishaan", "Kavya", "Lakshmi", "Manoj", "Meera", "Neha", "Nikhil", "Pooja",
    "Priya", "Rahul", "Rohan", "Sana", "Sandeep", "Sneha", "Suresh", "Tanvi", "Varun",
    "Vikram", "Zoya", "Karthik", "Anjali", "Imran", "Gurpreet", "Swati", "Arnav", "Riya",
    # East
    "Arindam", "Sourav", "Debashree", "Moumita", "Bhaskar", "Pallavi", "Subhajit",
    # South
    "Senthil", "Meenakshi", "Venkatesh", "Sravani", "Anoop", "Sreeja", "Murugan", "Divyashree",
    # West
    "Aniket", "Sayali", "Hardik", "Krupa", "Tejas", "Gauri",
    # North
    "Jaspreet", "Manpreet", "Ankit", "Shalini", "Rajesh", "Sunita",
    # Muslim, Christian and other names common across India
    "Ayesha", "Faizan", "Mohammed", "Nazia", "Joseph", "Maria", "Alwyn", "Lalremruati",
)  # fmt: skip
SURNAMES = (
    "Sharma", "Verma", "Gupta", "Iyer", "Reddy", "Nair", "Patel", "Shah", "Singh", "Kaur",
    "Das", "Banerjee", "Chatterjee", "Mukherjee", "Joshi", "Kulkarni", "Deshpande", "Khan",
    "Ansari", "Menon", "Pillai", "Rao", "Naidu", "Mehta", "Agarwal", "Bose", "Yadav",
    "Mishra", "Pandey", "Fernandes", "Gill", "Chauhan", "Hegde", "Shetty",
    "Ghosh", "Sen", "Dutta", "Bora", "Gogoi", "Subramanian", "Krishnan", "Raman", "Chowdary",
    "Nambiar", "Kurian", "Thomas", "Patil", "Jadhav", "Pawar", "Desai", "Parikh", "Sandhu",
    "Grewal", "Dhillon", "Qureshi", "Siddiqui", "Shaikh", "Pereira", "Tripathi", "Saxena",
)  # fmt: skip

# Devanagari names for Hindi templates.
FIRST_NAMES_HI = (
    "राहुल", "प्रिया", "अमित", "सुनीता", "विकास", "अंजलि", "रमेश", "पूजा", "संजय", "कविता",
    "मोहन", "नेहा", "अरुण", "सीमा",
)  # fmt: skip
SURNAMES_HI = (
    "शर्मा", "वर्मा", "गुप्ता", "सिंह", "यादव", "मिश्रा", "पांडे", "जोशी", "चौहान", "त्रिपाठी",
)  # fmt: skip

HONORIFICS = ("Shri ", "Smt. ", "Dr. ", "Mr. ", "Ms. ", "Prof. ")

# Public geography, not personal data: (city, state, first three PIN digits, localities).
CITIES = (
    ("Mumbai", "Maharashtra", "400", ("Andheri West", "Dadar", "Powai", "Borivali East")),
    ("Pune", "Maharashtra", "411", ("Kothrud", "Baner", "Hadapsar", "Viman Nagar")),
    ("New Delhi", "Delhi", "110", ("Lajpat Nagar", "Dwarka Sector 7", "Rohini", "Saket")),
    ("Bengaluru", "Karnataka", "560", ("Koramangala", "Indiranagar", "Jayanagar", "HSR Layout")),
    ("Chennai", "Tamil Nadu", "600", ("T. Nagar", "Adyar", "Velachery", "Anna Nagar")),
    ("Hyderabad", "Telangana", "500", ("Gachibowli", "Banjara Hills", "Kukatpally")),
    ("Kolkata", "West Bengal", "700", ("Salt Lake", "Behala", "Ballygunge", "Dum Dum")),
    ("Jaipur", "Rajasthan", "302", ("Malviya Nagar", "Vaishali Nagar", "Mansarovar")),
    ("Lucknow", "Uttar Pradesh", "226", ("Gomti Nagar", "Aliganj", "Hazratganj")),
    ("Ahmedabad", "Gujarat", "380", ("Navrangpura", "Satellite", "Maninagar")),
    ("Kochi", "Kerala", "682", ("Kakkanad", "Edappally", "Fort Kochi")),
    ("Chandigarh", "Chandigarh", "160", ("Sector 17", "Sector 35", "Manimajra")),
    ("Bhopal", "Madhya Pradesh", "462", ("Arera Colony", "MP Nagar", "Kolar Road")),
    ("Patna", "Bihar", "800", ("Boring Road", "Kankarbagh", "Rajendra Nagar")),
    ("Guwahati", "Assam", "781", ("Dispur", "Beltola", "Zoo Road")),
)  # fmt: skip
STREETS = (
    "MG Road", "Station Road", "Nehru Marg", "Gandhi Road", "Link Road", "Church Street",
    "2nd Cross, 5th Main", "Ring Road", "Tilak Path", "Park Street", "Lal Bahadur Shastri Marg",
)  # fmt: skip
BUILDINGS = (
    "Shanti Apartments", "Green Park Society", "Sai Krupa Residency", "Lotus Towers",
    "Gokuldham Society", "Sunrise Enclave", "Royal Palms", "Ganga Niwas",
)  # fmt: skip
CITIES_HI = (
    ("जयपुर", "302"),
    ("लखनऊ", "226"),
    ("पटना", "800"),
    ("भोपाल", "462"),
    ("वाराणसी", "221"),
)
STREETS_HI = ("गांधी नगर", "नेहरू मार्ग", "स्टेशन रोड", "शास्त्री नगर", "सिविल लाइंस")

ORG_WORDS = (
    "Sunrise", "Lotus", "Ganga", "Shree Balaji", "Om Sai", "Navkar", "Annapurna", "Silverline",
    "Bluestone", "Kaveri", "Himalaya View", "Saraswati",
)  # fmt: skip
ORG_KINDS = (
    "Traders", "Enterprises", "Textiles", "Technologies", "Logistics", "Pharma", "Foods",
    "Constructions", "Jewellers", "Agencies",
)  # fmt: skip
ORG_SUFFIXES = ("Pvt Ltd", "Private Limited", "LLP", "& Sons", "& Co.", "")

# Words that are also given names but here mean something else. Must not be reported.
NAME_WORDS = ("Rose", "Sunny", "Joy", "Asha", "Kiran", "Suraj")

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

    # --- names, addresses, organisations ----------------------------------------------
    # These return ``(before, value, after)``: only ``value`` is personal data, so an
    # honorific or "-ji" around a name stays outside the gold span.

    def person_name(self, person: Persona) -> tuple[str, str, str]:
        first, last = person.first, person.last
        form = self.rng.choices(
            ["full", "first", "initial", "honorific", "ji"], weights=[50, 15, 10, 18, 7]
        )[0]
        if form == "first":
            return "", first, ""
        if form == "initial":
            return "", f"{first[0]}. {last}", ""
        if form == "honorific":
            return self.rng.choice(HONORIFICS), f"{first} {last}", ""
        if form == "ji":
            return "", self.rng.choice([first, last]), self.rng.choice(["-ji", " ji"])
        return "", f"{first} {last}", ""

    def person_name_hi(self) -> tuple[str, str, str]:
        first, last = self.rng.choice(FIRST_NAMES_HI), self.rng.choice(SURNAMES_HI)
        return "", self.rng.choice([f"{first} {last}", first]), ""

    def pin_code(self, prefix: str) -> str:
        return prefix + self._digits(3)

    def city(self) -> str:
        return self.rng.choice(CITIES)[0]

    def address(self) -> str:
        city, state, prefix, localities = self.rng.choice(CITIES)
        locality = self.rng.choice(localities)
        pin = self.pin_code(prefix)
        unit = self.rng.choice(
            [
                f"Flat {self.rng.randint(1, 15)}0{self.rng.randint(1, 9)}",
                f"House No. {self.rng.randint(1, 450)}",
                f"#{self.rng.randint(1, 99)}",
                f"{self.rng.choice('ABCDE')}-{self.rng.randint(1, 60)}",
                f"Plot {self.rng.randint(1, 300)}",
            ]
        )
        sep = self.rng.choice([" ", " - ", "-"])
        form = self.rng.choices(["full", "street", "short"], weights=[45, 35, 20])[0]
        if form == "full":
            building = self.rng.choice(BUILDINGS)
            return f"{unit}, {building}, {locality}, {city}, {state}{sep}{pin}"
        if form == "street":
            street = self.rng.choice(STREETS)
            return f"{unit}, {street}, {locality}, {city}{sep}{pin}"
        return f"{locality}, {city}{sep}{pin}"

    def address_hi(self) -> str:
        city, prefix = self.rng.choice(CITIES_HI)
        street = self.rng.choice(STREETS_HI)
        return f"मकान नं. {self.rng.randint(1, 300)}, {street}, {city} {self.pin_code(prefix)}"

    def org(self, person: Persona) -> str:
        kind = self.rng.random()
        if kind < 0.4:
            name = f"{person.last} {self.rng.choice(ORG_KINDS)}"
        elif kind < 0.75:
            name = f"{self.rng.choice(ORG_WORDS)} {self.rng.choice(ORG_KINDS)}"
        else:
            city = self.city()
            return self.rng.choice(
                [
                    f"{self.rng.choice(ORG_WORDS)} Hospital",
                    f"{city} Public School",
                    f"{self.rng.choice(ORG_WORDS)} Cooperative Bank",
                    f"{self.rng.choice(ORG_WORDS)} Institute of Technology",
                ]
            )
        suffix = self.rng.choice(ORG_SUFFIXES)
        return f"{name} {suffix}" if suffix else name

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

    def amex_digits(self) -> str:
        payload = self.rng.choice(["34", "37"]) + self._digits(12)
        return payload + luhn_check_digit(payload)

    def card_number(self) -> str:
        sep = self.rng.choices([" ", "", "-"], weights=[6, 3, 1])[0]
        if self.rng.random() < 0.15:  # 15-digit, grouped 4-6-5
            d = self.amex_digits()
            return sep.join((d[:4], d[4:10], d[10:]))
        d = self.card_digits()
        return sep.join(d[i : i + 4] for i in range(0, 16, 4))

    def ip_address(self) -> str:
        """Private or documentation-range addresses only (RFC 1918, 5737, 3849)."""
        r = self.rng.randint
        return self.rng.choice(
            [
                f"192.168.{r(0, 255)}.{r(1, 254)}",
                f"10.{r(0, 255)}.{r(0, 255)}.{r(1, 254)}",
                f"203.0.113.{r(1, 254)}",
                f"198.51.100.{r(1, 254)}",
                f"2001:db8:{r(0, 0xFFFF):x}::{r(1, 0xFFFF):x}",
                f"2001:db8:{r(0, 0xFFFF):x}:{r(0, 0xFFFF):x}:{r(0, 0xFFFF):x}:{r(0, 0xFFFF):x}:"
                f"{r(0, 0xFFFF):x}:{r(1, 0xFFFF):x}",
            ]
        )

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
