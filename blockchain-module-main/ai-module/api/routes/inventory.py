from fastapi import APIRouter, Query
from typing import Optional
import sys, uuid
sys.path.insert(0, "/Users/zainabfatima/Desktop/nexus-erp/ai-module")
from models.inventory_engine import (
    get_inventory_overview, get_current_orders,
    get_past_orders, check_and_generate_orders,
    accept_order, get_notifications,
    mark_notification_read, get_dashboard_stats, engine
)
from models.vema_service import send_vendor_email, verify_smart_contract
from datetime import datetime, timedelta
from pydantic import BaseModel
from sqlalchemy import text

router = APIRouter()

# ── Dashboard ──────────────────────────────────────────────────────
@router.get("/dashboard")
def dashboard():
    return get_dashboard_stats()

# ── Inventory Overview ─────────────────────────────────────────────
@router.get("/inventory/overview")
def inventory_overview(category: Optional[str] = Query(None)):
    items   = get_inventory_overview(category)
    summary = {
        "total_items": len(items),
        "ok":          sum(1 for i in items if i["status"] == "OK"),
        "low":         sum(1 for i in items if i["status"] == "Low"),
        "critical":    sum(1 for i in items if i["status"] == "Critical"),
        "predicted_demand": sum(i.get("predicted_demand", 0) for i in items),
    }
    return {
        "summary":   summary,
        "items":     items,
        "timestamp": datetime.now().isoformat()
    }

# ── Orders ─────────────────────────────────────────────────────────
@router.get("/inventory/orders/current")
def current_orders(category: Optional[str] = Query(None)):
    orders = get_current_orders(category)
    return {"count": len(orders), "orders": orders}

@router.get("/inventory/orders/history")
def past_orders(category: Optional[str] = Query(None)):
    orders = get_past_orders(category)
    return {"count": len(orders), "orders": orders}

@router.post("/inventory/check")
def run_inventory_check():
    new_orders = check_and_generate_orders()
    return {
        "message":   f"{len(new_orders)} new orders generated",
        "order_ids": new_orders,
        "timestamp": datetime.now().isoformat()
    }

# ── Accept Order ───────────────────────────────────────────────────
class AcceptBody(BaseModel):
    officer_name: str = "Procurement Officer"

@router.post("/inventory/orders/{order_id}/accept")
def accept_procurement_order(order_id: str, body: AcceptBody):
    result   = accept_order(order_id, body.officer_name)
    contract = verify_smart_contract(order_id)
    email    = send_vendor_email(order_id)
    return {
        **result,
        "contract": contract,
        "email":    email
    }

@router.post("/inventory/orders/{order_id}/verify-contract")
def verify_contract(order_id: str):
    return verify_smart_contract(order_id)

@router.post("/inventory/orders/{order_id}/send-email")
def send_email(order_id: str):
    return send_vendor_email(order_id)

# ── Manual Reorder ─────────────────────────────────────────────────
class ReorderBody(BaseModel):
    quantity: int = 100

@router.post("/inventory/reorder/{item_id}")
def manual_reorder(item_id: str, body: ReorderBody):
    items = get_inventory_overview()
    item  = next((i for i in items if i["item_id"] == item_id), None)
    if not item:
        return {"error": "Item not found"}

    order_id = f"ORD-{uuid.uuid4().hex[:6].upper()}"
    delivery = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

    with engine.connect() as conn:
        conn.execute(text("""
            INSERT INTO procurement_orders
            (order_id, item_id, item_name, category, quantity, unit,
             vendor, vendor_email, trigger_type, stage,
             contract_status, expected_delivery)
            VALUES (:oid,:iid,:iname,:cat,:qty,:unit,
                    :vendor,:vemail,:trigger,:stage,:cstatus,:delivery)
        """), {
            "oid":     order_id, "iid":    item_id,
            "iname":   item["name"], "cat": item["category"],
            "qty":     body.quantity, "unit": item["unit"],
            "vendor":  item["vendor"], "vemail": item["vendor_email"],
            "trigger": "Manual", "stage": "Pending Verification",
            "cstatus": "Pending", "delivery": delivery
        })
        conn.execute(text("""
            INSERT INTO notifications
            (type, title, message, order_id, item_name, category)
            VALUES (:type,:title,:msg,:oid,:iname,:cat)
        """), {
            "type":  "REORDER_REQUEST",
            "title": f"Manual Reorder: {item['name']}",
            "msg":   f"Manual reorder of {body.quantity} {item['unit']} "
                     f"placed for {item['name']} ({item['category']}). "
                     f"Awaiting procurement officer approval.",
            "oid":   order_id, "iname": item["name"],
            "cat":   item["category"]
        })
        conn.commit()
    return {"message": "Manual reorder placed", "order_id": order_id}

# ── Notifications ──────────────────────────────────────────────────
@router.get("/notifications")
def get_all_notifications(unread_only: bool = False):
    notifs = get_notifications(unread_only)
    return {"count": len(notifs), "notifications": notifs}

@router.post("/notifications/{notification_id}/read")
def mark_read(notification_id: int):
    mark_notification_read(notification_id)
    return {"message": "Marked as read"}
