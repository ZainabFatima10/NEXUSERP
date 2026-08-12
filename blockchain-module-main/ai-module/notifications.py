"""
NEXUS ERP — Notifications Router (DB-backed)
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import text
from database import get_db

router = APIRouter(prefix="/api/notifications", tags=["Notifications"])


@router.get("")
def get_notifications(
    user_id:  str  = Query(None),
    unread:   bool = Query(False),
    category: str  = Query(None),
    limit:    int  = Query(50, le=200),
    offset:   int  = Query(0),
    db: Session = Depends(get_db),
):
    filters = "WHERE (user_id = :uid OR user_id IS NULL)"
    params: dict = {"uid": user_id, "limit": limit, "offset": offset}
    if unread:
        filters += " AND is_read = FALSE"
    if category:
        filters += " AND category = :cat"
        params["cat"] = category

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
        text("SELECT COUNT(*) FROM notifications WHERE (user_id=:uid OR user_id IS NULL) AND is_read=FALSE"),
        {"uid": user_id},
    ).scalar()

    return {
        "unread_count": unread_count,
        "notifications": [dict(r) for r in rows],
    }


@router.patch("/{notif_id}/read")
def mark_read(notif_id: str, db: Session = Depends(get_db)):
    db.execute(
        text("UPDATE notifications SET is_read=TRUE WHERE id=:id"),
        {"id": notif_id},
    )
    db.commit()
    return {"message": "Marked as read"}


@router.patch("/mark-all-read")
def mark_all_read(user_id: str = Query(None), db: Session = Depends(get_db)):
    db.execute(
        text("UPDATE notifications SET is_read=TRUE WHERE user_id=:uid OR user_id IS NULL"),
        {"uid": user_id},
    )
    db.commit()
    return {"message": "All marked as read"}
