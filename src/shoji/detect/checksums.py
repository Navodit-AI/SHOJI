"""Check-digit algorithms used by Indian and generic ID formats.

All functions take the bare characters (no spaces or hyphens); callers strip separators.
Non-ASCII digits are rejected explicitly, because ``str.isdigit`` accepts Devanagari digits.
"""

# Verhoeff (used by Aadhaar): dihedral-group multiplication, permutation and inverse tables.
_D = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 2, 3, 4, 0, 6, 7, 8, 9, 5),
    (2, 3, 4, 0, 1, 7, 8, 9, 5, 6),
    (3, 4, 0, 1, 2, 8, 9, 5, 6, 7),
    (4, 0, 1, 2, 3, 9, 5, 6, 7, 8),
    (5, 9, 8, 7, 6, 0, 4, 3, 2, 1),
    (6, 5, 9, 8, 7, 1, 0, 4, 3, 2),
    (7, 6, 5, 9, 8, 2, 1, 0, 4, 3),
    (8, 7, 6, 5, 9, 3, 2, 1, 0, 4),
    (9, 8, 7, 6, 5, 4, 3, 2, 1, 0),
)
_P = (
    (0, 1, 2, 3, 4, 5, 6, 7, 8, 9),
    (1, 5, 7, 6, 2, 8, 3, 0, 9, 4),
    (5, 8, 0, 3, 7, 9, 6, 1, 4, 2),
    (8, 9, 1, 6, 0, 4, 3, 5, 2, 7),
    (9, 4, 5, 3, 1, 2, 6, 8, 7, 0),
    (4, 2, 8, 6, 5, 7, 3, 9, 0, 1),
    (2, 7, 9, 3, 8, 0, 6, 4, 1, 5),
    (7, 0, 4, 6, 9, 1, 3, 2, 5, 8),
)
_INV = (0, 4, 3, 2, 1, 5, 6, 7, 8, 9)


def _digits(number: str) -> list[int]:
    if not number or not (number.isascii() and number.isdigit()):
        raise ValueError(f"expected ASCII digits, got {number!r}")
    return [int(c) for c in number]


def verhoeff_check_digit(payload: str) -> str:
    """The digit to append to ``payload`` so the whole number passes ``verhoeff_valid``."""
    c = 0
    for i, d in enumerate(reversed(_digits(payload))):
        c = _D[c][_P[(i + 1) % 8][d]]
    return str(_INV[c])


def verhoeff_valid(number: str) -> bool:
    c = 0
    for i, d in enumerate(reversed(_digits(number))):
        c = _D[c][_P[i % 8][d]]
    return c == 0


def luhn_check_digit(payload: str) -> str:
    """The digit to append to ``payload`` so the whole number passes ``luhn_valid``."""
    total = 0
    for i, d in enumerate(reversed(_digits(payload))):
        if i % 2 == 0:  # these positions are doubled once the check digit is appended
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return str((10 - total % 10) % 10)


def luhn_valid(number: str) -> bool:
    _digits(number)
    return len(number) > 1 and luhn_check_digit(number[:-1]) == number[-1]


_GSTIN_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def gstin_check_char(payload: str) -> str:
    """Check character for the first 14 characters of a GSTIN (mod-36 weighted sum)."""
    if len(payload) != 14 or any(c not in _GSTIN_CHARS for c in payload):
        raise ValueError(f"expected 14 uppercase alphanumerics, got {payload!r}")
    total = 0
    for i, c in enumerate(payload):
        product = _GSTIN_CHARS.index(c) * (2 if i % 2 else 1)
        total += product // 36 + product % 36
    return _GSTIN_CHARS[(36 - total % 36) % 36]


def gstin_valid(gstin: str) -> bool:
    if len(gstin) != 15 or any(c not in _GSTIN_CHARS for c in gstin):
        return False
    return gstin_check_char(gstin[:14]) == gstin[14]
