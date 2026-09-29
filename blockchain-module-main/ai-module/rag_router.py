"""
NEXUS ERP — RAG API (Features C + D)
  POST /api/rag/query    — grounded Q&A for a customer's question (any role)
  POST /api/rag/ingest   — upload + ingest a Q&A dataset file (admin only)
  GET  /api/rag/stats    — doc counts per source, last ingest time (admin/CR)
  POST /api/rag/reindex  — rebuild category_kb + resolved_ticket (admin only)
"""
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from rbac import require_role, get_current_user, ROLE_ADMIN, ROLE_CUSTOMER_REP
from rag.retrieval import retrieve
from rag.generation import generate_answer
from rag.intent import classify_intent, COMPLAINT_INTENT, QUESTION_INTENT, SMALLTALK_INTENT
from rag.vector_store import store
from rag.ingest import ingest_file
from rag.category_kb import rebuild_category_kb
from rag.resolved_tickets import rebuild_resolved_ticket_index

router = APIRouter(prefix="/api/rag", tags=["RAG"])
_admin = Depends(require_role(ROLE_ADMIN))
_staff = Depends(require_role(ROLE_CUSTOMER_REP))  # implicitly includes admin, per rbac.require_role


class RagQueryRequest(BaseModel):
    question: str
    category: Optional[str] = None


@router.post("/query")
def rag_query(req: RagQueryRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    The informational Q&A path (Feature C). Never creates a ticket — if the
    message reads as a complaint, the frontend is told to route it into the
    existing (unchanged) POST /api/complaints/chat|voice flow instead.
    """
    question = (req.question or "").strip()
    if not question:
        raise HTTPException(400, "question is empty")

    intent = classify_intent(question)

    if intent == SMALLTALK_INTENT:
        return {
            "reply": "Hi! I can answer questions about your electricity service, or log a complaint for you — what do you need?",
            "intent": intent, "grounded": True, "sources": [], "retrieval_scores": [],
        }

    if intent == COMPLAINT_INTENT:
        return {
            "reply": "This sounds like something we should file as a complaint so it gets tracked and actioned.",
            "intent": intent, "grounded": False, "sources": [], "retrieval_scores": [],
        }

    results = retrieve(db, question, doc_type="qa", category=req.category)
    answer = generate_answer(question, results)
    return {**answer, "intent": intent}


@router.post("/ingest", dependencies=[_admin])
async def rag_ingest(file: UploadFile = File(...)):
    suffix = Path(file.filename or "upload").suffix or ".jsonl"
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        shutil.copyfileobj(file.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        report = ingest_file(tmp_path, source_name=file.filename)
    finally:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
    return {
        "ingested": report.ingested,
        "skipped": len(report.skipped),
        "duplicates": len(report.duplicates),
        "skip_reasons": [reason for _, reason in report.skipped[:20]],
    }


@router.get("/stats", dependencies=[_staff])
def rag_stats(db: Session = Depends(get_db)):
    rows = db.execute(text("""
        SELECT doc_type, COUNT(*) AS count, MAX(updated_at) AS last_updated
        FROM rag_documents GROUP BY doc_type
    """)).mappings().all()
    by_type = {r["doc_type"]: {"count": r["count"], "last_updated": r["last_updated"]} for r in rows}
    return {
        "total": sum(v["count"] for v in by_type.values()),
        "by_doc_type": by_type,
        "embedding_backend": __import__("rag.embeddings", fromlist=["EMBEDDING_BACKEND"]).EMBEDDING_BACKEND,
    }


@router.post("/reindex", dependencies=[_admin])
def rag_reindex(db: Session = Depends(get_db)):
    category_count = rebuild_category_kb(db)
    ticket_count = rebuild_resolved_ticket_index(db)
    return {"category_kb_documents": category_count, "resolved_ticket_documents": ticket_count}
