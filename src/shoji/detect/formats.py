"""Reference data for Indian ID formats, shared by the recognizers and the synthetic generator."""

from functools import cache
from importlib.resources import files

# GST state/UT codes (first two digits of a GSTIN). 25 (Daman and Diu) and 28 (undivided
# Andhra Pradesh) are retired but still appear on older registrations; 97 is "Other Territory".
GST_STATE_CODES: dict[str, str] = {
    "01": "Jammu and Kashmir",
    "02": "Himachal Pradesh",
    "03": "Punjab",
    "04": "Chandigarh",
    "05": "Uttarakhand",
    "06": "Haryana",
    "07": "Delhi",
    "08": "Rajasthan",
    "09": "Uttar Pradesh",
    "10": "Bihar",
    "11": "Sikkim",
    "12": "Arunachal Pradesh",
    "13": "Nagaland",
    "14": "Manipur",
    "15": "Mizoram",
    "16": "Tripura",
    "17": "Meghalaya",
    "18": "Assam",
    "19": "West Bengal",
    "20": "Jharkhand",
    "21": "Odisha",
    "22": "Chhattisgarh",
    "23": "Madhya Pradesh",
    "24": "Gujarat",
    "25": "Daman and Diu",
    "26": "Dadra and Nagar Haveli and Daman and Diu",
    "27": "Maharashtra",
    "28": "Andhra Pradesh (before 2014)",
    "29": "Karnataka",
    "30": "Goa",
    "31": "Lakshadweep",
    "32": "Kerala",
    "33": "Tamil Nadu",
    "34": "Puducherry",
    "35": "Andaman and Nicobar Islands",
    "36": "Telangana",
    "37": "Andhra Pradesh",
    "38": "Ladakh",
    "97": "Other Territory",
}

# 4th character of a PAN: the holder type.
PAN_HOLDER_TYPES: dict[str, str] = {
    "P": "Individual",
    "C": "Company",
    "H": "Hindu Undivided Family",
    "F": "Firm",
    "A": "Association of Persons",
    "T": "Trust",
    "B": "Body of Individuals",
    "L": "Local Authority",
    "J": "Artificial Juridical Person",
    "G": "Government",
}


@cache
def upi_psp_handles() -> frozenset[str]:
    """Known UPI payment-provider handles (the part after ``@``), from ``data/upi_handles.txt``."""
    text = files("shoji.detect").joinpath("data/upi_handles.txt").read_text(encoding="utf-8")
    lines = (line.split("#", 1)[0].strip().lower() for line in text.splitlines())
    return frozenset(line for line in lines if line)
