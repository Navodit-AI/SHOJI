# SHOJI

A privacy firewall for LLM apps. SHOJI sits between your application and an LLM API,
detects personal data in prompts (with strong coverage of Indian formats such as Aadhaar,
PAN, UPI IDs, IFSC, GSTIN and Indian phone numbers), replaces it with reversible
placeholders before anything leaves the machine, restores the real values in the model's
response, and keeps an audit log.

Integration is a one-line change: point your OpenAI-compatible client's base URL at SHOJI.

> Status: Stage 1 of 7 complete: an OpenAI-compatible pass-through proxy with streaming,
> retries and request logging. Detection and redaction come next (Stages 2–4).

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

Each request writes one JSON line to stdout. Logs hold metadata only, never prompt or
response content:

```json
{"request_id": "75153b5c...", "provider": "groq", "started_at": "2026-11-22T18:35:12+00:00",
 "model": "openai/gpt-oss-20b", "stream": false, "status": 200,
 "upstream_latency_ms": 674.47, "total_latency_ms": 675.68, "error_type": null}
```

The same id is returned in the `X-Request-ID` response header. Send your own `X-Request-ID`
to correlate SHOJI's logs with your app's.

## Development

```bash
pytest           # all tests mock the provider; no API calls, no key needed
ruff check .
ruff format --check .
```

## Roadmap

1. ~~Pass-through proxy with streaming, one provider, request logging~~ (done)
2. Rule-based detection for structured Indian and generic formats
3. Redact/restore, including streaming restoration and an encrypted vault
4. ML-based detection (names, addresses) merged with the rules
5. Audit log, dashboard and playground
6. Evaluation against Presidio; answer quality and latency overhead
7. NER fine-tuning if evaluation shows gaps; public demo

All test and demo data is synthetic. No real personal data is ever sent to an LLM API.
