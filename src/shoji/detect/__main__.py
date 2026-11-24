"""Run the built-in recognizers on some text: ``python -m shoji.detect "text"``.

Reads standard input when no text is given. Runs locally; nothing is sent anywhere.
"""

import argparse
import json
import sys

from shoji.detect import detect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m shoji.detect",
        description="Detect personal data in text with SHOJI's built-in recognizers.",
    )
    parser.add_argument("text", nargs="*", help="text to analyse (default: read stdin)")
    parser.add_argument("--json", action="store_true", help="one JSON object per detection")
    args = parser.parse_args(argv)

    text = " ".join(args.text) if args.text else sys.stdin.read()
    entities = detect(text)

    if args.json:
        for e in entities:
            record = {
                "type": str(e.type),
                "start": e.start,
                "end": e.end,
                "text": e.text,
                "score": e.score,
                "recognizer": e.recognizer,
            }
            print(json.dumps(record, ensure_ascii=False))
        return 0

    if not entities:
        print("No personal data found.")
        return 0
    rows = [
        (str(e.type), f"[{e.start}, {e.end})", f"{e.score:.2f}", e.recognizer, e.text)
        for e in entities
    ]
    header = ("TYPE", "SPAN", "SCORE", "RECOGNIZER", "TEXT")
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(4)]
    for r in [header, *rows]:
        print("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=False)) + "  " + r[4])
    return 0


if __name__ == "__main__":
    sys.exit(main())
