-- ============================================================
-- NEXUS ERP — Migration 007
-- Features C + D: the shared retrieval store both the Q&A path and the
-- RAG-grounded complaint path read from (rag/vector_store.py). One table,
-- distinguished by doc_type:
--   'qa'             — Feature C's ingested question/answer datasets
--   'category_kb'    — Feature D's auto-built-from-taxonomy category reference
--   'resolved_ticket'— Feature D's PII-scrubbed anonymized resolved tickets
--
-- embedding is vector(512) to match rag/embeddings.py's tested default
-- (scikit-learn HashingVectorizer — see VEMA_RAG.md "Embedding model" for
-- why: sentence-transformers/torch cannot load on this machine, blocked by
-- a Windows Application Control policy, confirmed by testing, not assumed).
-- If you swap in a different embedding backend with a different output
-- dimension (e.g. Mistral's mistral-embed at 1024), you must
-- `ALTER TABLE rag_documents ALTER COLUMN embedding TYPE vector(<new dim>)`
-- and re-ingest everything — this migration does not attempt to support
-- multiple dimensions in one column.
--
-- Idempotent — safe to re-run on every startup.
-- ============================================================

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    doc_type            VARCHAR(20) NOT NULL,
    -- qa | category_kb | resolved_ticket
    question            TEXT NOT NULL,
    -- The retrieval key: a Q&A pair's question, a category's description +
    -- example phrases concatenated, or a resolved ticket's (PII-scrubbed)
    -- problem summary.
    answer              TEXT NOT NULL,
    -- The Q&A pair's answer, the category's guidance text, or the resolved
    -- ticket's resolution note.
    category            VARCHAR(100),
    language            VARCHAR(10) DEFAULT 'en',
    source              VARCHAR(255),
    -- Dataset filename (qa), 'taxonomy' (category_kb), or the ticket's id
    -- (resolved_ticket) — never a customer-identifying value.
    related_ticket_id   UUID REFERENCES complaints(id) ON DELETE SET NULL,
    embedding           vector(512),
    metadata            JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_rag_documents_doc_type  ON rag_documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_rag_documents_category  ON rag_documents(category);
-- No ANN index (ivfflat/hnsw) yet — the seed/demo corpus is small enough
-- that an exact sequential scan over <=> is both simpler and fast enough.
-- Add one (`CREATE INDEX ... USING ivfflat (embedding vector_cosine_ops)`)
-- once the corpus is large enough that a full scan is actually slow.

-- Feature D — duplicate/known-issue awareness: a new ticket may point at an
-- already-open ticket instead of (not "rather than", per the spec: creation
-- is never blocked) being created in isolation.
ALTER TABLE complaints ADD COLUMN IF NOT EXISTS related_ticket_id UUID REFERENCES complaints(id);
