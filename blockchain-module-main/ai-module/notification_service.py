"""
NEXUS ERP — Notification Service
Writes notifications to PostgreSQL and (optionally) broadcasts
via WebSocket in a future iteration.
"""
from datetime import datetime
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import text
import uuid


# ---------------------------------------------------------------------------
# Core writer
# ---------------------------------------------------------------------------

def create_notification(
    db: Session,
    category: str,
    title: str,
    description: str,
    user_id: Optional[str] = None,   # None = broadcast
    metadata: dict = None,
) -> dict:
    """Insert a notification row and return it as a dict."""
    nid = str(uuid.uuid4())
    db.execute(
        text("""
        INSERT INTO notifications
          (id, user_id, category, title, description, metadata, created_at)
        VALUES
          (:id, :user_id, :category, :title, :description, CAST(:metadata AS jsonb), NOW())
        """),
        {
            "id":          nid,
            "user_id":     user_id,
            "category":    category,
            "title":       title,
            "description": description,
            "metadata":    __import__("json").dumps(metadata or {}),
        },
    )
    db.commit()
    return {
        "id":          nid,
        "category":    category,
        "title":       title,
        "description": description,
        "is_read":     False,
        "created_at":  datetime.utcnow().isoformat() + "Z",
    }


# ---------------------------------------------------------------------------
# Typed helpers — called from procurement routes
# ---------------------------------------------------------------------------

def notify_order_created(db: Session, order_code: str, item_name: str, trigger: str):
    create_notification(
        db,
        category    = "Confirmations",
        title       = f"Order {order_code} Created",
        description = (
            f"{trigger} order for {item_name} has been generated. "
            "Vendor email sent — awaiting confirmation."
        ),
        metadata    = {"order_code": order_code, "trigger": trigger},
    )


def notify_vendor_confirmed(db: Session, order_code: str, vendor_name: str):
    create_notification(
        db,
        category    = "Confirmations",
        title       = f"Vendor Confirmed — {order_code}",
        description = (
            f"{vendor_name} has confirmed order {order_code}. "
            "Smart contract is being generated."
        ),
        metadata    = {"order_code": order_code},
    )


def notify_contract_signed(db: Session, order_code: str, contract_hash: str):
    create_notification(
        db,
        category    = "Confirmations",
        title       = f"Contract Signed — {order_code}",
        description = (
            f"Smart contract for {order_code} is fully signed. "
            f"Hash: {contract_hash[:20]}…"
        ),
        metadata    = {"order_code": order_code, "contract_hash": contract_hash},
    )


def notify_delivery_checkin(
    db: Session,
    order_code: str,
    item_name: str,
    condition: str,
    quantity_received: float,
):
    is_good = condition == "Good"
    create_notification(
        db,
        category    = "Confirmations" if is_good else "Updates",
        title       = f"Delivery {'Accepted' if is_good else 'Issue'} — {order_code}",
        description = (
            f"{item_name}: {quantity_received:,.0f} units received. "
            f"Condition: {condition}. "
            + ("Smart contract executed automatically." if is_good
               else "Review required before contract execution.")
        ),
        metadata    = {
            "order_code": order_code,
            "condition":  condition,
        },
    )


def notify_stock_critical(db: Session, item_name: str, current_stock: float, item_id: str):
    create_notification(
        db,
        category    = "Updates",
        title       = f"🔴 Critical Stock — {item_name}",
        description = (
            f"Stock for {item_name} has fallen to {current_stock} units "
            "(below 20% threshold). VEMA reorder triggered automatically."
        ),
        metadata    = {"item_id": item_id},
    )


def notify_stock_low(db: Session, item_name: str, current_stock: float, item_id: str):
    create_notification(
        db,
        category    = "Updates",
        title       = f"⚠️ Low Stock — {item_name}",
        description = (
            f"Stock for {item_name} is at {current_stock} units, "
            "below the minimum threshold. Auto-Generated reorder created."
        ),
        metadata    = {"item_id": item_id},
    )


def notify_out_of_stock(db: Session, item_name: str, item_id: str):
    create_notification(
        db,
        category    = "Updates",
        title       = f"🚨 OUT OF STOCK — {item_name}",
        description = (
            f"Stock for {item_name} has reached 0 units! "
            "Immediate VEMA reorder triggered automatically."
        ),
        metadata    = {"item_id": item_id},
    )
