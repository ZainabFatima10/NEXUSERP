"""
NEXUS ERP — RAG Retrieval (Feature C)
Thin, configurable wrapper over vector_store.search with the env-driven
defaults the spec asks for (top-k, similarity threshold) — PLUS a lexical
overlap gate that turned out to be necessary once tested against a real,
multi-document corpus rather than a 1-2 document smoke test (see
VEMA_RAG.md "A gap the eval script caught" for the full story):

HashingVectorizer cosine scores do not reliably separate in-domain from
out-of-domain text on their own. Against the real seed corpus, "what is the
capital of france" scored 0.38 against an unrelated Q&A pair — HIGHER than
several genuinely relevant paraphrases score against their own match. The
512-dim hash space is small enough that short strings collide into
overlapping buckets regardless of actual meaning; cosine similarity alone
cannot tell "shares real words" from "coincidentally hashes near". A real
semantic embedding model would not have this specific failure mode, but
isn't usable here (see embeddings.py).

The fix: a result only counts as "found" if it ALSO shares at least one
real (non-stopword, length > 3) token with the query — cheap, deterministic,
and it directly fixes the demonstrated false-positive without needing
semantic embeddings. min_score stays as a first-pass filter on top of this,
not instead of it.
"""
import os
import re
from typing import List, Optional
from sqlalchemy.orm import Session

from rag.vector_store import store, RagSearchResult

RAG_TOP_K = int(os.getenv("RAG_TOP_K", "5"))
RAG_MIN_SIMILARITY = float(os.getenv("RAG_MIN_SIMILARITY", "0.05"))

_STOPWORDS = {
    "what", "when", "where", "which", "who", "why", "how", "the", "and",
    "for", "are", "you", "can", "with", "have", "this", "that", "does",
    "will", "there", "your", "about", "from", "into", "much", "many",
}
_WORD_RE = re.compile(r"[a-z]{4,}")


def _significant_tokens(text: str) -> set:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in _STOPWORDS}


def _shares_a_real_word(query: str, candidate: str) -> bool:
    query_tokens = _significant_tokens(query)
    if not query_tokens:
        return True  # nothing to check against (e.g. a very short query) — don't over-reject
    return bool(query_tokens & _significant_tokens(candidate))


def retrieve(
    db: Session, query: str, doc_type: Optional[str] = None,
    category: Optional[str] = None, top_k: Optional[int] = None,
    min_score: Optional[float] = None,
) -> List[RagSearchResult]:
    k = top_k if top_k is not None else RAG_TOP_K
    threshold = min_score if min_score is not None else RAG_MIN_SIMILARITY
    # Over-fetch before the lexical gate narrows results down, so a genuine
    # match ranked 4th by the (noisy) vector score isn't lost just because
    # 3 spurious higher-scoring hits get filtered out ahead of it.
    candidates = store.search(db, query, top_k=k * 3, doc_type=doc_type, category=category, min_score=threshold)
    filtered = [r for r in candidates if _shares_a_real_word(query, r.question) or _shares_a_real_word(query, r.answer)]
    return filtered[:k]
