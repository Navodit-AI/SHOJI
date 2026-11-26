# SHOJI

A privacy firewall for LLM apps. SHOJI sits between your application and an LLM API,
detects personal data in prompts (with strong coverage of Indian formats such as Aadhaar,
PAN, UPI IDs, IFSC, GSTIN and Indian phone numbers), replaces it with reversible
placeholders before anything leaves the machine, restores the real values in the model's
response, and keeps an audit log.

Integration is a one-line change: point your OpenAI-compatible client's base URL at SHOJI.

> Status: Stages 1–3 of 7 complete: an OpenAI-compatible proxy with streaming, retries and
> request logging; rule-based detection of Indian and generic personal-data formats; and
> reversible redaction, including streamed replies and an optional encrypted vault. Names
> and addresses (ML detection) come in Stage 4.

## Quickstart

Requires Python 3.11+ and a free [Groq API key](https://console.groq.com/keys).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env      # then set GROQ_API_KEY=... in .env
python -m shoji           # serves on http://127.0.0.1:8000
```

Check it is up:

```bash
curl -s localhost:8000/health
# {"status":"ok","provider":"groq"}
```

## Usage

SHOJI exposes `POST /v1/chat/completions` with the same request and response shape as the
OpenAI API. The proxy holds the provider key, so clients do not need one.

**curl, non-streaming**

```bash
curl -s localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "openai/gpt-oss-20b",
       "messages": [{"role": "user", "content": "Say hello in five words."}]}'
```

**curl, streaming** (`-N` turns off curl's buffering so tokens print as they arrive)

```bash
curl -sN localhost:8000/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model": "openai/gpt-oss-20b", "stream": true,
       "messages": [{"role": "user", "content": "Count from 1 to 5."}]}'
# data: {"id":"chatcmpl-...","choices":[{"delta":{"content":"1"}, ...}]}
# ...
# data: [DONE]
```

**OpenAI Python SDK:** only `base_url` changes (`pip install openai`):

```python
from openai import OpenAI

client = OpenAI(base_url="http://localhost:8000/v1", api_key="unused")

reply = client.chat.completions.create(
    model="openai/gpt-oss-20b",
    messages=[{"role": "user", "content": "Name three colours."}],
)
print(reply.choices[0].message.content)

for chunk in client.chat.completions.create(
    model="openai/gpt-oss-20b",
    stream=True,
    messages=[{"role": "user", "content": "Name three fruits."}],
):
    if chunk.choices and chunk.choices[0].delta.content:
        print(chunk.choices[0].delta.content, end="", flush=True)
```

Available model ids depend on the provider; for Groq, see
`curl -s https://api.groq.com/openai/v1/models -H "Authorization: Bearer $GROQ_API_KEY"`.

## Redaction

Every request is redacted before it leaves the machine, and every reply is restored before
your app sees it. Each value gets a placeholder such as `<PHONE_1>`. The same value always
gets the same placeholder, even when it is written differently (`98765 43210` and
`+91-98765-43210`). Live run against Groq (`python scripts/smoke_redact.py`, synthetic
data):

```text
App sent:
  Write a two-sentence payment reminder for customer PAN ABCPD1234F (Aadhaar 2345 6789 0124).
  Ask them to pay via UPI to shop@okaxis or call +91 98765 43210. Quote the PAN, UPI ID and
  phone number exactly as written.

Provider received:
  Write a two-sentence payment reminder for customer PAN <PAN_1> (Aadhaar <AADHAAR_1>).
  Ask them to pay via UPI to <UPI_ID_1> or call <PHONE_1>. Quote the PAN, UPI ID and
  phone number exactly as written.

App got back:
  Dear customer with PAN ABCPD1234F (Aadhaar 2345 6789 0124), please pay the outstanding
  amount via UPI to shop@okaxis. If you have any queries, you can also call +91 98765 43210.
```

(Lines wrapped for the README.) Streaming works the same way: a placeholder cut across two
chunks (`<PHO` + `NE_1>`) is held back only until it is complete, and ordinary text is
never delayed.

All roles are redacted, including earlier assistant turns and `{"type": "text"}` parts.
Images, tool-call arguments and other fields are passed through as they are. Because chat
clients resend the whole history every turn, placeholders stay stable across a conversation
with nothing stored.

**Vault (optional).** If your app trims old messages, set `SHOJI_VAULT_KEY` (generate one
with `python -m shoji.vault`) and send an `X-Shoji-Conversation: <any id>` header. The
conversation's placeholders are then kept in a local SQLite file, values encrypted with
Fernet and looked up by keyed hash, and deleted after `SHOJI_VAULT_TTL_HOURS`. Without a
key, nothing is stored.

**Known limits**

- Only exact placeholder tokens are restored. If a model rewrites one (`<phone_1>`,
  `PHONE_1`), it reaches your app as written.
- The model only sees the placeholder, so it can misread what it stands for. In an
  earlier smoke run, a streamed reply began "Dear ABCPD1234F": the model took `<PAN_1>`
  for a name. Stage 6 measures how much redaction changes answer quality.
- Placeholders in tool-call arguments and reasoning fields are not restored.
- With the vault, if a user types a placeholder that was already issued in that
  conversation (`<PHONE_1>`), it is restored to the real value.
- With the vault, two requests in the same conversation at the same moment can both
  issue a new placeholder under the same number. The vault keeps the first one. Each reply
  is still restored correctly.

## Configuration

All settings are environment variables, usually set in `.env` (see `.env.example`).

| Variable | Default | Meaning |
|---|---|---|
| `SHOJI_PROVIDER` | `groq` | Upstream provider: `groq`, `gemini` or `openrouter` |
| `GROQ_API_KEY` / `GEMINI_API_KEY` / `OPENROUTER_API_KEY` | (none) | Key for the selected provider |
| `SHOJI_DEFAULT_MODEL` | (none) | Model used when a request omits `model` |
| `SHOJI_UPSTREAM_TIMEOUT` | `60` | Seconds to wait for the provider before returning 504 |
| `SHOJI_UPSTREAM_RETRIES` | `1` | Retries on connection failures and 5xx, before any response is sent |
| `SHOJI_RETRY_BACKOFF` | `0.5` | Base delay in seconds between retries |
| `SHOJI_REDACT` | `true` | Redact requests and restore replies; `false` = plain pass-through |
| `SHOJI_MIN_SCORE` | `0.5` | Detections scoring below this are ignored |
| `SHOJI_VAULT_KEY` | (none) | Enables the encrypted vault; `python -m shoji.vault` prints a key |
| `SHOJI_VAULT_PATH` | `shoji_vault.db` | Vault file (created readable by its owner only) |
| `SHOJI_VAULT_TTL_HOURS` | `24` | Conversations unused for this long are deleted |

Switching providers is a config change: set `SHOJI_PROVIDER` and that provider's key.

## Errors

Failures come back in the OpenAI error shape, so SDKs raise their usual exceptions.

| Situation | Response | Retried? |
|---|---|---|
| Provider 4xx (incl. 429 rate limit) | Same status, provider's error | No |
| Provider 5xx | Same status | Once |
| Provider unreachable | 502 `upstream_unavailable` | Once |
| Provider too slow | 504 `upstream_timeout` | No |
| Connection drops mid-stream | Events so far, then a final SSE error event | Never |

## Request logs

Each request writes one JSON line to stdout. Logs hold metadata only (what kinds of data
were caught and how many), never prompt or response content, values or placeholders:

```json
{"request_id": "563600d9cbf1...", "provider": "groq", "started_at": "2026-11-26T04:56:40+00:00",
 "model": "openai/gpt-oss-20b", "stream": false, "status": 200,
 "upstream_latency_ms": 784.36, "total_latency_ms": 784.68, "error_type": null,
 "entity_counts": {"AADHAAR": 1, "PAN": 1, "PHONE": 1, "UPI_ID": 1}, "redaction_ms": 0.15}
```

The same id is returned in the `X-Request-ID` response header. Send your own `X-Request-ID`
to correlate SHOJI's logs with your app's.

## Detection

The rule-based recognizers can also be run on their own (locally, nothing is sent anywhere):

```bash
python -m shoji.detect "Remind Rahul (PAN ABCPD1234F, Aadhaar 2345 6789 0124) to pay ₹4,999 \
via UPI to shop@okaxis or card 4111 1111 1111 1111. Call +91 98765 43210, order 234567890123."
```

```
TYPE         SPAN        SCORE  RECOGNIZER  TEXT
PAN          [18, 28)    0.85   pan         ABCPD1234F
AADHAAR      [38, 52)    0.90   aadhaar     2345 6789 0124
UPI_ID       [79, 90)    0.90   upi         shop@okaxis
CARD_NUMBER  [99, 118)   0.90   card        4111 1111 1111 1111
PHONE        [125, 140)  0.90   phone_in    +91 98765 43210
```

The order number is Aadhaar-shaped but fails the Verhoeff checksum, so it is not reported.
Names ("Rahul") need the ML model from Stage 4. Add `--json` for one JSON object per
detection, or pipe text on stdin. Spans are Python string offsets (Unicode code points).

| Entity | Formats | Validation |
|---|---|---|
| `AADHAAR` | 12 digits, plain or 4-4-4 with spaces/hyphens | first digit 2-9, Verhoeff checksum |
| `PAN` | `AAAAA9999A` | holder-type letter (4th) |
| `GSTIN` | 15 characters | state code, embedded PAN, check character |
| `IFSC` | `AAAA0XXXXXX` | 5th character `0` |
| `PHONE` | Indian mobiles; `+91`/`91`/`0` prefixes; 5-5 or 3-3-4 grouping | starts 6-9 |
| `UPI_ID` | `name@handle` | handle in [`upi_handles.txt`](src/shoji/detect/data/upi_handles.txt) |
| `EMAIL` | `name@domain.tld` | |
| `CARD_NUMBER` | 13-19 digits, plain or grouped | Luhn checksum |
| `IP_ADDRESS` | IPv4, IPv6 | |

Codes such as PAN, GSTIN and IFSC are also accepted in lowercase, with a lower score. When
spans overlap (a PAN inside a GSTIN, a phone number inside a UPI ID), the longer span wins,
then the higher score. Not yet covered: masked Aadhaar (`XXXX XXXX 1234`) and landlines.

Tests and evaluation use only synthetic data from `shoji.synthetic` (fake values, look-alikes
that must not match, and exact ground-truth spans).

## Development

```bash
pytest           # all tests mock the provider; no API calls, no key needed
ruff check .
ruff format --check .
```

`scripts/smoke_redact.py` is a manual check against the real Groq free tier with synthetic
data. It needs `GROQ_API_KEY` and is not run in CI.

## Roadmap

1. ~~Pass-through proxy with streaming, one provider, request logging~~ (done)
2. ~~Rule-based detection for structured Indian and generic formats~~ (done)
3. ~~Redact/restore, including streaming restoration and an encrypted vault~~ (done)
4. ML-based detection (names, addresses) merged with the rules
5. Audit log, dashboard and playground
6. Evaluation against Presidio; answer quality and latency overhead
7. NER fine-tuning if evaluation shows gaps; public demo

All test and demo data is synthetic. No real personal data is ever sent to an LLM API.
