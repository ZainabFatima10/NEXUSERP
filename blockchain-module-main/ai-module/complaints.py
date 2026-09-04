"""
NEXUS ERP — VEMA Complaints Router
  POST /api/complaints/voice   — push-to-talk voice complaint (customer)
  POST /api/complaints/chat    — text chat complaint (customer)
  POST /api/complaints/manual  — manual ticket entry (CR/admin)
  GET  /api/complaints         — full ticket log, filterable (CR/admin)
  GET  /api/complaints/mine    — the logged-in customer's own tickets
  GET  /api/complaints/{id}    — ticket detail + full conversation history
  PATCH /api/complaints/{id}   — CR resolve / escalate
"""
import base64
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from rbac import require_role, get_current_user, ROLE_CUSTOMER, ROLE_CUSTOMER_REP
from taxonomy import all_categories, subtypes_for
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

@router.post("/voice", dependencies=[_customer])
async def submit_voice_complaint(
    audio: UploadFile = File(...),
    area: Optional[str] = Form(None),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    audio_bytes = await audio.read()
    transcript = stt_service.transcribe(audio_bytes, audio.filename or "audio.webm")
    text_content = transcript["text"]
    if not text_content:
        raise HTTPException(400, "Could not extract any speech from the audio")

    result = vema_orchestrator.create_ticket(
        db, description=text_content, channel="voice",
        customer_id=user["id"], customer_name=user["name"], customer_email=user["email"],
        area=area,
    )
    reply_text = llm_service.generate_chat_reply(text_content, result["ticket_code"])
    speech = tts_service.synthesize(reply_text)

    return {
        "ticket_code": result["ticket_code"],
        "ticket_id": result["ticket_id"],
        "transcript": text_content,
        "transcription_engine": transcript["engine"],
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
        "classification": result["classification"],
        "status": result["status"],
        "reply_text": reply_text,
    }


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
def create_manual_complaint(req: ManualComplaintRequest, db: Session = Depends(get_db)):
    if req.subtype not in subtypes_for(req.category):
        raise HTTPException(400, f"'{req.subtype}' is not a valid subtype of '{req.category}'")
    result = vema_orchestrator.create_ticket(
        db, description=req.description, channel="manual", vema_triggered=False,
        customer_name=req.customer_name, customer_email=req.customer_email, area=req.area,
        override_category=req.category, override_subtype=req.subtype, override_severity=req.severity,
    )
    return result


@router.get("", dependencies=[_cr])
def list_complaints(
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    severity: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
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

    rows = db.execute(
        text(f"""
            SELECT * FROM complaints {filters}
            ORDER BY
              CASE severity WHEN 'critical' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
              created_at DESC
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


class UpdateComplaintRequest(BaseModel):
    action: str  # resolve | escalate
    resolution: Optional[str] = None
    note: Optional[str] = None


@router.patch("/{ticket_id}", dependencies=[_cr])
def update_complaint(ticket_id: str, req: UpdateComplaintRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.action == "resolve":
        if not req.resolution:
            raise HTTPException(400, "resolution is required to resolve a ticket")
        code = vema_orchestrator.cr_resolve_ticket(db, ticket_id, req.resolution, user["id"])
        if not code:
            raise HTTPException(404, "Ticket not found")
        return {"message": f"Ticket {code} marked resolved."}
    elif req.action == "escalate":
        code = vema_orchestrator.cr_escalate_to_admin(db, ticket_id, user["id"], req.note or "")
        if not code:
            raise HTTPException(404, "Ticket not found")
        return {"message": f"Ticket {code} escalated to Admin."}
    else:
        raise HTTPException(400, "action must be 'resolve' or 'escalate'")
