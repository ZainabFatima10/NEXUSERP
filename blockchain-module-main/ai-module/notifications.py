"""
NEXUS ERP — Notifications Router (DB-backed)
Extended for Phase 3 (notification_engine.py's event catalogue, SSE
stream, preferences) without breaking the existing endpoints' paths or
response shapes. One real fix along the way: the original endpoints
trusted a client-supplied `user_id` query parameter instead of the JWT —
meaning any signed-in staff user could read or mark-read *anyone else's*
notifications by guessing their UUID. Every endpoint here now derives the
current user from the token; the existing frontend callers already only
ever passed their own id, so this closes the gap without changing
legitimate behavior.
"""
import json
import time
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db, db_session
from rbac import require_role, ROLE_CUSTOMER_REP, ROLE_PROCUREMENT_MANAGER, get_current_user, decode_access_token
from notification_engine import EVENT_META

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])
_staff = Depends(require_role(ROLE_CUSTOMER_REP, ROLE_PROCUREMENT_MANAGER))

# Events where in-app is always on regardless of preference (critical
# severity, or requires_action) — mirrors notification_engine.notify()'s
# own enforcement, so the preferences UI can show them correctly "locked".
_LOCKED_TYPES = {
    t for t, meta in EVENT_META.items()
    if meta.get("requires_action") or meta.get("severity") == "critical"
}


@router.get("", dependencies=[_staff])
def get_notifications(
    unread:          bool = Query(False),
    category:        str  = Query(None),
    severity:        str  = Query(None),
    requires_action: Optional[bool] = Query(None),
    archived:        bool = Query(False),
    limit:           int  = Query(50, le=200),
    offset:          int  = Query(0),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filters = "WHERE (user_id = :uid OR user_id IS NULL)"
    params: dict = {"uid": user["id"], "limit": limit, "offset": offset}
    filters += " AND archived_at IS NOT NULL" if archived else " AND archived_at IS NULL"
    if unread:
        filters += " AND is_read = FALSE"
    if category:
        filters += " AND category = :cat"
        params["cat"] = category
    if severity:
        filters += " AND severity = :sev"
        params["sev"] = severity
    if requires_action is not None:
        filters += " AND requires_action = :ra"
        params["ra"] = requires_action

    rows = db.execute(
        text(f"""
            SELECT * FROM notifications
            {filters}
            ORDER BY created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()

    unread_count = db.execute(
        text("SELECT COUNT(*) FROM notifications WHERE (user_id=:uid OR user_id IS NULL) AND is_read=FALSE AND archived_at IS NULL"),
        {"uid": user["id"]},
    ).scalar()

    return {
        "unread_count": unread_count,
        "notifications": [dict(r) for r in rows],
    }


@router.get("/unread-count", dependencies=[_staff])
def get_unread_count(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    count = db.execute(
        text("SELECT COUNT(*) FROM notifications WHERE (user_id=:uid OR user_id IS NULL) AND is_read=FALSE AND archived_at IS NULL"),
        {"uid": user["id"]},
    ).scalar()
    return {"count": count}


@router.patch("/{notif_id}/read", dependencies=[_staff])
def mark_read(notif_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    result = db.execute(
        text("""
            UPDATE notifications SET is_read=TRUE, read_at=NOW()
            WHERE id=:id AND (user_id=:uid OR user_id IS NULL)
        """),
        {"id": notif_id, "uid": user["id"]},
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Notification not found")
    return {"message": "Marked as read"}


@router.patch("/mark-all-read", dependencies=[_staff])
def mark_all_read(category: str = Query(None), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    filters = "WHERE (user_id=:uid OR user_id IS NULL) AND is_read=FALSE"
    params = {"uid": user["id"]}
    if category:
        filters += " AND category = :cat"
        params["cat"] = category
    db.execute(text(f"UPDATE notifications SET is_read=TRUE, read_at=NOW() {filters}"), params)
    db.commit()
    return {"message": "All marked as read"}


@router.post("/{notif_id}/archive", dependencies=[_staff])
def archive_notification(notif_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    result = db.execute(
        text("""
            UPDATE notifications SET archived_at=NOW(), is_read=TRUE, read_at=COALESCE(read_at, NOW())
            WHERE id=:id AND (user_id=:uid OR user_id IS NULL)
        """),
        {"id": notif_id, "uid": user["id"]},
    )
    db.commit()
    if result.rowcount == 0:
        raise HTTPException(404, "Notification not found")
    return {"message": "Archived"}


# ---------------------------------------------------------------------------
# Preferences
# ---------------------------------------------------------------------------

@router.get("/preferences", dependencies=[_staff])
def get_preferences(user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT type, in_app, email FROM notification_preferences WHERE user_id = :uid"), {"uid": user["id"]}
    ).mappings().all()
    saved = {r["type"]: {"in_app": r["in_app"], "email": r["email"]} for r in rows}

    out = []
    for event_type, meta in sorted(EVENT_META.items()):
        pref = saved.get(event_type, {"in_app": True, "email": True})
        out.append({
            "type": event_type,
            "category": meta.get("category", "Updates"),
            "severity": meta.get("severity", "info"),
            "locked": event_type in _LOCKED_TYPES,
            "in_app": True if event_type in _LOCKED_TYPES else pref["in_app"],
            "email": pref["email"],
            "has_email": meta.get("email", False),
        })
    return {"preferences": out}


@router.put("/preferences", dependencies=[_staff])
def update_preference(body: dict, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    event_type = body.get("type")
    if not event_type:
        raise HTTPException(400, "type is required")
    in_app = bool(body.get("in_app", True))
    email = bool(body.get("email", True))
    if event_type in _LOCKED_TYPES:
        in_app = True  # critical/requires_action in-app can't be turned off

    db.execute(
        text("""
            INSERT INTO notification_preferences (id, user_id, type, in_app, email)
            VALUES (gen_random_uuid(), :uid, :type, :in_app, :email)
            ON CONFLICT (user_id, type) DO UPDATE SET in_app = :in_app, email = :email
        """),
        {"uid": user["id"], "type": event_type, "in_app": in_app, "email": email},
    )
    db.commit()
    return {"message": "Preference saved", "locked": event_type in _LOCKED_TYPES}


# ---------------------------------------------------------------------------
# Real-time stream (SSE, with the frontend polling fallback documented in
# NOTIFICATIONS.md). Implemented as a polling-the-DB generator under the
# SSE wire protocol -- there's no message bus in this single-process
# APScheduler-based app (consistent with why APScheduler was chosen over
# Celery/Redis elsewhere) -- functionally equivalent for this app's scale,
# not a true push. Each poll opens and closes its own short-lived db
# session so a long-held SSE connection doesn't pin a pool connection for
# its whole lifetime.
# ---------------------------------------------------------------------------

def _event_generator(user_id: str, since: datetime):
    tick = 0
    while True:
        try:
            with db_session() as db:
                rows = db.execute(
                    text("""
                        SELECT * FROM notifications
                        WHERE (user_id = :uid OR user_id IS NULL) AND created_at > :since
                        ORDER BY created_at ASC
                    """),
                    {"uid": user_id, "since": since},
                ).mappings().all()
            for row in rows:
                since = row["created_at"]
                payload = jsonable_encoder(dict(row))
                yield f"id: {row['id']}\ndata: {json.dumps(payload)}\n\n"
        except GeneratorExit:
            raise
        except Exception as e:
            print(f"[WARN] notifications SSE poll failed: {e}")

        tick += 1
        if tick >= 15:  # ~15s heartbeat at the 1s poll cadence below
            yield ": heartbeat\n\n"
            tick = 0
        time.sleep(1)


@router.get("/stream")
def notifications_stream(request: Request, token: str = Query(...), last_event_id: Optional[str] = None):
    """EventSource can't set an Authorization header, so auth comes via a
    `token` query param here instead of the usual bearer header — same JWT,
    just carried differently for this one endpoint."""
    try:
        payload = decode_access_token(token)
    except HTTPException:
        raise HTTPException(401, "Invalid or expired token")
    user_id = payload["sub"]

    since = datetime.now(timezone.utc)
    last_id = request.headers.get("last-event-id") or last_event_id
    if last_id:
        with db_session() as db:
            row = db.execute(text("SELECT created_at FROM notifications WHERE id = :id"), {"id": last_id}).mappings().first()
            if row:
                since = row["created_at"]

    return StreamingResponse(
        _event_generator(user_id, since),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
