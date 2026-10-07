"""
NEXUS ERP — Notification Engine (Phase 3)
A second, richer entry point alongside notification_service.py's
create_notification()/notify_role() — which keep working completely
unchanged for every existing caller (procurement.py, inventory_v2.py,
complaints.py, vema_orchestrator.py, reminder_scheduler.py's VEMA job).
This engine is used by the event-catalogue-shaped call sites introduced in
vendor_orders.py / vendors.py (Phase 1/2) — see NOTIFICATIONS.md for the
full catalogue and the "why a second entry point" scoping note.

Design:
  - notify() resolves recipients from a per-event rule (role names, or the
    special markers "$orderer"/"$actor" pulled from the caller's context
    dict), applies each recipient's preferences (critical/requires_action
    events are always in-app regardless of preference), writes the in-app
    row(s), and queues a staff email via notification_outbox — all using
    the caller's own db session, in the same transaction, with NO commit
    here (the caller commits once, same as every other write in that
    request, so a committed business change never loses its notification).
  - Vendor-facing email stays exactly as built in Phase 1/2: a direct,
    synchronous n8n call at the point of action. Nothing here re-routes
    that — only staff-facing email goes through the outbox.
  - Dedup via the unique (user_id, dedupe_key) index — a repeated
    dedupe_key for the same user silently no-ops (no duplicate row, no
    duplicate email).
  - auto_resolve() closes out a requires_action notification once its
    underlying action is actually done (e.g. confirming arrival resolves
    both "out for delivery" and any "confirm arrival" reminder for that
    same order).
"""
import json
import os
import uuid
from typing import Optional

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.orm import Session

import email_service

load_dotenv()
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")

# Each role's section of the app lives under a different path prefix —
# a notification's action_path (e.g. "/tracking/{id}") gets this prefixed
# per-recipient, since the same event often fans out to an orderer *and*
# an admin/PM who each reach the same page via a different route.
ROLE_BASE_PATH = {
    "admin": "/admin",
    "procurement_manager": "/procurement",
    "customer_rep": "/cr",
    "customer": "/portal",
}

# ---------------------------------------------------------------------------
# Event catalogue — category/severity/requires_action/recipients per event.
# "$orderer" / "$actor" are resolved from the caller's ctx dict at notify()
# time; anything else is treated as a role name (notify_role-style fan-out).
# `email: True` means staff recipients also get a queued outbox email.
# ---------------------------------------------------------------------------
EVENT_META = {
    "vendor_application.submitted": {"category": "Vendor Applications", "severity": "info", "requires_action": True, "action_label": "Review", "recipients": ["admin", "procurement_manager"]},
    "vendor_application.approved":  {"category": "Vendor Applications", "severity": "success", "recipients": ["$actor"]},

    "order.placed":          {"category": "Orders", "severity": "info", "recipients": ["$orderer"]},
    "order.resent":           {"category": "Orders", "severity": "info", "recipients": ["$orderer"]},
    "order.vendor_accepted":   {"category": "Orders", "severity": "success", "recipients": ["$orderer"], "email": True},
    "order.vendor_rejected":    {"category": "Orders", "severity": "warning", "requires_action": True, "action_label": "Pick another vendor", "recipients": ["$orderer"], "email": True},
    "order.expired":             {"category": "Orders", "severity": "warning", "recipients": ["$orderer", "procurement_manager"], "email": True},

    "payment.required":           {"category": "Payments", "severity": "critical", "requires_action": True, "action_label": "Add payment method", "recipients": ["admin", "$orderer"]},
    "payment.captured":             {"category": "Payments", "severity": "success", "recipients": ["$orderer", "admin"], "email": True},
    "payment.failed":                {"category": "Payments", "severity": "critical", "recipients": ["$orderer", "admin"], "email": True},
    "payment.transfer_required":     {"category": "Payments", "severity": "warning", "requires_action": True, "action_label": "Record transfer", "recipients": ["admin"], "email": True},
    "payment.payout_sent":            {"category": "Payments", "severity": "success", "recipients": ["$orderer", "admin"]},

    "shipment.dispatched":             {"category": "Shipments", "severity": "info", "recipients": ["$orderer"], "email": True},
    "shipment.in_transit":              {"category": "Shipments", "severity": "info", "recipients": ["$orderer"]},
    "shipment.out_for_delivery":          {"category": "Shipments", "severity": "info", "requires_action": True, "action_label": "Confirm arrival", "recipients": ["$orderer"]},
    "shipment.delayed":                    {"category": "Shipments", "severity": "warning", "recipients": ["$orderer", "procurement_manager"], "email": True},
    "shipment.arrival_reminder":             {"category": "Shipments", "severity": "warning", "requires_action": True, "action_label": "Confirm arrival", "recipients": ["$orderer"], "email": True},
    "shipment.arrived":                        {"category": "Shipments", "severity": "warning", "requires_action": True, "action_label": "Approve or dispute", "recipients": ["$orderer"], "email": True},
    "shipment.approval_reminder":                {"category": "Shipments", "severity": "warning", "requires_action": True, "action_label": "Approve or dispute", "recipients": ["$orderer"], "email": True},
    "shipment.status_checkin_sent":                {"category": "Shipments", "severity": "info", "recipients": ["$orderer"]},

    "contract.executed":                           {"category": "Confirmations", "severity": "success", "recipients": ["$orderer", "admin", "procurement_manager"], "email": True},
    "dispute.opened":                                {"category": "Shipments", "severity": "warning", "recipients": ["admin"], "email": True},
    "contract.cancelled":                              {"category": "Shipments", "severity": "warning", "recipients": ["$orderer", "procurement_manager"], "email": True},
    "dispute.resolved":                                {"category": "Shipments", "severity": "info", "recipients": ["$orderer"], "email": True},

    "chain.unreachable":                                 {"category": "System", "severity": "warning", "recipients": ["admin"]},
}


def _resolve_recipients(db: Session, event_type: str, ctx: dict) -> list:
    meta = EVENT_META.get(event_type, {})
    out = set()
    for r in meta.get("recipients", []):
        if r == "$orderer":
            if ctx.get("orderer_user_id"):
                out.add(str(ctx["orderer_user_id"]))
        elif r == "$actor":
            if ctx.get("actor_user_id"):
                out.add(str(ctx["actor_user_id"]))
        else:
            rows = db.execute(
                text("SELECT id FROM users WHERE role = :r AND is_active = TRUE"), {"r": r}
            ).scalars().all()
            out.update(str(u) for u in rows)
    return list(out)


def _get_preference(db: Session, user_id: str, event_type: str) -> dict:
    row = db.execute(
        text("SELECT in_app, email FROM notification_preferences WHERE user_id = :uid AND type = :t"),
        {"uid": user_id, "t": event_type},
    ).mappings().first()
    if row:
        return {"in_app": row["in_app"], "email": row["email"]}
    return {"in_app": True, "email": True}  # no row = default on


def notify(
    db: Session,
    event_type: str,
    ctx: dict,
    *,
    title: str,
    body: str,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    action_path: Optional[str] = None,
    dedupe_key: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> list:
    """Writes in-app rows + queues staff email for every resolved recipient.
    No commit here — same transaction as the caller's business change.
    `action_path` (e.g. "/tracking/{id}") is prefixed per-recipient with
    their own role's base route, since the same event can fan out to an
    orderer and an admin/PM who reach the same page via different routes.
    Returns the list of notification ids actually inserted (empty entries
    are dedupe no-ops, not failures)."""
    meta = EVENT_META.get(event_type, {})
    category = meta.get("category", "Updates")
    severity = meta.get("severity", "info")
    requires_action = meta.get("requires_action", False)
    action_label = meta.get("action_label")
    wants_email = meta.get("email", False)

    recipients = _resolve_recipients(db, event_type, ctx)
    inserted_ids = []

    for user_id in recipients:
        prefs = _get_preference(db, user_id, event_type)
        in_app_on = prefs["in_app"] or requires_action or severity == "critical"
        if not in_app_on:
            continue

        action_url = None
        if action_path:
            role = db.execute(text("SELECT role FROM users WHERE id = :uid"), {"uid": user_id}).scalar()
            base = ROLE_BASE_PATH.get(role, "/admin")
            action_url = f"{FRONTEND_URL}{base}{action_path}"

        notif_id = str(uuid.uuid4())
        row = db.execute(
            text("""
                INSERT INTO notifications
                  (id, user_id, category, title, description, is_read, metadata,
                   type, severity, entity_type, entity_id, action_url, action_label,
                   requires_action, dedupe_key, created_at)
                VALUES
                  (:id, :uid, :cat, :title, :body, FALSE, CAST(:metadata AS jsonb),
                   :type, :sev, :etype, :eid, :action_url, :action_label,
                   :requires_action, :dedupe_key, NOW())
                ON CONFLICT (user_id, dedupe_key) WHERE dedupe_key IS NOT NULL DO NOTHING
                RETURNING id
            """),
            {
                "id": notif_id, "uid": user_id, "cat": category, "title": title, "body": body,
                "metadata": json.dumps(metadata or {}), "type": event_type, "sev": severity,
                "etype": entity_type, "eid": entity_id, "action_url": action_url,
                "action_label": action_label, "requires_action": requires_action,
                "dedupe_key": dedupe_key,
            },
        ).first()
        if row is None:
            continue  # deduped — an identical notification already exists
        inserted_ids.append(notif_id)

        email_on = prefs["email"] and wants_email
        if email_on:
            recipient_email = db.execute(
                text("SELECT email FROM users WHERE id = :uid"), {"uid": user_id}
            ).scalar()
            if recipient_email:
                _enqueue_outbox_email(db, recipient_email, title, body)

    return inserted_ids


def _enqueue_outbox_email(db: Session, recipient_email: str, subject: str, body: str):
    db.execute(
        text("""
            INSERT INTO notification_outbox (id, channel, recipient, payload, status)
            VALUES (:id, 'email', :recipient, CAST(:payload AS jsonb), 'pending')
        """),
        {
            "id": str(uuid.uuid4()), "recipient": recipient_email,
            "payload": json.dumps({"subject": subject, "body_html": f"<p>{body}</p>"}),
        },
    )


def auto_resolve(db: Session, entity_type: str, entity_id: str, user_id: Optional[str] = None):
    """Marks any open requires_action notification for this entity as
    resolved + read — called right after the underlying action succeeds
    (confirm arrival, approve receipt, add payment method, etc.)."""
    filters = "WHERE entity_type = :etype AND entity_id = :eid AND requires_action = TRUE AND resolved_at IS NULL"
    params = {"etype": entity_type, "eid": entity_id}
    if user_id:
        filters += " AND user_id = :uid"
        params["uid"] = user_id
    db.execute(
        text(f"UPDATE notifications SET resolved_at = NOW(), is_read = TRUE, read_at = NOW() {filters}"),
        params,
    )


def process_notification_outbox(db: Session, max_rows: int = 20) -> int:
    """Scheduler job (wired into reminder_scheduler.py) — sends pending
    outbox rows, with exponential backoff on failure, capped at 8 attempts."""
    rows = db.execute(
        text("""
            SELECT * FROM notification_outbox
            WHERE status = 'pending' AND next_retry_at <= NOW()
            ORDER BY created_at ASC LIMIT :n
        """),
        {"n": max_rows},
    ).mappings().all()

    sent = 0
    for row in rows:
        payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
        try:
            ok = email_service.send_internal_notification_email(
                row["recipient"], payload.get("subject", "NEXUS ERP Notification"), payload.get("body_html", "")
            )
        except Exception:
            ok = False

        if ok:
            db.execute(
                text("UPDATE notification_outbox SET status='sent', sent_at=NOW() WHERE id=:id"), {"id": row["id"]}
            )
            sent += 1
        else:
            attempts = row["attempts"] + 1
            backoff_minutes = min(2 ** attempts, 60)
            status = "failed" if attempts >= 8 else "pending"
            db.execute(
                text("""
                    UPDATE notification_outbox
                    SET attempts=:a, status=:s, next_retry_at = NOW() + (:m * INTERVAL '1 minute'),
                        last_error='send failed'
                    WHERE id=:id
                """),
                {"a": attempts, "s": status, "m": backoff_minutes, "id": row["id"]},
            )
        db.commit()
    return sent
