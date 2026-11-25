"""Built-in recognizers, run by ``default_registry()`` / ``detect()``."""

from shoji.detect.recognizer import Recognizer
from shoji.detect.recognizers.aadhaar import AadhaarRecognizer
from shoji.detect.recognizers.generic import (
    CardNumberRecognizer,
    IpAddressRecognizer,
    email_recognizer,
)
from shoji.detect.recognizers.phone_upi import IndianPhoneRecognizer, UpiRecognizer
from shoji.detect.recognizers.tax_codes import GstinRecognizer, IfscRecognizer, PanRecognizer


def builtin_recognizers() -> list[Recognizer]:
    """Fresh instances of every built-in recognizer, in registration order."""
    return [
        AadhaarRecognizer(),
        PanRecognizer(),
        GstinRecognizer(),
        IfscRecognizer(),
        IndianPhoneRecognizer(),
        UpiRecognizer(),
        email_recognizer(),
        CardNumberRecognizer(),
        IpAddressRecognizer(),
    ]


__all__ = [
    "AadhaarRecognizer",
    "CardNumberRecognizer",
    "GstinRecognizer",
    "IfscRecognizer",
    "IndianPhoneRecognizer",
    "IpAddressRecognizer",
    "PanRecognizer",
    "UpiRecognizer",
    "builtin_recognizers",
    "email_recognizer",
]
