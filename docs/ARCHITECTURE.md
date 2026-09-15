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
| `guardrails/guardrails-function.py` | **shared verbatim** (as of 2026-09-15): embeddings + reranker run locally on CPU TEI, exactly like ai-stack — the cloud adaptations were removed when the single-provider-key design landed |
| `ingestion/ingest.py` | + env `EMBED_MODE` (default `openai`), `EMBED_MODEL`, `EMBED_API_KEY` (LiteLLM master key via compose), `VECTOR_SIZE` (default `3072` for text-embedding-3-large); `embed()` OpenAI-style branch. Worker machinery (manifest, delta, dead-letter, reconciliation) is identical |
| `litellm/config.yaml` | `company-ai` → cloud chat model (the ONLY entry — embeddings/reranker are local TEI and bypass the gateway, same as ai-stack) |
| `docker-compose.yml` | no llamacpp / no GPU reservations; embeddings + reranker = TEI on **CPU** (no GPU); network `oi-net`; paths `/opt/office-inference` |
| `genenv.sh` | `MOONSHOT_API_KEY=PENDING_USER` (the ONLY provider key — embeddings/reranker are local) instead of LLAMA_API_KEY; 10 keys |

## Removed (local-tier only)

llamacpp + all GPU reservations + GPU driver machinery (phase1a/phase1b).
Embeddings/reranker are NOT removed — they run on CPU TEI here instead of GPU.

## The single-provider-key design (2026-09-15)

Only the **chat** call leaves the box (to Moonshot). Embeddings and reranking run
locally on CPU (bge-m3 + bge-reranker-v2-m3, ~1.1 GB each, fine on ≥4 vCPU). So the
stack needs exactly one key (`MOONSHOT_API_KEY`) and the RAG path is byte-identical
to ai-stack's (same models, same 1024-dim collection). The vendored ingest.py keeps
the `EMBED_MODE=openai` branch as an option for future cloud-embeddings setups.

## Sync policy (until/unless the repos merge)

1. Fixes and features land in **`ai-stack` first** (it has the test guard
   `check-doc-sync.py` and the active test box).
2. Vendor to this repo by copying the file and **re-applying the adaptations in
   the table above** — never overwrite an adaptation.
3. If the vendored copies drift twice in the same quarter, that's the signal to
   extract a shared package or unify the repos with compose profiles.

## Model notes (verified 2026-09-15 — re-verify before each deploy)

- **Chat default `moonshot/kimi-k2.6`** (~$0.55/$2.31 per 1M via Moonshot's
  OpenAI-compatible API; key from platform.kimi.ai → `MOONSHOT_API_KEY`).
  LiteLLM's `moonshot/` provider handles the endpoint; `api_base:
  https://api.moonshot.ai/v1` is in the config as a commented fallback.
- **Embeddings + reranker are LOCAL** (bge-m3 + bge-reranker-v2-m3 on CPU TEI —
  no key, no GPU). Cloud-embeddings remains an option via `EMBED_MODE=openai`
  (OpenAI `text-embedding-3-large` = 3072 dims, or `voyage/voyage-embed-4`).
- Alternatives: OpenAI `gpt-6-astra` (flagship) / `gpt-5.6-sol` / `gpt-5.6-terra` /
  `gpt-5.6-luna`; Anthropic `claude-fable-5-1` > `claude-opus-5` > `claude-sonnet-5`
  > `claude-haiku-4-5`; Google `gemini-3.1-pro-preview` / `gemini-3.8-flash`.
  Embeddings alternatives: `voyage/voyage-embed-4` (`VOYAGE_API_KEY`).
- Provider swaps are one-line changes in `litellm/config.yaml`. The weekly tech
  watch (ai-stack `docs/tech-watch.md`) tracks renames/deprecations.

## Reranker

Off by default (`enable_rerank: false` valve) because there's no local reranker
and OpenAI has no rerank endpoint. Optional upgrade: Cohere rerank via LiteLLM
(`rerank-v4.0-pro` or `-fast`; Jina `jina-reranker-v3.5` and Voyage `rerank-2.5`
also current) — set `COHERE_API_KEY` in `.env`, point the guardrails `rerank_url`
valve at `http://litellm:4000`, re-enable the valve.
