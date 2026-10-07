"""
NEXUS ERP — VEMA Complaints Router
  POST /api/complaints/voice/transcribe — audio -> transcript ONLY, no ticket
                                          (customer reviews/edits before submit)
  POST /api/complaints/voice   — submit a (confirmed) voice complaint (customer)
  POST /api/complaints/chat    — text chat complaint (customer)
  POST /api/complaints/manual  — manual ticket entry (CR/admin)
  GET  /api/complaints         — full ticket log, filterable (CR/admin)
  GET  /api/complaints/mine    — the logged-in customer's own tickets
  GET  /api/complaints/{id}    — ticket detail + full conversation history
  PATCH /api/complaints/{id}   — CR resolve / escalate
  DELETE /api/complaints/{id}  — customer withdraws their own complaint
                                 (only while it hasn't been escalated/resolved)
"""
import base64
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from rbac import require_role, get_current_user, ROLE_CUSTOMER, ROLE_CUSTOMER_REP
from taxonomy import all_categories, subtypes_for, reference_table
from rag.retrieval import retrieve
import stt_service
import tts_service
import llm_service
import vema_orchestrator

router = APIRouter(prefix="/api/complaints", tags=["Complaints"])
_customer = Depends(require_role(ROLE_CUSTOMER))
_cr = Depends(require_role(ROLE_CUSTOMER_REP))


def _ticket_to_dict(row: dict) -> dict:
    return dict(row)


# ────────────────────────────────────────────────────────────────────────────
# Customer Portal intake (Section 5b)
# ────────────────────────────────────────────────────────────────────────────

@router.post("/voice/transcribe", dependencies=[_customer])
async def transcribe_voice_complaint(audio: UploadFile = File(...)):
    """
    Speech-to-text only — does NOT create a ticket. The Customer Portal shows
    the transcript back to the customer (editable) so they can correct STT
    slips or re-record before committing. Submit the confirmed text to
    POST /api/complaints/voice.
    """
    audio_bytes = await audio.read()
    transcript = stt_service.transcribe(audio_bytes, audio.filename or "audio.webm")
    if not transcript["text"]:
        raise HTTPException(400, "Could not extract any speech from the audio — please try again.")
    return {
        "transcript": transcript["text"],
        "transcription_engine": transcript["engine"],
    }


class VoiceComplaintRequest(BaseModel):
    message: str          # the confirmed (possibly customer-edited) transcript
    area: Optional[str] = None


@router.post("/voice", dependencies=[_customer])
def submit_voice_complaint(req: VoiceComplaintRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    text_content = (req.message or "").strip()
    if not text_content:
        raise HTTPException(400, "Complaint text is empty")

    result = vema_orchestrator.create_ticket(
        db, description=text_content, channel="voice",
        customer_id=user["id"], customer_name=user["name"], customer_email=user["email"],
        area=req.area,
    )
    reply_text = llm_service.generate_chat_reply(text_content, result["ticket_code"])
    speech = tts_service.synthesize(reply_text)

    return {
        "ticket_code": result["ticket_code"],
        "ticket_id": result["ticket_id"],
        "reference_id": result["reference_id"],
        "related_ticket_reference": result.get("related_ticket_reference"),
        "transcript": text_content,
        "classification": result["classification"],
        "status": result["status"],
        "reply_text": reply_text,
        "reply_audio_base64": speech["audio_base64"],
        "reply_audio_available": speech["audio_available"],
    }


class ChatComplaintRequest(BaseModel):
    message: str
    area: Optional[str] = None


@router.post("/chat", dependencies=[_customer])
def submit_chat_complaint(req: ChatComplaintRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    result = vema_orchestrator.create_ticket(
        db, description=req.message, channel="chat",
        customer_id=user["id"], customer_name=user["name"], customer_email=user["email"],
        area=req.area,
    )
    reply_text = llm_service.generate_chat_reply(req.message, result["ticket_code"])
    return {
        "ticket_code": result["ticket_code"],
        "ticket_id": result["ticket_id"],
        "reference_id": result["reference_id"],
        "related_ticket_reference": result.get("related_ticket_reference"),
        "classification": result["classification"],
        "status": result["status"],
        "reply_text": reply_text,
    }


class ComplaintPreviewRequest(BaseModel):
    message: str


@router.post("/preview", dependencies=[_customer])
def preview_complaint(req: ComplaintPreviewRequest):
    """
    Read-only: classifies a draft complaint, flags whether it's actually
    in scope (a genuine complaint about this DISCO's electricity service),
    and suggests at most one clarifying follow-up question if something
    important seems missing — never creates a ticket, never writes to the
    DB. Lets the Customer Portal decline out-of-scope messages and ask one
    natural follow-up before filing, for both voice and typed chat. Same
    guardrail as the rest of RAG/LLM use in this app: this only ever
    suggests; /voice and /chat (above) remain the sole, deterministic
    ticket-creation path — always willing to file a ticket regardless of
    in_scope, unchanged by this endpoint's existence. classify_complaint()
    folds both decisions into its one call — see its docstring for why
    (Gemini's free-tier daily quota).
    """
    text_content = (req.message or "").strip()
    if not text_content:
        raise HTTPException(400, "Complaint text is empty")
    classification = llm_service.classify_complaint(text_content)
    followup_question = classification.pop("followup_question", None)
    in_scope = classification.pop("in_scope", True)
    return {"classification": classification, "followup_question": followup_question, "in_scope": in_scope}


@router.get("/mine", dependencies=[_customer])
def list_my_complaints(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT * FROM complaints WHERE customer_id = :cid ORDER BY created_at DESC"),
        {"cid": user["id"]},
    ).mappings().all()
    return {"tickets": [_ticket_to_dict(dict(r)) for r in rows]}


# ────────────────────────────────────────────────────────────────────────────
# CR / Admin — manual ticket creation, full log, detail, resolve/escalate
# ────────────────────────────────────────────────────────────────────────────

class ManualComplaintRequest(BaseModel):
    description: str
    category: str
    subtype: str
    severity: str = "medium"
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    area: Optional[str] = None


@router.post("/manual", dependencies=[_cr])
def create_manual_complaint(req: ManualComplaintRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.subtype not in subtypes_for(req.category):
        raise HTTPException(400, f"'{req.subtype}' is not a valid subtype of '{req.category}'")
    result = vema_orchestrator.create_ticket(
        db, description=req.description, channel="manual", vema_triggered=False,
        customer_name=req.customer_name, customer_email=req.customer_email, area=req.area,
        override_category=req.category, override_subtype=req.subtype, override_severity=req.severity,
        logged_by_actor=f"{user['role']}:{user['name']}",
    )
    return result


# "recent"   -> newest first (the log view — a just-filed ticket is always on top).
# "priority" -> critical before medium before small, then newest first
#               (triage view — but a new low-severity ticket sinks below the
#               whole critical backlog, which reads as "my ticket vanished").
_ORDER_CLAUSES = {
    "recent": "created_at DESC",
    "priority": (
        "CASE severity WHEN 'critical' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, "
        "created_at DESC"
    ),
}


@router.get("", dependencies=[_cr])
def list_complaints(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    search: Optional[str] = Query(None, description="Matches ticket_code, reference_id, or description"),
    order: str = Query("recent"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    order_by = _ORDER_CLAUSES.get(order, _ORDER_CLAUSES["recent"])
    filters = "WHERE 1=1"
    params: dict = {"limit": limit, "offset": offset}
    if status:
        filters += " AND status = :status"
        params["status"] = status
    if category:
        filters += " AND category = :category"
        params["category"] = category
    if severity:
        filters += " AND severity = :severity"
        params["severity"] = severity
    if search:
        filters += " AND (ticket_code ILIKE :search OR reference_id ILIKE :search OR description ILIKE :search)"
        params["search"] = f"%{search}%"

    rows = db.execute(
        text(f"""
            SELECT * FROM complaints {filters}
            ORDER BY {order_by}
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()
    total = db.execute(text(f"SELECT COUNT(*) FROM complaints {filters}"), params).scalar()
    return {"total": total, "tickets": [_ticket_to_dict(dict(r)) for r in rows]}


@router.get("/taxonomy")
def get_taxonomy():
    """Public reference data for building manual-entry / filter dropdowns."""
    return {cat: subtypes_for(cat) for cat in all_categories()}


@router.get("/categories")
def get_categories(db: Session = Depends(get_db)):
    """
    Feature B — the "Complaint Categories" reference view. One source of
    truth (taxonomy.py) plus live ticket counts; admin and CR both read this,
    nothing duplicates the category list on the frontend.
    """
    counts = dict(db.execute(
        text("SELECT category, COUNT(*) AS n FROM complaints GROUP BY category")
    ).all())
    return [
        {**record, "ticket_count": counts.get(record["category"], 0)}
        for record in reference_table()
    ]


@router.get("/{ticket_id}")
def get_complaint(ticket_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.execute(text("SELECT * FROM complaints WHERE id = :id"), {"id": ticket_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Ticket not found")
    if user["role"] == ROLE_CUSTOMER and str(row["customer_id"]) != user["id"]:
        raise HTTPException(403, "Not your ticket")

    events = db.execute(
        text("SELECT * FROM complaint_events WHERE complaint_id = :id ORDER BY created_at ASC"),
        {"id": ticket_id},
    ).mappings().all()
    return {"ticket": _ticket_to_dict(dict(row)), "events": [dict(e) for e in events]}


@router.get("/{ticket_id}/similar", dependencies=[_cr])
def get_similar_resolved_cases(ticket_id: str, db: Session = Depends(get_db)):
    """
    Feature D — up to 3 anonymized similar resolved cases for staff, to help
    resolve faster. Staff-only (customer role can never reach this — the
    dependency requires ROLE_CUSTOMER_REP, which require_role() also grants
    to admin, never to a customer). Retrieval only; never shown to customers.
    """
    row = db.execute(text("SELECT category, subtype, description FROM complaints WHERE id = :id"), {"id": ticket_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Ticket not found")

    results = retrieve(
        db, f"{row['category']} {row['subtype']} {row['description']}",
        doc_type="resolved_ticket", top_k=3,
    )
    return {
        "cases": [
            {
                "ticket_code": r.metadata.get("ticket_code"),
                "category": r.category,
                "summary": r.question,
                "resolution": r.answer,
                "score": round(r.score, 3),
            }
            for r in results
        ]
    }


class UpdateComplaintRequest(BaseModel):
    action: str  # resolve | escalate
    resolution: Optional[str] = None
    note: Optional[str] = None


@router.patch("/{ticket_id}", dependencies=[_cr])
def update_complaint(ticket_id: str, req: UpdateComplaintRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.action == "resolve":
        if not req.resolution:
            raise HTTPException(400, "resolution is required to resolve a ticket")
        code = vema_orchestrator.cr_resolve_ticket(db, ticket_id, req.resolution, user["id"], actor=f"{user['role']}:{user['name']}")
        if not code:
            raise HTTPException(404, "Ticket not found")
        return {"message": f"Ticket {code} marked resolved."}
    elif req.action == "escalate":
        code = vema_orchestrator.cr_escalate_to_admin(db, ticket_id, user["id"], req.note or "", actor=f"{user['role']}:{user['name']}")
        if not code:
            raise HTTPException(404, "Ticket not found")
        return {"message": f"Ticket {code} escalated to Admin."}
    else:
        raise HTTPException(400, "action must be 'resolve' or 'escalate'")


# Statuses a customer is still allowed to withdraw their own complaint from.
# Once a CR is on it (escalated) or it's closed (resolved), it stays on record.
_DELETABLE_BY_CUSTOMER = ("open", "auto_resolved")


@router.delete("/{ticket_id}", dependencies=[_customer])
def delete_complaint(ticket_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT ticket_code, customer_id, status FROM complaints WHERE id = :id"),
        {"id": ticket_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Ticket not found")
    if user["role"] == ROLE_CUSTOMER and str(row["customer_id"]) != user["id"]:
        raise HTTPException(403, "Not your ticket")
    if row["status"] not in _DELETABLE_BY_CUSTOMER:
        raise HTTPException(
            409,
            "This complaint is already being handled by a representative or has "
            "been resolved, so it can no longer be withdrawn.",
        )

    # complaint_events rows cascade (ON DELETE CASCADE in migration 004).
    db.execute(text("DELETE FROM complaints WHERE id = :id"), {"id": ticket_id})
    db.commit()
    return {"message": f"Complaint {row['ticket_code']} withdrawn."}
