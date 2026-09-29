"""
NEXUS ERP — RAG Embeddings (Feature C)

Decision history, made by testing rather than assuming (see VEMA_RAG.md
"Embedding model"): a local sentence-transformers model was the original
plan, but `sentence-transformers`/`torch` cannot load on this machine —
Windows Application Control blocks torch.dll outright (OSError WinError
4551), not a pip/version problem. Mistral's embedding API was the next
choice, but Mistral's paid tier wasn't workable for the team, so the
provider priority is now:

  1. Gemini embeddings (`GEMINI_API_KEY`, `text-embedding-004`, 768-dim) —
     free tier, no card required. NOT LIVE-TESTED in this environment (no
     key configured here) — coded and disclosed as such, same status every
     other "add your own key" integration in this codebase carries until
     someone actually runs it with a real key.
  2. scikit-learn HashingVectorizer (768-dim, matched to Gemini's width so
     the schema never needs to change again just because the provider
     did) — stateless, no fitted vocabulary, no model download, no torch.
     This is the path every test and the eval script in this repo actually
     exercises.

EMBEDDING_DIM (768) MUST match migration 008's `vector(768)` column. If you
introduce a third backend with a different output width, you must widen the
column again and re-ingest everything — see 008's comment block.
"""
import os
from functools import lru_cache
from typing import List

import httpx
from dotenv import load_dotenv

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "text-embedding-004")
GEMINI_BATCH_EMBED_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:batchEmbedContents"
)

EMBEDDING_DIM = 768  # Gemini text-embedding-004's native width — see module docstring
EMBEDDING_BACKEND = "gemini" if GEMINI_API_KEY else "hashing"

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


def _embed_with_gemini(texts: List[str]) -> List[List[float]]:
    url = GEMINI_BATCH_EMBED_URL_TEMPLATE.format(model=GEMINI_EMBEDDING_MODEL)
    model_path = f"models/{GEMINI_EMBEDDING_MODEL}"
    resp = httpx.post(
        url,
        params={"key": GEMINI_API_KEY},
        json={"requests": [{"model": model_path, "content": {"parts": [{"text": t}]}} for t in texts]},
        timeout=30.0,
    )
    resp.raise_for_status()
    embeddings = resp.json()["embeddings"]
    return [e["values"] for e in embeddings]


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Returns one embedding vector per input text, in order. Never raises —
    falls back to the hashing backend if the Gemini call fails, so a flaky
    network never breaks ingestion or retrieval."""
    if not texts:
        return []
    if EMBEDDING_BACKEND == "gemini":
        try:
            return _embed_with_gemini(texts)
        except Exception as e:
            print(f"[WARN] Gemini embeddings failed ({e}), falling back to local hashing embeddings")
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
