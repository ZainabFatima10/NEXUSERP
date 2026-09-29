-- ============================================================
-- NEXUS ERP — Migration 008
-- Widen rag_documents.embedding from vector(512) to vector(768).
--
-- Provider swap: the LLM/embedding provider priority moved to Gemini
-- (free tier, no card required) as primary, since Mistral's paid tier
-- wasn't workable for the team. Gemini's text-embedding-004 is natively
-- 768-dim — the local scikit-learn HashingVectorizer fallback (used when no
-- API key is configured) was widened to match, so the schema only needs to
-- support one dimension regardless of which backend is actually active.
--
-- pgvector enforces the declared dimension on every row, so widening the
-- column type while 512-dim rows still exist would fail outright — the
-- existing corpus is wiped first. This is safe: rag_documents holds a
-- rebuildable index (Q&A dataset, taxonomy-derived category_kb, resolved-
-- ticket summaries), not a system of record — re-ingest with
-- `python -m rag.ingest --path data/qa/ --rebuild` and
-- `POST /api/rag/reindex` after this runs.
--
-- Idempotent — safe to re-run on every startup (re-running a no-op ALTER on
-- an already-vector(768) column, and DELETE on an empty/768-dim table, are
-- both harmless).
-- ============================================================

DELETE FROM rag_documents;
ALTER TABLE rag_documents ALTER COLUMN embedding TYPE vector(768);
