"""
EduGuard BW — Qdrant RAG engine.

Self-hosted retrieval for IT knowledge. Embeddings come from a **local** source:
the Ollama embedding model when available, otherwise a deterministic hashed
bag-of-words vector so the prototype works with zero extra model pulls. Either
way, no document or query ever leaves the host.

Public surface (used by the triage graph):
  * init_rag()                  -> create collection + seed mock docs (idempotent)
  * is_ready()                  -> True if Qdrant is reachable
  * search(query, k, category)  -> list[dict] of relevant docs with scores
"""
from __future__ import annotations

import hashlib
import math
import os

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
EMBED_MODEL = os.getenv("EMBED_MODEL", "nomic-embed-text")
COLLECTION = "it_knowledge_base"

HASH_DIM = 256  # dimensionality of the deterministic fallback embedding

# --- Guarded import so the module loads even without qdrant-client installed --
try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointStruct,
        VectorParams,
    )

    _QDRANT_IMPORTED = True
except Exception:  # pragma: no cover - env dependent
    _QDRANT_IMPORTED = False


# ---------------------------------------------------------------------------
# Mock IT support documents (seeded into Qdrant)
# ---------------------------------------------------------------------------
DOCUMENTS: list[dict] = [
    {
        "id": 1,
        "title": "Smartboard HDMI reset process",
        "category": "Hardware",
        "source": "kb://hardware/smartboard-hdmi",
        "text": (
            "When a smartboard shows 'No Signal': power the panel off and unplug it for "
            "30 seconds. Reseat the HDMI cable at both ends, then select the correct HDMI "
            "input on the panel. If still blank, connect a known-good laptop to verify the "
            "cable, and check that the room PC is powered on and not in standby."
        ),
    },
    {
        "id": 2,
        "title": "Teacher Wi-Fi password policy",
        "category": "Network",
        "source": "kb://network/teacher-wifi",
        "text": (
            "The Teacher WLAN (SSID 'Staff') uses WPA2-Enterprise tied to the staff "
            "directory account. Passwords rotate each semester. If a teacher cannot "
            "connect, confirm their account is not locked, have them forget and rejoin "
            "the SSID, and re-enter their current directory credentials."
        ),
    },
    {
        "id": 3,
        "title": "Student network access rules",
        "category": "Network",
        "source": "kb://network/student-access",
        "text": (
            "Student devices on the Student VLAN are restricted to HTTPS (443) web access "
            "through the content filter. Ports like RDP (3389) and SMB (445) are blocked by "
            "policy. Any student host exposing these ports should be quarantined and "
            "reported as a security anomaly."
        ),
    },
    {
        "id": 4,
        "title": "Account password reset procedure",
        "category": "Account",
        "source": "kb://account/password-reset",
        "text": (
            "To reset a locked or forgotten account: verify the requester's identity per "
            "school policy (in person or via a known secondary channel), then reset the "
            "password in the directory and require a change at next logon. Never send "
            "passwords over email or chat."
        ),
    },
]


# ---------------------------------------------------------------------------
# Embedder — local Ollama, with a deterministic hashed fallback
# ---------------------------------------------------------------------------
class _Embedder:
    def __init__(self) -> None:
        self.backend = "hash"
        self.dim = HASH_DIM
        self._ollama = None
        try:
            from langchain_ollama import OllamaEmbeddings

            emb = OllamaEmbeddings(base_url=OLLAMA_BASE_URL, model=EMBED_MODEL)
            probe = emb.embed_query("probe")  # also validates the model is present
            self._ollama = emb
            self.dim = len(probe)
            self.backend = "ollama"
        except Exception:
            # Ollama / embed model not available — keep the hashed fallback.
            self._ollama = None

    def embed(self, text: str) -> list[float]:
        if self._ollama is not None:
            try:
                return self._ollama.embed_query(text)
            except Exception:
                pass
        return self._hash_embed(text)

    def _hash_embed(self, text: str) -> list[float]:
        """Deterministic, normalized bag-of-words hash vector (no model needed)."""
        vec = [0.0] * self.dim
        for token in text.lower().split():
            h = int(hashlib.sha1(token.encode()).hexdigest(), 16)
            vec[h % self.dim] += 1.0
        norm = math.sqrt(sum(x * x for x in vec)) or 1.0
        return [x / norm for x in vec]


_client = None
_embedder: _Embedder | None = None


def get_client():
    global _client
    if not _QDRANT_IMPORTED:
        return None
    if _client is None:
        _client = QdrantClient(url=QDRANT_URL, timeout=5.0)
    return _client


def get_embedder() -> _Embedder:
    global _embedder
    if _embedder is None:
        _embedder = _Embedder()
    return _embedder


# ---------------------------------------------------------------------------
# Lifecycle
# ---------------------------------------------------------------------------
def is_ready() -> bool:
    """True if the Qdrant server is reachable."""
    client = get_client()
    if client is None:
        return False
    try:
        client.get_collections()
        return True
    except Exception:
        return False


def ensure_collection() -> None:
    client = get_client()
    if client is None:
        raise RuntimeError("qdrant-client is not installed")
    emb = get_embedder()

    existing = {c.name for c in client.get_collections().collections}
    if COLLECTION in existing:
        # Recreate if the stored vector size no longer matches the active
        # embedder (e.g. the hash fallback dim != Ollama embedding dim after a
        # model becomes available). Otherwise upserts fail with a dim error.
        try:
            info = client.get_collection(COLLECTION)
            current_dim = info.config.params.vectors.size
        except Exception:
            current_dim = None
        if current_dim == emb.dim:
            return
        client.delete_collection(COLLECTION)

    client.create_collection(
        collection_name=COLLECTION,
        vectors_config=VectorParams(size=emb.dim, distance=Distance.COSINE),
    )


def seed_documents() -> int:
    """Upsert the mock docs (idempotent — stable ids)."""
    client = get_client()
    if client is None:
        raise RuntimeError("qdrant-client is not installed")
    emb = get_embedder()
    points = [
        PointStruct(
            id=d["id"],
            vector=emb.embed(f"{d['title']} {d['text']}"),
            payload={
                "title": d["title"],
                "category": d["category"],
                "source": d["source"],
                "text": d["text"],
            },
        )
        for d in DOCUMENTS
    ]
    client.upsert(collection_name=COLLECTION, points=points)
    return len(points)


def init_rag() -> dict:
    """Create the collection and seed documents. Safe to call repeatedly."""
    ensure_collection()
    count = seed_documents()
    return {"collection": COLLECTION, "documents": count, "embedder": get_embedder().backend}


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------
def search(query: str, k: int = 3, category: str | None = None) -> list[dict]:
    """Return the top-k relevant docs for ``query``, optionally filtered by category."""
    client = get_client()
    if client is None:
        return []
    emb = get_embedder()

    qfilter = None
    if category:
        qfilter = Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))])

    try:
        hits = client.search(
            collection_name=COLLECTION,
            query_vector=emb.embed(query),
            query_filter=qfilter,
            limit=k,
        )
    except Exception:
        return []

    return [
        {
            "title": h.payload.get("title", ""),
            "text": h.payload.get("text", ""),
            "source": h.payload.get("source", ""),
            "category": h.payload.get("category", ""),
            "score": float(h.score),
        }
        for h in hits
    ]


if __name__ == "__main__":
    import json

    print("Qdrant ready:", is_ready())
    if is_ready():
        print(json.dumps(init_rag(), indent=2))
        print(json.dumps(search("smartboard no signal", k=2, category="Hardware"), indent=2))
