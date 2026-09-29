"""
NEXUS ERP — RAG Embeddings (Feature C)

Decision, made by testing rather than assuming (see VEMA_RAG.md "Embedding
model" for the write-up): a local sentence-transformers model was the
original plan, but `sentence-transformers`/`torch` cannot load on this
machine — Windows Application Control blocks torch.dll outright
(OSError WinError 4551), not a pip/version problem. Two backends instead,
selected the same way every other external-API dependency in this codebase
already is (MISTRAL_API_KEY set -> real thing; unset -> a deterministic
local fallback that keeps the whole pipeline testable):

  - Mistral embeddings API (`mistral-embed`, 1024-dim) when MISTRAL_API_KEY
    is set. Coded but NOT live-tested in this environment (no key here) —
    flagged honestly rather than claimed as verified.
  - scikit-learn HashingVectorizer (512-dim) otherwise — no fitted
    vocabulary to persist (stateless, deterministic per input text), no
    torch, no model download. This is the path actually exercised by every
    test and eval script in this repo. Weaker than real semantic embeddings
    (term-hashing, not meaning) — a legitimate but disclosed dev-mode
    fallback, same spirit as llm_service._keyword_classify.

EMBEDDING_DIM (512) MUST match migration 007's `vector(512)` column. If you
switch to the Mistral backend (1024-dim) or a real sentence-transformers
model on a machine without this environment's DLL block, you must widen the
column and re-ingest everything — see 007's comment block.
"""
import os
from functools import lru_cache
from typing import List

import httpx
from dotenv import load_dotenv

load_dotenv()

MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
RAG_EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", "mistral-embed")
EMBEDDING_DIM = 512  # HashingVectorizer output width — see module docstring
MISTRAL_EMBED_URL = "https://api.mistral.ai/v1/embeddings"

EMBEDDING_BACKEND = "mistral" if MISTRAL_API_KEY else "hashing"

_hashing_vectorizer = None


def _get_hashing_vectorizer():
    global _hashing_vectorizer
    if _hashing_vectorizer is None:
        from sklearn.feature_extraction.text import HashingVectorizer
        _hashing_vectorizer = HashingVectorizer(
            n_features=EMBEDDING_DIM,
            alternate_sign=False,  # non-negative features - slightly better for cosine sim here
            norm="l2",
            ngram_range=(1, 2),  # bigrams help short-phrase matching (e.g. "no electricity")
        )
    return _hashing_vectorizer


def _embed_with_hashing(texts: List[str]) -> List[List[float]]:
    vec = _get_hashing_vectorizer()
    matrix = vec.transform(texts)  # stateless — no .fit() needed
    return matrix.toarray().tolist()


def _embed_with_mistral(texts: List[str]) -> List[List[float]]:
    resp = httpx.post(
        MISTRAL_EMBED_URL,
        headers={"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"},
        json={"model": RAG_EMBEDDING_MODEL, "input": texts},
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()["data"]
    return [row["embedding"] for row in data]


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Returns one embedding vector per input text, in order. Never raises —
    falls back to the hashing backend if the Mistral call fails, so a flaky
    network never breaks ingestion or retrieval."""
    if not texts:
        return []
    if EMBEDDING_BACKEND == "mistral":
        try:
            return _embed_with_mistral(texts)
        except Exception as e:
            print(f"[WARN] Mistral embeddings failed ({e}), falling back to local hashing embeddings")
    return _embed_with_hashing(texts)


@lru_cache(maxsize=256)
def _embed_single_cached(text: str) -> tuple:
    """LRU-cached single-text embedding (tuple so it's hashable for the
    cache) — repeated identical queries (a customer re-asking, or the eval
    script re-running) skip re-embedding."""
    return tuple(embed_texts([text])[0])


def embed_query(text: str) -> List[float]:
    return list(_embed_single_cached(text))


def to_pgvector_literal(embedding: List[float]) -> str:
    """pg8000 has no native pgvector adapter — bind this string and
    CAST(:embedding AS vector) in SQL, the same idiom this codebase already
    uses for jsonb (CAST(:x AS jsonb))."""
    return "[" + ",".join(f"{v:.8f}" for v in embedding) + "]"
