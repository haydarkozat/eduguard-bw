"""
EduGuard BW — AI ticket triage (LangGraph + local Ollama).

A strict, **fully self-hosted** triage workflow. No ticket text ever leaves the
host: classification runs on a local Ollama model, and knowledge retrieval is a
local store (a mock today, Qdrant tomorrow — same interface).

Graph
-----
    analyze  ->  suggest  ->  END

* ``analyze`` : local Ollama extracts ``category`` (Network/Hardware/Software/
  Account) and ``priority`` (Low/Medium/High) from ``ticket_text``.
* ``suggest`` : looks the category up in a local knowledge base and produces a
  ``suggested_action``. The KB is behind a small ``KnowledgeBase`` interface, so
  swapping the mock for Qdrant is a one-line change (see ``get_knowledge_base``).

If Ollama is unreachable, a keyword heuristic keeps the prototype usable.
"""
from __future__ import annotations

import json
import os
from typing import Protocol, TypedDict

from langgraph.graph import END, StateGraph

from knowledge_base import KnowledgeBase, get_knowledge_base

OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3")

CATEGORIES = ("Network", "Hardware", "Software", "Account")
PRIORITIES = ("Low", "Medium", "High")

# SLA hint appended to the KB action, driven by the analyzed priority.
SLA_BY_PRIORITY = {
    "High": "Escalate to on-site IT immediately (P1, target < 1h).",
    "Medium": "Assign to 1st-level support (target < 1 business day).",
    "Low": "Queue for routine handling (weekly batch).",
}


# ---------------------------------------------------------------------------
# Shared graph state
# ---------------------------------------------------------------------------
class TriageState(TypedDict, total=False):
    ticket_text: str
    category: str
    priority: str
    summary: str
    suggested_action: str
    kb_source: str


# ---------------------------------------------------------------------------
# Prompt — 1st-Level IT Support Assistant for a German school
# ---------------------------------------------------------------------------
ANALYZE_PROMPT = """You are a 1st-Level IT Support Assistant for a school in \
Baden-Württemberg, Germany. You triage incoming IT support tickets from teachers \
and staff. Tickets may be in German or English.

Classify the ticket below.

- category MUST be exactly one of: Network, Hardware, Software, Account.
- priority MUST be exactly one of: Low, Medium, High.
  * High  = teaching is blocked now, many users affected, or a security concern.
  * Medium= a single device/user is impaired but a workaround exists.
  * Low   = minor issue, request, or cosmetic.

Respond with ONLY compact JSON, no prose, of this exact shape:
{{"category": "<one of the four>", "priority": "<Low|Medium|High>", \
"summary": "<one short sentence>"}}

Ticket: {ticket_text}
"""

# Node 2 prompt — grounds the action in retrieved IT documentation (RAG).
SUGGEST_PROMPT = """You are a 1st-Level IT Support Assistant for a school. \
Recommend a concrete first-line action for the ticket below, grounded ONLY in \
the knowledge-base context provided. Do not invent steps that aren't supported \
by the context; if the context is insufficient, say what to verify and which \
team to route to.

Knowledge-base context:
{context}

Ticket: {ticket_text}
Category: {category}
Priority: {priority}

Answer with 1-3 short, actionable sentences. No preamble, no markdown.
"""


# ---------------------------------------------------------------------------
# Ollama helper (lazy import so the module loads without the dependency)
# ---------------------------------------------------------------------------
class _Analyzer(Protocol):
    def __call__(self, ticket_text: str) -> dict: ...


def _get_llm():
    """Return a langchain-ollama chat model, or None if unavailable."""
    try:
        from langchain_ollama import ChatOllama

        return ChatOllama(base_url=OLLAMA_BASE_URL, model=OLLAMA_MODEL, temperature=0)
    except Exception:
        return None


def _extract_json(text: str) -> str:
    """Pull the first {...} block out of an LLM response."""
    start, end = text.find("{"), text.rfind("}")
    return text[start : end + 1] if start != -1 and end > start else text


def _heuristic_analyze(ticket_text: str) -> dict:
    """Keyword fallback when Ollama is offline. Mirrors the four categories."""
    q = ticket_text.lower()
    if any(w in q for w in ("wlan", "wifi", "internet", "network", "netzwerk", "vpn", "down")):
        category = "Network"
    elif any(w in q for w in ("password", "passwort", "login", "account", "konto", "locked", "gesperrt")):
        category = "Account"
    elif any(w in q for w in ("smartboard", "beamer", "printer", "drucker", "monitor", "signal", "device")):
        category = "Hardware"
    else:
        category = "Software"

    if any(w in q for w in ("down", "outage", "whole class", "ganze klasse", "breach", "all", "alle")):
        priority = "High"
    elif any(w in q for w in ("no signal", "not working", "broken", "kein", "nicht", "error", "fehler")):
        priority = "Medium"
    else:
        priority = "Low"

    return {"category": category, "priority": priority, "summary": ticket_text.strip()}


# ---------------------------------------------------------------------------
# Node 1 — Analyze (local Ollama classification)
# ---------------------------------------------------------------------------
def analyze_node(state: TriageState) -> TriageState:
    ticket_text = state["ticket_text"]
    llm = _get_llm()

    if llm is not None:
        try:
            raw = llm.invoke(ANALYZE_PROMPT.format(ticket_text=ticket_text)).content
            data = json.loads(_extract_json(raw))
            category = data.get("category") if data.get("category") in CATEGORIES else None
            priority = data.get("priority") if data.get("priority") in PRIORITIES else None
            if category and priority:
                return {
                    **state,
                    "category": category,
                    "priority": priority,
                    "summary": data.get("summary", ticket_text),
                }
        except Exception:
            pass  # fall through to heuristic

    return {**state, **_heuristic_analyze(ticket_text)}


# ---------------------------------------------------------------------------
# Node 2 — Suggest (local knowledge-base retrieval; Qdrant-ready)
# ---------------------------------------------------------------------------
def suggest_node(state: TriageState, kb: KnowledgeBase | None = None) -> TriageState:
    kb = kb or get_knowledge_base()
    category = state.get("category", "Software")
    priority = state.get("priority", "Medium")
    ticket_text = state["ticket_text"]

    # --- RAG retrieval: pull relevant IT documentation (Qdrant or mock) -------
    try:
        docs = kb.retrieve(category=category, query=ticket_text, k=3)
    except Exception:
        docs = []

    context = "\n".join(f"- {d.title}: {d.action}" for d in docs) or "(no documentation found)"
    source = ", ".join(d.source for d in docs) or "none"

    # --- Grounded generation: inject the retrieved context into Ollama --------
    llm = _get_llm()
    if llm is not None and docs:
        try:
            grounded = llm.invoke(
                SUGGEST_PROMPT.format(
                    context=context,
                    ticket_text=ticket_text,
                    category=category,
                    priority=priority,
                )
            ).content.strip()
            if grounded:
                return {**state, "suggested_action": grounded, "kb_source": source}
        except Exception:
            pass  # fall through to the deterministic fallback

    # --- Fallback: top retrieved action + priority SLA (no LLM needed) --------
    if docs:
        action = f"{docs[0].action} — {SLA_BY_PRIORITY.get(priority, '')}".strip(" —")
    else:
        action = SLA_BY_PRIORITY.get(priority, "Assign to 1st-level support.")
    return {**state, "suggested_action": action, "kb_source": source}


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------
def build_triage_graph(kb: KnowledgeBase | None = None):
    """Compile the triage graph. Pass a custom ``kb`` to inject Qdrant later."""
    graph = StateGraph(TriageState)
    graph.add_node("analyze", analyze_node)
    graph.add_node("suggest", lambda state: suggest_node(state, kb=kb))
    graph.set_entry_point("analyze")
    graph.add_edge("analyze", "suggest")
    graph.add_edge("suggest", END)
    return graph.compile()


# Compiled once at import time with the default (mock) knowledge base.
_TRIAGE_APP = build_triage_graph()


def triage_ticket(ticket_text: str) -> dict:
    """Run a single IT support ticket through the triage graph."""
    final_state = _TRIAGE_APP.invoke({"ticket_text": ticket_text})
    return {
        "category": final_state.get("category", "Software"),
        "priority": final_state.get("priority", "Medium"),
        "summary": final_state.get("summary", ticket_text),
        "suggested_action": final_state.get("suggested_action", ""),
        "kb_source": final_state.get("kb_source", "none"),
    }


if __name__ == "__main__":
    for sample in (
        "Smartboard no signal in room 204",
        "Das ganze WLAN in Gebäude B ist ausgefallen",
        "Passwort vergessen, Konto gesperrt",
    ):
        print(json.dumps(triage_ticket(sample), indent=2, ensure_ascii=False))
        print("-" * 60)
