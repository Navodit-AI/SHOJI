"""Manual Stage 3 smoke test against a real provider (Groq free tier), synthetic data only.

    python scripts/smoke_redact.py [model]

Starts the proxy in-process, sends one normal and one streaming request containing fake
personal data, and prints three things for each: the prompt the app sent, the body the
provider actually received (captured here by wrapping the upstream send; the proxy itself
never logs content), and the reply the app got back. Needs GROQ_API_KEY in .env. Not run in
CI. Never put real personal data in this script.
"""

import json
import sys
import threading
import time

import httpx
import uvicorn

import shoji.app
from shoji.capture import Capture
from shoji.config import Settings

MODEL = sys.argv[1] if len(sys.argv) > 1 else "openai/gpt-oss-20b"
PORT = 8765
# Synthetic values: a Verhoeff-valid Aadhaar, a Luhn-valid test card, made-up PAN/UPI/phone.
PROMPT = (
    "Write a two-sentence payment reminder for customer PAN ABCPD1234F (Aadhaar 2345 6789 0124). "
    "Ask them to pay via UPI to shop@okaxis or call +91 98765 43210. "
    "Quote the PAN, UPI ID and phone number exactly as written."
)

provider_saw: list[str] = []
real_send = shoji.app.send_with_retry


async def capturing_send(client, request, **kwargs):
    provider_saw.append(json.loads(request.content)["messages"][0]["content"])
    return await real_send(client, request, **kwargs)


shoji.app.send_with_retry = capturing_send


def show(title, text):
    print(f"\n{title}\n  {text}")


def main() -> None:
    records = []
    app = shoji.app.create_app(Settings(), Capture([records.append]))
    server = uvicorn.Server(uvicorn.Config(app, port=PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    url = f"http://127.0.0.1:{PORT}/v1/chat/completions"
    body = {"model": MODEL, "messages": [{"role": "user", "content": PROMPT}]}
    try:
        with httpx.Client(timeout=60) as client:
            print("=== Non-streaming ===")
            resp = client.post(url, json=body)
            resp.raise_for_status()
            show("App sent:", PROMPT)
            show("Provider received:", provider_saw[-1])
            show("App got back:", resp.json()["choices"][0]["message"]["content"])

            print("\n=== Streaming ===")
            parts = []
            with client.stream("POST", url, json={**body, "stream": True}) as stream:
                for line in stream.iter_lines():
                    if line.startswith("data: {"):
                        for choice in json.loads(line[6:]).get("choices", []):
                            parts.append((choice.get("delta") or {}).get("content") or "")
            show("Provider received:", provider_saw[-1])
            show("App got back:", "".join(parts))
    finally:
        server.should_exit = True
        thread.join()

    print("\n=== Request records (what the log keeps) ===")
    for r in records:
        print(" ", json.dumps(r.to_dict()))


if __name__ == "__main__":
    main()
