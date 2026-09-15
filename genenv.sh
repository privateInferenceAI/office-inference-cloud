#!/usr/bin/env bash
# genenv.sh — generate a FRESH .env for an Office Inference Cloud install.
# Secrets are BORN here (openssl rand), never typed or carried — except the one
# you bring yourself: MOONSHOT_API_KEY (chat). Embeddings + reranker are LOCAL
# (CPU TEI), so Moonshot is the only provider key this stack needs.
set -euo pipefail
STACK=/opt/office-inference

gen() { openssl rand -hex 24; }   # 48 hex chars, URL-safe

PGPASS=$(gen); WEBUISEC=$(gen); QDRANT=$(gen); N8NENC=$(gen)

sudo tee "$STACK/.env" >/dev/null <<EOF
# --- Section 1: cloud provider (YOU fill this in — the only secret you bring) ---
# Moonshot (chat: kimi-k2.6). Embeddings + reranker run locally (CPU TEI) — no key needed.
MOONSHOT_API_KEY=PENDING_USER

# --- Section 3: LiteLLM gateway ---
LITELLM_MASTER_KEY=sk-$(gen)
POSTGRES_USER=litellm
POSTGRES_DB=litellm
POSTGRES_PASSWORD=$PGPASS
DATABASE_URL=postgresql://litellm:$PGPASS@postgres:5432/litellm

# --- Section 4: Open WebUI ---
WEBUI_VIRTUAL_KEY=PENDING_MINT
WEBUI_SECRET_KEY=$WEBUISEC

# --- Section 5: Document brain (RAG) ---
QDRANT_API_KEY=$QDRANT

# --- Section 6: n8n workflows ---
N8N_VIRTUAL_KEY=PENDING_MINT
N8N_ENCRYPTION_KEY=$N8NENC
EOF
sudo chmod 600 "$STACK/.env"
sudo chown "${SUDO_USER:-$USER}:${SUDO_USER:-$USER}" "$STACK/.env"

# verify: 10 keys, none empty
# (the count pattern must include 0-9 or the digit-bearing N8N_* keys don't count)
MISSING=$(sudo grep -cE '=$' "$STACK/.env" || true)
COUNT=$(sudo grep -cE '^[A-Z0-9_]+=' "$STACK/.env" || true)
echo "genenv: wrote $STACK/.env (mode 600). keys=$COUNT empty=$MISSING"
[[ "$COUNT" -ge 10 && "$MISSING" -eq 0 ]] || { echo "ERROR: env incomplete"; exit 1; }

echo
echo "NEXT:"
echo "  1. edit $STACK/.env and set MOONSHOT_API_KEY"
echo "  2. docker network create oi-net   (once per host)"
echo "  3. cd $STACK && docker compose build ingestion && docker compose up -d"
echo "  4. mint the WebUI + n8n virtual keys (see README quick start)"
