"""Built-in recognizers. Each Stage 2 issue adds its recognizers to ``builtin_recognizers``."""

from shoji.detect.recognizer import Recognizer
from shoji.detect.recognizers.aadhaar import AadhaarRecognizer
from shoji.detect.recognizers.tax_codes import GstinRecognizer, IfscRecognizer, PanRecognizer


def builtin_recognizers() -> list[Recognizer]:
    """Fresh instances of every built-in recognizer, in registration order."""
    return [AadhaarRecognizer(), PanRecognizer(), GstinRecognizer(), IfscRecognizer()]


__all__ = [
    "AadhaarRecognizer",
    "GstinRecognizer",
    "IfscRecognizer",
    "PanRecognizer",
    "builtin_recognizers",
]
