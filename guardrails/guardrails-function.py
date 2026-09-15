"""
title: Company Guardrails + RAG
author: ai-stack
version: 0.4
description: Input guardrails (topic denial, injection), RAG injection from Qdrant with role-based ACL, output PII redaction.

CHANGELOG:
- v0.2: Changed rag_top_k from 3 to 10. Restructured ACL search to use Qdrant "should" filter
        so all users get the same retrieval count (ACL controls visibility, not volume).
        Previously: looped per-ACL with per-ACL limit, then truncated — gave admins more results by accident.
- v0.3: Conversation-aware injection. Retrieved context now arrives as a SEPARATE labeled
        system message before the user's question (which stays verbatim) — the wrapper can
        no longer be mistaken for a conversation turn, and conversational/meta messages stop
        being force-answered from random chunks. Retrieval now embeds the last
        rag_context_turns user messages, so follow-ups ("tell me more", "look deeper")
        retrieve what the conversation was actually about.
- v0.4: Meta-gate. Messages that are ABOUT the conversation itself ("repeat my first two
        questions", "what did I just ask", "do you remember") skip retrieval entirely —
        history answers those, and injected chunks can only distract. Deterministic
        behavior for meta-questions, enforced by code, not by hoping the model copes.
"""

from pydantic import BaseModel, Field
from typing import Optional
import os
import re
import requests

# CHANGED v0.4: meta/conversational messages skip retrieval entirely. Deliberately
# conservative: when in doubt we RETRIEVE (a slightly-irrelevant excerpt with the v0.3
# softened label is a small cost; skipping a real document question is a big one).
META_PATTERN = re.compile(
    r"\b(our conversation|this conversation|this chat|previous question|first question|"
    r"second question|earlier (question|message)|what did i (just )?(say|ask)|"
    r"repeat (back|my|it|that)|word for word|you (said|told|mentioned)|"
    r"we (discussed|talked about)|(chat|conversation|session) history|"
    r"remember (when|that|my)|do you remember|context of (our|this))\b",
    re.IGNORECASE,
)


class Filter:
    class Valves(BaseModel):
        # --- Guardrails config ---
        denied_keywords: str = Field(
            default="salary of,how much does,ssn,social security number,ignore previous instructions,ignore all previous,you are now,system:",
            description="Comma-separated lowercase substrings that trigger an input refusal.",
        )
        refusal_message: str = Field(
            default="I'm not able to help with that. Please contact your administrator if you believe this is an error.",
            description="Message returned when input is denied.",
        )
        # --- RAG config ---
        enable_rag: bool = Field(default=True, description="Inject Qdrant doc context.")
        qdrant_url: str = Field(
            default="http://qdrant:6333", description="Qdrant base URL."
        )
        qdrant_collection: str = Field(
            default="company_docs", description="Qdrant collection."
        )
        embed_url: str = Field(
            default="http://embeddings:80", description="Embeddings base URL."
        )
        rerank_url: str = Field(
            default="http://reranker:80", description="Reranker base URL."
        )
        enable_rerank: bool = Field(
            default=True, description="Re-rank retrieved chunks before injection."
        )
        qdrant_api_key: str = Field(
            default=os.environ.get("QDRANT_API_KEY", ""),
            description="Qdrant API key.",
        )
        # CHANGED v0.2: was default=3, now default=10
        # Rationale: 32k context has room; reranker works better with larger pool;
        # production needs better recall than 3 chunks provides.
        rag_top_k: int = Field(default=10, description="Number of chunks to retrieve and inject.")
        # CHANGED v0.3: retrieval uses the last N user messages so follow-up questions
        # ("tell me more", "anything else") pull chunks about the actual topic.
        rag_context_turns: int = Field(
            default=2,
            description="How many recent user messages to embed for retrieval (follow-up context).",
        )
        # CHANGED v0.4
        rag_skip_meta: bool = Field(
            default=True,
            description="Skip retrieval for questions about the conversation itself — history answers those.",
        )
        executive_roles: str = Field(
            default="admin",
            description="Comma-separated roles that get the 'executive' ACL filter; all others get 'company'.",
        )
        # --- Output redaction ---
        redact_patterns: str = Field(
            default=r"\b\d{3}-\d{2}-\d{4}\b",
            description="Comma-separated regex patterns to redact in output.",
        )

    def __init__(self):
        self.valves = self.Valves()

    # ---------------- helpers ----------------

    def _acl_for_user(self, __user__: Optional[dict]) -> str:
        role = (__user__ or {}).get("role", "user")
        exec_roles = [
            r.strip() for r in self.valves.executive_roles.split(",") if r.strip()
        ]
        return "executive" if role in exec_roles else "company"

    def _is_denied(self, text: str) -> bool:
        t = text.lower()
        kws = [k.strip() for k in self.valves.denied_keywords.split(",") if k.strip()]
        return any(k in t for k in kws)

    def _embed(self, text: str):
        resp = requests.post(
            f"{self.valves.embed_url}/embed",
            json={"inputs": [text]},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json()[0]

    # CHANGED v0.2: _search now takes a LIST of acls and uses Qdrant "should" filter.
    # Previously: took single acl, called once per acl, results merged and truncated.
    # Now: one search, one limit, ACL controls visibility not volume.
    def _search(self, vector, acls):
        headers = {
            "api-key": self.valves.qdrant_api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "vector": vector,
            "limit": self.valves.rag_top_k,
            "with_payload": True,
            "filter": {
                "should": [
                    {"key": "acl", "match": {"value": acl}} for acl in acls
                ]
            },
        }
        resp = requests.post(
            f"{self.valves.qdrant_url}/collections/{self.valves.qdrant_collection}/points/search",
            headers=headers,
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])

    def _rerank(self, query: str, hits):
        # Re-order retrieved chunks by true relevance to the question.
        if not hits or not self.valves.enable_rerank:
            return hits
        try:
            texts = [h["payload"]["text"] for h in hits if h.get("payload")]
            if not texts:
                return hits
            resp = requests.post(
                f"{self.valves.rerank_url}/rerank",
                json={"query": query, "texts": texts},
                timeout=60,
            )
            resp.raise_for_status()
            ranked = resp.json()  # list of {"index": i, "score": s}
            # sort by score descending, map back to hits, keep order
            order = sorted(ranked, key=lambda r: r.get("score", 0), reverse=True)
            reranked = [
                hits[r["index"]] for r in order if 0 <= r.get("index", -1) < len(hits)
            ]
            print(
                f"[guardrails] reranked {len(reranked)} chunk(s); top score={order[0].get('score') if order else 'n/a'}"
            )
            return reranked
        except Exception as e:
            print(f"[guardrails] rerank error (keeping original order): {e}")
            return hits

    def _last_user_text(self, body: dict) -> str:
        messages = body.get("messages", [])
        for m in reversed(messages):
            if m.get("role") == "user":
                return m.get("content", "")
        return ""

    def _recent_user_text(self, body: dict, n: int) -> str:
        """The last n user messages, chronological, each capped — the retrieval query
        for follow-up-aware RAG (v0.3)."""
        texts = [
            m.get("content", "")[:300]
            for m in body.get("messages", [])
            if m.get("role") == "user"
        ]
        return "\n".join(t for t in texts[-n:] if t)

    # ---------------- hooks ----------------

    def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        print(f"[guardrails] inlet start; user={(__user__ or {}).get('email')}")

        user_text = self._last_user_text(body)

        # 1. INPUT GUARDRAIL — stop denied topics / injection before the model ever sees it
        if user_text and self._is_denied(user_text):
            print("[guardrails] INPUT DENIED")
            raise Exception(self.valves.refusal_message)

        # 2. DOCUMENT CONNECTOR (RAG) — inject role-filtered context
        # CHANGED v0.4: meta-gate — questions ABOUT the conversation are answered from
        # history; injected chunks can only distract there. (Our own previously injected
        # excerpts remain visible in history, so document recap questions still work.)
        if self.valves.rag_skip_meta and user_text and META_PATTERN.search(user_text):
            print("[guardrails] META message — skipping retrieval (answered from history)")
        elif self.valves.enable_rag and user_text:
            try:
                role = (__user__ or {}).get("role", "user")
                exec_roles = [
                    r.strip()
                    for r in self.valves.executive_roles.split(",")
                    if r.strip()
                ]
                # executives see company + executive; everyone else sees company only
                acls = ["company", "executive"] if role in exec_roles else ["company"]
                # CHANGED v0.3: retrieval embeds the last N user turns so follow-up
                # questions ("tell me more") retrieve the actual topic, not junk.
                query_text = self._recent_user_text(body, self.valves.rag_context_turns) or user_text
                vec = self._embed(query_text)

                # CHANGED v0.2: single search with should-filter, no loop, no truncation.
                # Previously: looped per-ACL, merged, truncated to rag_top_k.
                # Now: one search returns up to rag_top_k total, mixed by relevance.
                hits = self._search(vec, acls)
                hits = self._rerank(query_text, hits)

                acl = "+".join(acls)  # for the log line below
                if hits:
                    context = "\n\n".join(
                        h["payload"]["text"] for h in hits if h.get("payload")
                    )
                    if context.strip():
                        # CHANGED v0.3: context goes in a SEPARATE labeled system message
                        # placed just before the user's question (which stays verbatim).
                        # The wrapper can no longer be mistaken for a conversation turn,
                        # and conversational messages stop being force-answered from chunks.
                        prefix = (
                            "REFERENCE EXCERPTS from company documents, retrieved for the user's "
                            "next message. Use them when they are relevant. Ignore them for "
                            "conversational questions (about this chat itself, preferences, or "
                            "earlier turns). If none of the excerpts address the question, say "
                            "you don't have that information in the documents.\n\n"
                            f"--- COMPANY INFORMATION ---\n{context}\n--- END ---"
                        )
                        messages = body.get("messages", [])
                        for i in range(len(messages) - 1, -1, -1):
                            if messages[i].get("role") == "user":
                                messages.insert(i, {"role": "system", "content": prefix})
                                break
                        print(
                            f"[guardrails] RAG injected {len(hits)} chunk(s) with acl={acl}"
                        )
                else:
                    print(f"[guardrails] RAG: no hits for acl={acl}")
            except Exception as e:
                # fail open: don't break chat if the brain hiccups
                print(f"[guardrails] RAG error (continuing without context): {e}")

        return body

    def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        # 3. OUTPUT GUARDRAIL — redact PII patterns in the assistant's reply
        try:
            patterns = [p for p in self.valves.redact_patterns.split(",") if p.strip()]
            messages = body.get("messages", [])
            for m in reversed(messages):
                if m.get("role") == "assistant":
                    content = m.get("content", "")
                    for pat in patterns:
                        content = re.sub(pat, "[REDACTED]", content)
                    m["content"] = content
                    break
        except Exception as e:
            print(f"[guardrails] outlet redaction error: {e}")
        return body
