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
-- Idempotent — the DELETE is guarded by the column's CURRENT dimension so
-- it only fires the first time this runs against a pre-768-dim column.
-- No DO block here on purpose: database.py's migration runner splits each
-- file naively on the semicolon character (see CLAUDE.md's "Known gotchas"
-- and "Migrations" sections) and would shred a DO block's internal
-- statement separators into invalid fragments. A plain WHERE-subquery
-- guard keeps this one statement.
--
-- Without this guard, `run_schema()` re-applying every migration on EVERY
-- startup would wipe the entire rag_documents table on every single
-- restart forever, not just once during the 512->768 widen — a real bug
-- this repo hit live: a routine backend restart during testing silently
-- erased an already-ingested 38-document corpus with no error or warning.
-- The ALTER TABLE below stays unconditional — re-running it against an
-- already-vector(768) column is a no-op, not data loss.
-- ============================================================

DELETE FROM rag_documents
WHERE (
  SELECT atttypmod FROM pg_attribute
  WHERE attrelid = 'rag_documents'::regclass AND attname = 'embedding'
) IS DISTINCT FROM 768;
ALTER TABLE rag_documents ALTER COLUMN embedding TYPE vector(768);
