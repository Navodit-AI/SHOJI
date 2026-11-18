# SHOJI

A privacy firewall for LLM apps. SHOJI sits between your application and an LLM API,
detects personal data in prompts (with strong coverage of Indian formats such as Aadhaar,
PAN, UPI IDs, IFSC, GSTIN and Indian phone numbers), replaces it with reversible
placeholders before anything leaves the machine, restores the real values in the model's
response, and keeps an audit log.

Integration is a one-line change: point your OpenAI-compatible client's base URL at SHOJI.

> Status: early development (Stage 1 of 7, pass-through proxy).

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env   # then add your free-tier API key
pytest
ruff check .
```

## Roadmap

1. Pass-through proxy with streaming, one provider, request logging
2. Rule-based detection for structured Indian and generic formats
3. Redact/restore, including streaming restoration and an encrypted vault
4. ML-based detection (names, addresses) merged with the rules
5. Audit log, dashboard and playground
6. Evaluation against Presidio; answer quality and latency overhead
7. NER fine-tuning if evaluation shows gaps; public demo

All test and demo data is synthetic. No real personal data is ever sent to an LLM API.
