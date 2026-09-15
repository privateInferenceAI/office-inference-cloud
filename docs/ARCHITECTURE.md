# Architecture — shared vs. different

Office Inference Cloud is the **same product** as `ai-stack` with the inference
tier swapped. This document is the map of what is shared verbatim, what is
adapted, and how changes flow between the repos.

## Shared verbatim (copy from ai-stack)

- `guardrails/policy.txt` — the human-readable policy contract
- `ingestion/Dockerfile` — same package set

## Adapted (vendored copies — edit carefully, keep the adaptations)

| File | Adaptations vs ai-stack |
|---|---|
| `guardrails/guardrails-function.py` | + valves `embed_mode` (default `openai`), `embed_model` (default `company-embed`), `embed_api_key` (set at install); `_embed()` posts OpenAI-style `/embeddings` via LiteLLM; `enable_rerank` defaults to **false** (no local reranker); `embed_url` default `http://litellm:4000/v1` |
| `ingestion/ingest.py` | + env `EMBED_MODE` (default `openai`), `EMBED_MODEL`, `EMBED_API_KEY` (LiteLLM master key via compose), `VECTOR_SIZE` (default `3072` for text-embedding-3-large); `embed()` OpenAI-style branch. Worker machinery (manifest, delta, dead-letter, reconciliation) is identical |
| `litellm/config.yaml` | `company-ai` → cloud chat model; `company-embed` → cloud embedding model (aliases are the only names the stack sees — swap providers by editing this one file) |
| `docker-compose.yml` | no llamacpp/embeddings/reranker (GPU tier); network `oi-net`; paths `/opt/office-inference`; ingestion gets the EMBED_* + VECTOR_SIZE env |
| `genenv.sh` | `OPENAI_API_KEY=PENDING_USER` instead of LLAMA_API_KEY; 10 keys |

## Removed (local-tier only)

llamacpp, TEI embeddings, TEI reranker, all GPU reservations, model GGUF/TEI
pre-download steps, all phase1a/phase1b GPU driver machinery.

## Sync policy (until/unless the repos merge)

1. Fixes and features land in **`ai-stack` first** (it has the test guard
   `check-doc-sync.py` and the active test box).
2. Vendor to this repo by copying the file and **re-applying the adaptations in
   the table above** — never overwrite an adaptation.
3. If the vendored copies drift twice in the same quarter, that's the signal to
   extract a shared package or unify the repos with compose profiles.

## Model notes (verified 2026-09-15 — re-verify before each deploy)

- Chat default `openai/gpt-5.6-sol` (workhorse, $4/$20 per 1M); flagship
  `openai/gpt-6-astra`; mid `gpt-5.6-terra` (~$2); cheap `gpt-5.6-luna` ($0.20).
- Embeddings `openai/text-embedding-3-large` (3072 dims — must match `VECTOR_SIZE`
  in compose; the cheap option `text-embedding-3-small` is 1536).
- Anthropic tier order: `claude-fable-5-1` > `claude-opus-5` > `claude-sonnet-5` >
  `claude-haiku-4-5` (key: `ANTHROPIC_API_KEY` in `.env`).
- Google: `gemini/gemini-3.1-pro-preview`, `gemini/gemini-3.8-flash`
  (key: `GEMINI_API_KEY`).
- Provider swaps are one-line changes in `litellm/config.yaml`. The weekly tech
  watch (ai-stack `docs/tech-watch.md`) tracks renames/deprecations.

## Reranker

Off by default (`enable_rerank: false` valve) because there's no local reranker
and OpenAI has no rerank endpoint. Optional upgrade: Cohere rerank via LiteLLM
(`rerank-v4.0-pro` or `-fast`; Jina `jina-reranker-v3.5` and Voyage `rerank-2.5`
also current) — set `COHERE_API_KEY` in `.env`, point the guardrails `rerank_url`
valve at `http://litellm:4000`, re-enable the valve.
