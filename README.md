# Office Inference Cloud

**The full agentic business-AI stack — guardrails, RAG over company documents, and
workflow automation — running on cloud LLMs through a LiteLLM gateway.**
For businesses that don't require on-prem inference.

An **Office Inference** product. Companion repo to
[`privateInferenceAI/ai-stack`](https://github.com/privateInferenceAI/ai-stack)
(the local, zero-egress privacy tier).

## The philosophy: swap the LLM, keep the system

The product is the agentic layer — code-enforced guardrails, role-ACL'd RAG,
n8n workflows — not the model. The model is a part number. This repo is the same
system as `ai-stack` with the GPU inference tier replaced by cloud providers:
**everything else — guardrails, ingestion, vector store, UI, workflows — stays the same.**

| | ai-stack (local tier) | office-inference-cloud (this repo) |
|---|---|---|
| Chat model | Qwen3-14B/32B local (llama.cpp) | Cloud via LiteLLM (OpenAI default; Anthropic/Gemini one line away) |
| Embeddings | bge-m3 local (TEI) | text-embedding-3-large via LiteLLM |
| Reranker | bge-reranker-v2-m3 local | off by default (Cohere optional) |
| GPU required | yes | **no** |
| Guardrails / RAG / ACL / ingestion / workflows | ✅ | ✅ identical components |
| Data leaves the building | **never** | **yes** — queries + retrieved excerpts + embeddings go to the provider |

## The privacy boundary (read before selling/deploying)

This variant exists for businesses that accept cloud processing. Per request, the
provider receives: the user's message, conversation history, retrieved document
excerpts, and embedding inputs. **Stored state stays on your box** (Qdrant vectors,
Postgres, accounts, workflows, documents). Need zero egress? That's
[`ai-stack`](https://github.com/privateInferenceAI/ai-stack).

## Architecture

7 containers on a Docker network (`oi-net`): **open-webui** (:3000, chat UI) →
**guardrails function** (denial + meta-gate + ACL'd RAG, PII redaction) →
**litellm** (:4000, gateway) → cloud provider. **qdrant** (vectors),
**postgres** (gateway DB), **ingestion** (periodic document worker), **n8n**
(:5678, workflows), **mailpit** (:8025, demo SMTP). No GPU; runs on a small VPS.

## Quick start

```bash
sudo mkdir -p /opt/office-inference && sudo chown $USER:$USER /opt/office-inference
# clone this repo's contents INTO /opt/office-inference (top level), then:
cd /opt/office-inference
sudo docker network create oi-net
sudo bash genenv.sh
sudo $EDITOR /opt/office-inference/.env     # set OPENAI_API_KEY
docker compose build ingestion
docker compose up -d
```

Then the same browser wiring as ai-stack: create the WebUI admin (first account) →
disable signups → mint two virtual keys (`POST /key/generate` on :4000 with the
master key from `.env`) into `WEBUI_VIRTUAL_KEY` / `N8N_VIRTUAL_KEY` →
force-recreate open-webui + n8n → import `guardrails/guardrails-function.py`
(Functions → enable + GLOBAL → Valves: `qdrant_api_key` **and** `embed_api_key`
= `LITELLM_MASTER_KEY` from `.env`) → n8n owner + credentials → import the
invoice workflow from `exports/`.

## What's here

```
docker-compose.yml     7 services, no GPU
litellm/config.yaml    company-ai + company-embed aliases → provider models
genenv.sh              generates .env (openssl secrets; you add OPENAI_API_KEY)
guardrails/            policy.txt + guardrails-function.py (vendored from ai-stack, cloud-adapted)
ingestion/             periodic document worker (vendored from ai-stack, cloud-adapted)
docs/ARCHITECTURE.md   shared-vs-different map, sync policy, model notes
```

## Roadmap

Cohere rerank via LiteLLM • provider STT or speaches-cpu voice • build scripts
(pathb equivalent) • eval harness • n8n workflow library • quarterly upstream
review (watch lives in ai-stack's tech watch).
