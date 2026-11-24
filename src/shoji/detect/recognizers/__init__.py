"""Built-in recognizers. Each Stage 2 issue adds its recognizers to ``builtin_recognizers``."""

from shoji.detect.recognizer import Recognizer
from shoji.detect.recognizers.aadhaar import AadhaarRecognizer


def builtin_recognizers() -> list[Recognizer]:
    """Fresh instances of every built-in recognizer, in registration order."""
    return [AadhaarRecognizer()]


__all__ = ["AadhaarRecognizer", "builtin_recognizers"]
