# Privacy Firewall for LLM Apps

## What this is
A proxy that sits between any application and an LLM API. It detects personal data in
prompts, replaces it with reversible placeholders before anything leaves the machine,
restores the real values in the model's response, and keeps an audit log.

Apps integrate by changing one base URL: the proxy exposes an OpenAI-compatible
`/v1/chat/completions` endpoint, including streaming.

## Why it exists (the portfolio story)
- Target audience: AI/ML and AI full-stack companies.
- It has to show both a real ML contribution and production engineering. It must not read as an API wrapper.
- Differentiator: strong coverage of Indian personal-data formats (Aadhaar, PAN, UPI IDs,
  Indian phone numbers, IFSC, GSTIN, Indian names and addresses), which existing open-source
  tools such as Microsoft Presidio handle poorly.
- Headline result to aim for: detection precision/recall vs Presidio on an Indian-format
  test set, plus the measured effect of redaction on LLM answer quality, plus added latency.

## Hard constraints
- **Zero budget.** Free tools and free tiers only (Groq / Gemini / OpenRouter free tiers for
  LLM calls; Kaggle or Colab free GPUs for any fine-tuning; free hosting for the demo).
- **Dev machine:** MacBook Pro M3, 8 GB RAM. Everything that runs locally must stay
  lightweight: CPU-friendly models, no large local LLMs.
- Provider-agnostic design: switching LLM providers should be a config change, since free
  tiers change without notice.
- Never send real personal data to free-tier APIs during development or testing; use
  synthetic data only.

## Architecture (target)
1. **Proxy layer:** OpenAI-compatible endpoint, streaming pass-through, provider routing,
   timeouts, retries, fallback across providers.
2. **Detection:**
   - Rule-based recognizers for structured formats (with checksum validation where one
     exists, e.g. Aadhaar Verhoeff check).
   - Small NER model (e.g. GLiNER, CPU-friendly) for names, addresses and organisations.
   - Merge and resolve overlapping detections.
3. **Redact/restore:** consistent placeholders per request (`<PERSON_1>`, `<PHONE_1>`, …),
   with the same value always getting the same placeholder within a conversation. Restore
   must handle placeholders split across streamed chunks.
4. **Vault and audit log:** an encrypted mapping store and per-request audit records
   (entity types caught, counts, latency added; never the raw values in plaintext).
5. **Dashboard:** catches over time, entity breakdown, latency, request history, plus a
   live "try it" playground showing original vs what the LLM actually saw.
6. **Evaluation harness:** reproducible scripts producing the headline numbers.

## Suggested stack (open to change)
Python + FastAPI + httpx (async streaming) for the proxy; SQLite for development
(Postgres-ready schema) for the vault and audit log; a React/Next.js dashboard; pytest.

## Build stages (each stage must work end-to-end before the next)
1. Pass-through proxy with streaming, one free provider, request logging.
2. Rule-based detection for structured Indian and generic formats, with unit tests.
3. Redact/restore, including streaming restoration and the encrypted vault.
4. ML-based detection (names/addresses) merged with the rules.
5. Audit log + dashboard + playground.
6. Evaluation: synthetic Indian-format test set; compare against Presidio; measure answer
   quality with vs without redaction; measure latency overhead.
7. Fine-tune the NER model on free GPUs if evaluation shows gaps; deploy a public demo.

## Evaluation principles
- Every claim on the resume must come from a reproducible script in this repo.
- Report precision, recall and F1 per entity type, not only overall.
- The public demo must not need paid calls or expose any real data.

## Out of scope (for now)
Multi-tenant auth, enterprise SSO, non-text modalities (images/PDFs), languages beyond
English and Hinglish.

## Related, later
A second project ("Counterfactual", causal failure attribution for LLM agents) will reuse
the LLM-traffic interception ideas from this proxy layer. Keep the proxy's request/response
capture clean and reusable.

## Workflow
- One GitHub issue per unit of work; each build stage is a milestone.
- Per issue: `git switch main && git pull`, then a branch like `proxy/3-streaming-passthrough`.
- Claude writes code + tests and runs `ruff check .`, `ruff format --check .` and `pytest`
  locally, then shows Navodit the diff summary and test output. Nothing is pushed and no PR
  is opened until Navodit approves.
- Commits: conventional style (`feat(proxy): ...`, `test(detect): ...`, `docs: ...`).
  PR body includes `Closes #N`. Navodit merges.
- Never push to main (the initial scaffold commit was the only exception), never force-push,
  never rebase a pushed branch; bring in main by merging.
- No Claude attribution in commits or PRs (no Co-Authored-By, no "Generated with" lines).
- Tests never call real LLM APIs: mock the upstream with `respx`. Real calls only in manual
  smoke scripts, with synthetic data.
- Secrets live in `.env` (gitignored); `.env.example` documents them.
- A stage closes only when it works end to end: README demo command + green CI.
- Every reported number comes from a script in `eval/` writing to `results/`.

## State
- 18 Nov 2026: repo scaffolded (pyproject, CI, README). Stage 1 not started.
