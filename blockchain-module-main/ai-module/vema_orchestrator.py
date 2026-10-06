"""
NEXUS ERP — VEMA Orchestration Service
Ties together llm_service (NLU + auto-resolution + chat replies),
notification_service, and email_service into the three-tier severity
routing described in Section 5c:

  small    -> auto-resolved by the system, no CR involvement
  medium   -> auto-resolution attempted first; if it fails, escalate to a
              CR and remind every 30 minutes until resolved
  critical -> escalate to a CR immediately, no auto-resolution attempt,
              remind every 15 minutes until resolved

Preserves the existing two-path lifecycle's spirit (auto-resolve vs
admin_pending) but extends it to three tiers as required.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from llm_service import classify_complaint, attempt_auto_resolution
from notification_service import notify_role, create_notification
from email_service import send_customer_resolution_email
from taxonomy import REMINDER_INTERVAL_MINUTES, CRITICAL, MEDIUM, SMALL, code_for


def _generate_reference_id(db: Session, category: str, max_attempts: int = 5) -> str:
    """
    VEMA-<CATEGORY CODE>-<YYYYMMDD>-<seq>, e.g. VEMA-POWER-20260929-004.
    Uses UTC date (matches TIMESTAMPTZ storage everywhere else in this
    codebase). seq is the next number for this category+day; the actual
    uniqueness guarantee comes from the DB's partial unique index
    (idx_complaints_reference_id, migration 006), not this count — a
    concurrent insert landing on the same seq raises IntegrityError, which
    the caller retries against a re-read count.
    """
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    prefix = f"VEMA-{code_for(category)}-{date_part}-"
    count = db.execute(
        text("SELECT COUNT(*) FROM complaints WHERE reference_id LIKE :p"),
        {"p": f"{prefix}%"},
    ).scalar() or 0
    return f"{prefix}{count + 1:03d}"


def _log_event(db: Session, complaint_id: str, event_type: str, actor: str, content: str, metadata: dict = None):
    db.execute(
        text("""
            INSERT INTO complaint_events (id, complaint_id, event_type, actor, content, metadata, created_at)
            VALUES (:id, :cid, :etype, :actor, :content, CAST(:metadata AS jsonb), NOW())
        """),
        {
            "id": str(uuid.uuid4()), "cid": complaint_id, "etype": event_type,
            "actor": actor, "content": content,
            "metadata": __import__("json").dumps(metadata or {}),
        },
    )


def create_ticket(
    db: Session,
    description: str,
    channel: str,                      # voice | chat | manual
    customer_id: Optional[str] = None,
    customer_name: Optional[str] = None,
    customer_email: Optional[str] = None,
    area: Optional[str] = None,
    vema_triggered: bool = True,
    override_category: Optional[str] = None,
    override_subtype: Optional[str] = None,
    override_severity: Optional[str] = None,
    logged_by_actor: Optional[str] = None,  # for channel="manual" -- who logged it, e.g. "customer_rep:Sara Malik"
) -> dict:
    """
    Classifies the complaint, creates the ticket + first conversation event,
    then routes it per its severity tier. Returns the created ticket row
    (as a dict) plus the routing outcome.
    """
    if override_category and override_subtype:
        classification = {
            "category": override_category,
            "subtype": override_subtype,
            "severity": override_severity or "medium",
            "summary": description.strip()[:200],
        }
    else:
        classification = classify_complaint(description)

    ticket_id = str(uuid.uuid4())
    ticket_code = "TKT-" + uuid.uuid4().hex[:6].upper()

    # reference_id (Feature B) has a real uniqueness guarantee only from the
    # DB's partial unique index (migration 006) — _generate_reference_id()'s
    # count is just a best-effort next-seq, so a concurrent insert landing on
    # the same value raises IntegrityError here; retry against a fresh count.
    for attempt in range(5):
        reference_id = _generate_reference_id(db, classification["category"])
        try:
            db.execute(
                text("""
                    INSERT INTO complaints (
                      id, ticket_code, reference_id, customer_id, customer_name, customer_email, channel,
                      category, subtype, severity, description, area, status, vema_triggered,
                      created_at, updated_at
                    ) VALUES (
                      :id, :code, :reference_id, :cust_id, :cust_name, :cust_email, :channel,
                      :category, :subtype, :severity, :description, :area, 'open', :vema_triggered,
                      NOW(), NOW()
                    )
                """),
                {
                    "id": ticket_id, "code": ticket_code, "reference_id": reference_id,
                    "cust_id": customer_id, "cust_name": customer_name, "cust_email": customer_email,
                    "channel": channel, "category": classification["category"], "subtype": classification["subtype"],
                    "severity": classification["severity"],
                    # Stored as the ticket's permanent description — prefer the
                    # classifier's one-sentence summary over the raw customer
                    # text, so a voice complaint that got a follow-up question
                    # folded in (see llm_service.classify_complaint) reads as a
                    # proper complaint record rather than a glued-together
                    # transcript ("Hi, my electricity isn't working.. I live in
                    # F-11."). Free: classify_complaint() already runs above for
                    # every ticket, so this costs no extra LLM call. In dev-mode
                    # / on any classify failure, summary IS the raw text (see
                    # _keyword_classify), so this is a no-op there — only
                    # changes behavior when the LLM actually ran. The verbatim
                    # customer words are preserved unchanged in the
                    # voice_transcript/chat_message event logged just below.
                    "description": classification.get("summary") or description,
                    "area": area,
                    "vema_triggered": vema_triggered,
                },
            )
            break
        except IntegrityError:
            db.rollback()
            if attempt == 4:
                raise

    actor = "customer" if channel in ("voice", "chat") else (logged_by_actor or "admin")
    _log_event(db, ticket_id, "voice_transcript" if channel == "voice" else "chat_message", actor, description)
    _log_event(
        db, ticket_id, "system_action", "vema",
        f"Classified as {classification['category']} / {classification['subtype']} "
        f"(severity: {classification['severity']}).",
        metadata=classification,
    )

    # RAG Feature D — duplicate/known-issue awareness. Never blocks creation
    # (the ticket above is already committed) — just links the new one to an
    # existing open report in the same category+area, if any, so staff see
    # the relation instead of two independent tickets for one outage.
    related = _find_duplicate_ticket(db, classification["category"], area, exclude_ticket_id=ticket_id)
    if related:
        db.execute(
            text("UPDATE complaints SET related_ticket_id = :rel WHERE id = :id"),
            {"rel": related["id"], "id": ticket_id},
        )
        _log_event(
            db, ticket_id, "system_action", "vema",
            f"Linked to existing open ticket {related['ticket_code']} — same category and area.",
            metadata={"related_ticket_id": str(related["id"]), "related_ticket_code": related["ticket_code"]},
        )
    db.commit()

    outcome = _route_ticket(db, ticket_id, ticket_code, classification["severity"], classification, customer_name, customer_email)
    if related:
        outcome["related_ticket_reference"] = related["reference_id"] or related["ticket_code"]
    return {
        "ticket_id": ticket_id, "ticket_code": ticket_code, "reference_id": reference_id,
        "classification": classification, **outcome,
    }


def _find_duplicate_ticket(db: Session, category: str, area: Optional[str], exclude_ticket_id: str) -> Optional[dict]:
    """
    Feature D duplicate/known-issue rule (proposed heuristic — flagged for
    team review, not a precise geo-match): an already-open (status=
    'escalated') ticket in the SAME category whose free-text `area` field
    overlaps this one's, checked case-insensitively in both directions
    ('G-11' should match 'G-11 Islamabad' and vice versa) since `area` has
    no controlled vocabulary in this schema — it's whatever the customer
    typed. Structured DB lookup only; no embedding similarity fallback on
    the description was added given the time budget for this pass (the
    spec allows this as a secondary check, not a required one).
    """
    if not area or not area.strip():
        return None
    row = db.execute(
        text("""
            SELECT id, ticket_code, reference_id, area FROM complaints
            WHERE category = :category AND status = 'escalated' AND id != :exclude
              AND area IS NOT NULL AND area != ''
              AND (area ILIKE '%' || :area || '%' OR :area ILIKE '%' || area || '%')
            ORDER BY created_at DESC LIMIT 1
        """),
        {"category": category, "exclude": exclude_ticket_id, "area": area.strip()},
    ).mappings().first()
    return dict(row) if row else None


def _route_ticket(db: Session, ticket_id: str, ticket_code: str, severity: str, classification: dict,
                   customer_name: Optional[str], customer_email: Optional[str]) -> dict:
    if severity == CRITICAL:
        # No auto-resolution attempt — escalate immediately.
        _escalate(db, ticket_id, ticket_code, severity, reason="Critical severity — immediate escalation")
        return {"status": "escalated", "auto_resolved": False}

    # small + medium both attempt auto-resolution first.
    result = attempt_auto_resolution(classification["category"], classification["subtype"], classification["summary"])
    if result["resolved"]:
        _resolve(db, ticket_id, ticket_code, resolution=result["message"], resolved_by=None,
                 customer_name=customer_name, customer_email=customer_email)
        return {"status": "auto_resolved", "auto_resolved": True, "resolution": result["message"]}

    if severity == SMALL:
        # Spec: small tickets are always auto-resolved, no CR involvement.
        # If the LLM couldn't produce a confident resolution, resolve with a
        # generic acknowledgement rather than escalating a "small" ticket.
        fallback_message = (
            "Thanks for letting us know. This has been logged and forwarded to the "
            "relevant back-office team for routine follow-up."
        )
        _resolve(db, ticket_id, ticket_code, resolution=fallback_message, resolved_by=None,
                 customer_name=customer_name, customer_email=customer_email)
        return {"status": "auto_resolved", "auto_resolved": True, "resolution": fallback_message}

    # medium, auto-resolution failed -> escalate with the 30-min cadence.
    _escalate(db, ticket_id, ticket_code, severity, reason="Automated resolution attempt was inconclusive")
    return {"status": "escalated", "auto_resolved": False}


def _escalate(db: Session, ticket_id: str, ticket_code: str, severity: str, reason: str, escalated_by: Optional[str] = None):
    interval = REMINDER_INTERVAL_MINUTES.get(severity, 30)
    # Compute "NOW() + N minutes" server-side rather than binding a Python
    # datetime -- a naive datetime.utcnow() bound to a TIMESTAMPTZ column
    # gets reinterpreted in the Postgres session's local timezone (e.g.
    # Asia/Karachi, UTC+5), silently shifting the stored instant.
    db.execute(
        text("""
            UPDATE complaints SET
              status = 'escalated', escalated_at = NOW(), escalated_by = :by,
              next_reminder_due = NOW() + (:minutes * INTERVAL '1 minute'), updated_at = NOW()
            WHERE id = :id
        """),
        {"by": escalated_by, "minutes": interval, "id": ticket_id},
    )
    _log_event(db, ticket_id, "escalation", "vema" if not escalated_by else "admin", reason)
    db.commit()
    notify_role(
        db, "customer_rep", "User Complaints",
        f"{'Critical' if severity == 'critical' else 'Escalated'} Ticket — {ticket_code}",
        f"{reason}. Reminder every {interval} minutes until resolved.",
        metadata={"ticket_id": ticket_id, "ticket_code": ticket_code, "severity": severity},
    )


def _resolve(db: Session, ticket_id: str, ticket_code: str, resolution: str, resolved_by: Optional[str],
             customer_name: Optional[str], customer_email: Optional[str], actor: str = "vema"):
    status = "auto_resolved" if resolved_by is None else "resolved"
    db.execute(
        text("""
            UPDATE complaints SET
              status = :status, resolved_at = NOW(), resolved_by = :by,
              resolution = :resolution, next_reminder_due = NULL, updated_at = NOW()
            WHERE id = :id
        """),
        {"status": status, "by": resolved_by, "resolution": resolution, "id": ticket_id},
    )
    _log_event(db, ticket_id, "resolution", actor, resolution)
    db.commit()
    if customer_email:
        send_customer_resolution_email(customer_email, customer_name or "Customer", ticket_code, resolution)

    # RAG Feature D — keep the resolved_ticket corpus roughly current between
    # full reindexes. Wrapped so a RAG failure can never block a resolution.
    try:
        from rag.resolved_tickets import index_single_resolved_ticket
        index_single_resolved_ticket(db, ticket_id)
    except Exception as e:
        print(f"[WARN] non-fatal: RAG incremental indexing failed for {ticket_code}: {e}")


def cr_resolve_ticket(db: Session, ticket_id: str, resolution: str, resolved_by_user_id: str, actor: str = "customer_rep"):
    row = db.execute(text("SELECT * FROM complaints WHERE id = :id"), {"id": ticket_id}).mappings().first()
    if not row:
        return None
    _resolve(db, ticket_id, row["ticket_code"], resolution, resolved_by_user_id,
              row["customer_name"], row["customer_email"], actor=actor)
    return row["ticket_code"]


def cr_escalate_to_admin(db: Session, ticket_id: str, escalated_by_user_id: str, note: str = "", actor: str = "customer_rep"):
    row = db.execute(text("SELECT * FROM complaints WHERE id = :id"), {"id": ticket_id}).mappings().first()
    if not row:
        return None
    db.execute(
        text("UPDATE complaints SET escalated_by = :by, updated_at = NOW() WHERE id = :id"),
        {"by": escalated_by_user_id, "id": ticket_id},
    )
    _log_event(db, ticket_id, "escalation", actor, note or "Manually escalated to Admin by a Customer Representative.")
    db.commit()
    notify_role(
        db, "admin", "User Complaints",
        f"Manually Escalated — {row['ticket_code']}",
        note or f"A Customer Representative escalated {row['ticket_code']} to Admin.",
        metadata={"ticket_id": ticket_id, "ticket_code": row["ticket_code"]},
    )
    return row["ticket_code"]
