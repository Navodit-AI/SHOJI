"""The ``python -m shoji.detect`` command."""

import io
import json
import subprocess
import sys

from shoji.detect.__main__ import main

TEXT = "Call +91 98765 43210 or mail rahul@example.com"


def test_table_output(capsys):
    assert main([TEXT]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].split() == ["TYPE", "SPAN", "SCORE", "RECOGNIZER", "TEXT"]
    assert lines[1].split()[0] == "PHONE" and lines[1].endswith("+91 98765 43210")
    assert "[5, 20)" in lines[1]
    assert lines[2].split()[0] == "EMAIL" and lines[2].endswith("rahul@example.com")


def test_json_output(capsys):
    assert main(["--json", TEXT]) == 0
    records = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert records[0] == {
        "type": "PHONE",
        "start": 5,
        "end": 20,
        "text": "+91 98765 43210",
        "score": 0.9,
        "recognizer": "phone_in",
    }
    assert records[1]["type"] == "EMAIL"


def test_words_are_joined(capsys):
    main(["PAN", "ABCPD1234F"])
    assert "ABCPD1234F" in capsys.readouterr().out


def test_nothing_found(capsys):
    assert main(["nothing personal here"]) == 0
    assert capsys.readouterr().out.strip() == "No personal data found."


def test_reads_stdin(capsys, monkeypatch):
    monkeypatch.setattr(sys, "stdin", io.StringIO("आधार 2345 6789 0124 है\n"))
    main([])
    assert "AADHAAR" in capsys.readouterr().out


def test_runs_as_module():
    result = subprocess.run(
        [sys.executable, "-m", "shoji.detect", "--json", "UPI priya@okaxis"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(result.stdout)["type"] == "UPI_ID"
