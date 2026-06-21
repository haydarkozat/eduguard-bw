"""
EduGuard BW — IT knowledge base interface + local mock.

The triage graph's "Suggest" node depends only on the ``KnowledgeBase``
Protocol below. Today it's backed by an in-memory mock that does naive keyword
overlap scoring; in a later phase a ``QdrantKnowledgeBase`` will implement the
exact same ``retrieve`` signature using vector search — no change to the graph.

To swap in Qdrant later, implement ``QdrantKnowledgeBase`` and return it from
``get_knowledge_base`` (e.g. gated on the ``QDRANT_URL`` env var).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class KBDoc:
    """A retrieved knowledge-base entry."""

    title: str
    action: str
    source: str
    score: float = 0.0


@runtime_checkable
class KnowledgeBase(Protocol):
    """Anything the Suggest node can query. Qdrant will implement this too."""

    def retrieve(self, category: str, query: str, k: int = 1) -> list[KBDoc]: ...


# ---------------------------------------------------------------------------
# Local mock knowledge base
# ---------------------------------------------------------------------------
# Per-category playbook. Each entry carries trigger keywords so the mock can do
# a lightweight relevance match — a stand-in for vector similarity.
_PLAYBOOK: dict[str, list[dict]] = {
    "Network": [
        {
            "title": "WLAN / Wi-Fi outage",
            "keywords": ["wlan", "wifi", "internet", "ssid", "access point", "ausgefallen", "down"],
            "action": "Verify the affected AP/switch uplink; check the captive portal and "
            "the building VLAN; restart the AP if a single room is affected.",
            "source": "kb://network/wlan-outage",
        },
        {
            "title": "VPN / remote access",
            "keywords": ["vpn", "remote", "fernzugriff", "tunnel"],
            "action": "Confirm the user's VPN profile and certificate validity; check the "
            "firewall VPN gateway status.",
            "source": "kb://network/vpn",
        },
    ],
    "Hardware": [
        {
            "title": "Display / projector no signal",
            "keywords": ["smartboard", "beamer", "projector", "monitor", "signal", "hdmi", "display"],
            "action": "Check cable/input source on the display; power-cycle the panel; "
            "test with a known-good laptop; verify the correct HDMI input.",
            "source": "kb://hardware/display-no-signal",
        },
        {
            "title": "Printer issue",
            "keywords": ["printer", "drucker", "toner", "paper jam", "papierstau"],
            "action": "Check toner/paper and the print queue on the print server; clear "
            "stuck jobs; confirm the printer's IP is reachable.",
            "source": "kb://hardware/printer",
        },
    ],
    "Software": [
        {
            "title": "Application error / update",
            "keywords": ["application", "app", "software", "update", "crash", "fehler", "error"],
            "action": "Reproduce the error; check for a pending update or known issue; "
            "clear the app cache or reinstall via the software deployment tool.",
            "source": "kb://software/app-error",
        },
    ],
    "Account": [
        {
            "title": "Password reset / locked account",
            "keywords": ["password", "passwort", "login", "locked", "gesperrt", "konto", "account"],
            "action": "Verify identity per policy, then reset the password / unlock the "
            "account in the directory; enforce a change at next logon.",
            "source": "kb://account/password-reset",
        },
    ],
}


class MockKnowledgeBase:
    """In-memory KB with naive keyword-overlap scoring (Qdrant stand-in)."""

    def retrieve(self, category: str, query: str, k: int = 1) -> list[KBDoc]:
        entries = _PLAYBOOK.get(category, [])
        q = query.lower()
        scored: list[KBDoc] = []
        for e in entries:
            hits = sum(1 for kw in e["keywords"] if kw in q)
            score = hits / max(len(e["keywords"]), 1)
            scored.append(KBDoc(title=e["title"], action=e["action"], source=e["source"], score=score))

        # Best match first; if nothing matched, still return the category default.
        scored.sort(key=lambda d: d.score, reverse=True)
        return scored[:k]


# ---------------------------------------------------------------------------
# Qdrant-backed knowledge base (vector search via rag_engine)
# ---------------------------------------------------------------------------
class QdrantKnowledgeBase:
    """Implements the same ``retrieve`` contract using Qdrant vector search."""

    def retrieve(self, category: str, query: str, k: int = 1) -> list[KBDoc]:
        import rag_engine

        # Semantic search filtered to the analyzed category.
        hits = rag_engine.search(query=query, k=k, category=category)
        # If the category filter is too strict (no hits), retry unfiltered.
        if not hits:
            hits = rag_engine.search(query=query, k=k)
        return [
            KBDoc(title=h["title"], action=h["text"], source=h["source"], score=h["score"])
            for h in hits
        ]


# ---------------------------------------------------------------------------
# Factory — single seam that selects Qdrant when it's available
# ---------------------------------------------------------------------------
_DEFAULT_KB: KnowledgeBase | None = None


def get_knowledge_base() -> KnowledgeBase:
    """Return the active knowledge base (cached).

    Uses Qdrant when ``QDRANT_URL`` is set and the server is reachable; otherwise
    falls back to the in-memory mock so the prototype always works.
    """
    global _DEFAULT_KB
    if _DEFAULT_KB is None:
        _DEFAULT_KB = _build_kb()
    return _DEFAULT_KB


def _build_kb() -> KnowledgeBase:
    if os.getenv("QDRANT_URL"):
        try:
            import rag_engine

            if rag_engine.is_ready():
                return QdrantKnowledgeBase()
        except Exception:
            pass
    return MockKnowledgeBase()
