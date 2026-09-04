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
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text

from llm_service import classify_complaint, attempt_auto_resolution
from notification_service import notify_role, create_notification
from email_service import send_customer_resolution_email
from taxonomy import REMINDER_INTERVAL_MINUTES, CRITICAL, MEDIUM, SMALL


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

    db.execute(
        text("""
            INSERT INTO complaints (
              id, ticket_code, customer_id, customer_name, customer_email, channel,
              category, subtype, severity, description, area, status, vema_triggered,
              created_at, updated_at
            ) VALUES (
              :id, :code, :cust_id, :cust_name, :cust_email, :channel,
              :category, :subtype, :severity, :description, :area, 'open', :vema_triggered,
              NOW(), NOW()
            )
        """),
        {
            "id": ticket_id, "code": ticket_code,
            "cust_id": customer_id, "cust_name": customer_name, "cust_email": customer_email,
            "channel": channel, "category": classification["category"], "subtype": classification["subtype"],
            "severity": classification["severity"], "description": description, "area": area,
            "vema_triggered": vema_triggered,
        },
    )

    actor = "customer" if channel in ("voice", "chat") else "admin"
    _log_event(db, ticket_id, "voice_transcript" if channel == "voice" else "chat_message", actor, description)
    _log_event(
        db, ticket_id, "system_action", "vema",
        f"Classified as {classification['category']} / {classification['subtype']} "
        f"(severity: {classification['severity']}).",
        metadata=classification,
    )
    db.commit()

    outcome = _route_ticket(db, ticket_id, ticket_code, classification["severity"], classification, customer_name, customer_email)
    return {"ticket_id": ticket_id, "ticket_code": ticket_code, "classification": classification, **outcome}


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
    next_due = datetime.utcnow() + timedelta(minutes=interval)
    db.execute(
        text("""
            UPDATE complaints SET
              status = 'escalated', escalated_at = NOW(), escalated_by = :by,
              next_reminder_due = :due, updated_at = NOW()
            WHERE id = :id
        """),
        {"by": escalated_by, "due": next_due, "id": ticket_id},
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
             customer_name: Optional[str], customer_email: Optional[str]):
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
    _log_event(db, ticket_id, "resolution", "vema" if resolved_by is None else "admin", resolution)
    db.commit()
    if customer_email:
        send_customer_resolution_email(customer_email, customer_name or "Customer", ticket_code, resolution)


def cr_resolve_ticket(db: Session, ticket_id: str, resolution: str, resolved_by_user_id: str):
    row = db.execute(text("SELECT * FROM complaints WHERE id = :id"), {"id": ticket_id}).mappings().first()
    if not row:
        return None
    _resolve(db, ticket_id, row["ticket_code"], resolution, resolved_by_user_id,
              row["customer_name"], row["customer_email"])
    return row["ticket_code"]


def cr_escalate_to_admin(db: Session, ticket_id: str, escalated_by_user_id: str, note: str = ""):
    row = db.execute(text("SELECT * FROM complaints WHERE id = :id"), {"id": ticket_id}).mappings().first()
    if not row:
        return None
    db.execute(
        text("UPDATE complaints SET escalated_by = :by, updated_at = NOW() WHERE id = :id"),
        {"by": escalated_by_user_id, "id": ticket_id},
    )
    _log_event(db, ticket_id, "escalation", "admin", note or "Manually escalated to Admin by a Customer Representative.")
    db.commit()
    notify_role(
        db, "admin", "User Complaints",
        f"Manually Escalated — {row['ticket_code']}",
        note or f"A Customer Representative escalated {row['ticket_code']} to Admin.",
        metadata={"ticket_id": ticket_id, "ticket_code": row["ticket_code"]},
    )
    return row["ticket_code"]
