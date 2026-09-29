"""
NEXUS ERP — RAG resolved_ticket source (Feature D, source 2)
Anonymized summaries of RESOLVED tickets only, used for (a) "similar
resolved cases" shown to staff on a ticket's detail view, and (b) as
few-shot grounding during classification. See rag/pii.py's module docstring
for the two-layer PII defense this relies on: the retrieval "question" is
built from category+subtype (fixed taxonomy vocabulary, no free text) —
never the customer's own complaint description — and the resolution note
("answer") is regex-scrubbed on top of that.

Controlled by RAG_INDEX_RESOLVED_TICKETS (default: see env.example) — a
project-level privacy decision, not something this module decides for you.
"""
import os
from typing import Optional
from sqlalchemy import text
from sqlalchemy.orm import Session

from rag.vector_store import store, RagDocument
from rag.pii import scrub_text

RAG_INDEX_RESOLVED_TICKETS = os.getenv("RAG_INDEX_RESOLVED_TICKETS", "true").lower() == "true"


def _document_for_ticket(row: dict) -> Optional[RagDocument]:
    resolution = scrub_text(row.get("resolution"), customer_name=row.get("customer_name"))
    if not resolution:
        return None  # nothing useful to show staff without a resolution note
    return RagDocument(
        doc_type="resolved_ticket",
        question=f"{row['category']} — {row['subtype']}",
        answer=resolution,
        category=row["category"],
        source=str(row["id"]),
        related_ticket_id=str(row["id"]),
        metadata={"severity": row["severity"], "ticket_code": row["ticket_code"]},
    )


def rebuild_resolved_ticket_index(db: Session) -> int:
    """Idempotent full rebuild — wipes and re-indexes every resolved ticket
    that has a resolution note. Returns 0 without touching anything if
    RAG_INDEX_RESOLVED_TICKETS is off."""
    if not RAG_INDEX_RESOLVED_TICKETS:
        print("[RAG] RAG_INDEX_RESOLVED_TICKETS is off — skipping resolved-ticket indexing")
        return 0

    store.delete(db, doc_type="resolved_ticket")
    rows = db.execute(text("""
        SELECT id, ticket_code, category, subtype, severity, resolution, customer_name
        FROM complaints
        WHERE status IN ('resolved', 'auto_resolved') AND resolution IS NOT NULL
    """)).mappings().all()

    documents = []
    for row in rows:
        try:
            doc = _document_for_ticket(dict(row))
            if doc:
                documents.append(doc)
        except Exception as e:
            # One bad ticket must never abort indexing the rest.
            print(f"[WARN] skipped ticket {row.get('ticket_code')} during resolved-ticket indexing: {e}")
            continue

    return store.upsert(db, documents) if documents else 0


def index_single_resolved_ticket(db: Session, ticket_id: str) -> bool:
    """Incremental indexing hook — called (non-fatally) right after a ticket
    is resolved, so the corpus doesn't go stale until the next full reindex.
    Returns False (never raises) on any failure."""
    if not RAG_INDEX_RESOLVED_TICKETS:
        return False
    try:
        row = db.execute(text("""
            SELECT id, ticket_code, category, subtype, severity, resolution, customer_name, status
            FROM complaints WHERE id = :id
        """), {"id": ticket_id}).mappings().first()
        if not row or row["status"] not in ("resolved", "auto_resolved"):
            return False
        doc = _document_for_ticket(dict(row))
        if not doc:
            return False
        store.upsert(db, [doc])
        return True
    except Exception as e:
        print(f"[WARN] non-fatal: failed to index resolved ticket {ticket_id} for RAG: {e}")
        return False
