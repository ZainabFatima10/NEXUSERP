"""
NEXUS ERP — Procurement Router
Covers the full order lifecycle:
  POST /procurement/orders          — create order + send vendor email
  GET  /procurement/orders          — list all orders
  GET  /procurement/orders/{id}     — order detail + tracking
  POST /procurement/confirm/{token} — vendor email confirmation (link)
  POST /procurement/sign/{id}       — operator signs contract
  POST /procurement/checkin/{id}    — delivery check-in
  GET  /procurement/checkins/{id}   — all check-ins for an order
  POST /procurement/manual-reorder  — manual reorder trigger
"""
import uuid, json
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db
from email_service import (
    generate_confirm_token,
    send_vendor_order_email,
    send_contract_ready_email,
    send_delivery_notification_email,
)
from contract_service import (
    create_smart_contract,
    sign_contract,
    execute_contract,
    reject_contract,
)
from notification_service import (
    notify_order_created,
    notify_vendor_confirmed,
    notify_contract_signed,
    notify_delivery_checkin,
)

router = APIRouter(prefix="/api/procurement", tags=["Procurement"])


# ────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ────────────────────────────────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    item_id:           str
    quantity:          float
    unit_price:        Optional[float] = None
    trigger_type:      str = "Manual"    # VEMA-Triggered | Auto-Generated | Manual
    triggered_by:      Optional[str] = None
    expected_delivery: Optional[str] = None   # YYYY-MM-DD, default +14 days


class DeliveryCheckinRequest(BaseModel):
    location:          Optional[str] = "Main Warehouse"
    status:            str            # Arrived at Warehouse | Inspected | Accepted | Rejected
    quantity_received: float
    condition:         str            # Good | Partial | Damaged
    notes:             Optional[str] = None
    is_final:          bool = False
    checked_by:        Optional[str] = None


class SignContractRequest(BaseModel):
    signatory:  str   # operator name / user ID
    role:       str = "operator"


class ManualReorderRequest(BaseModel):
    item_id:    str
    quantity:   float
    unit_price: Optional[float] = None


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _get_item(db: Session, item_id: str) -> dict:
    row = db.execute(
        text("""
            SELECT i.*, v.name AS vendor_name, v.email AS vendor_email
            FROM inventory_items i
            LEFT JOIN vendors v ON v.id = i.vendor_id
            WHERE i.item_id = :id
        """),
        {"id": item_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, f"Item {item_id} not found")
    return dict(row)


def _get_order(db: Session, order_id: str) -> dict:
    row = db.execute(
        text("""
            SELECT o.*, i.name AS item_name, i.unit,
                   v.name AS vendor_name, v.email AS vendor_email
            FROM procurement_orders o
            JOIN inventory_items i ON i.item_id = o.item_id
            JOIN vendors v ON v.id = o.vendor_id
            WHERE o.id = :id
        """),
        {"id": order_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, f"Order {order_id} not found")
    return dict(row)


def _update_inventory_status(db: Session, item_id: str):
    """Recalculate and persist status after stock change."""
    item = db.execute(
        text("SELECT current_stock, min_threshold, critical_threshold FROM inventory_items WHERE item_id = :id"),
        {"id": item_id},
    ).mappings().first()
    if not item:
        return
    s = item["current_stock"]
    mn = item["min_threshold"]
    cr = item["critical_threshold"]
    status = "Critical" if s <= cr else "Low" if s < mn else "OK"
    db.execute(
        text("UPDATE inventory_items SET status=:s, last_updated=NOW() WHERE item_id=:id"),
        {"s": status, "id": item_id},
    )


def _order_to_dict(row: dict) -> dict:
    """Clean up a DB row for API response."""
    out = dict(row)
    for key in ("smart_contract_data", "tracking_events"):
        if out.get(key) and isinstance(out[key], str):
            try:
                out[key] = json.loads(out[key])
            except Exception:
                pass
    return out


# ────────────────────────────────────────────────────────────────────────────
# CREATE ORDER
# ────────────────────────────────────────────────────────────────────────────

@router.post("/orders")
def create_order(req: CreateOrderRequest, db: Session = Depends(get_db)):
    item = _get_item(db, req.item_id)
    if not item.get("vendor_name"):
        raise HTTPException(400, "Item has no vendor assigned")

    order_id      = str(uuid.uuid4())
    order_code    = "ORD-" + uuid.uuid4().hex[:6].upper()
    confirm_token = generate_confirm_token()
    delivery_date = req.expected_delivery or (
        datetime.now() + timedelta(days=14)
    ).strftime("%Y-%m-%d")
    total_price = (
        round(req.quantity * req.unit_price, 2) if req.unit_price else None
    )

    db.execute(
        text("""
            INSERT INTO procurement_orders (
              id, order_code, item_id, vendor_id, quantity, unit,
              unit_price, total_price, trigger_type, triggered_by,
              stage, vendor_confirm_token, expected_delivery,
              tracking_events, created_at, updated_at
            ) VALUES (
              :id, :code, :item_id, :vendor_id, :qty, :unit,
              :unit_price, :total_price, :trigger, :triggered_by,
              'Pending Verification', :token, :delivery,
              '[]'::jsonb, NOW(), NOW()
            )
        """),
        {
            "id": order_id, "code": order_code,
            "item_id": req.item_id, "vendor_id": item["vendor_id"],
            "qty": req.quantity, "unit": item["unit"],
            "unit_price": req.unit_price, "total_price": total_price,
            "trigger": req.trigger_type, "triggered_by": req.triggered_by,
            "token": confirm_token, "delivery": delivery_date,
        },
    )
    db.commit()

    # Send vendor email
    sent = send_vendor_order_email(
        vendor_email      = item["vendor_email"],
        vendor_name       = item["vendor_name"],
        order_code        = order_code,
        item_name         = item["name"],
        quantity          = req.quantity,
        unit              = item["unit"],
        expected_delivery = delivery_date,
        confirm_token     = confirm_token,
        total_price       = total_price,
    )
    if sent:
        db.execute(
            text("""UPDATE procurement_orders
                    SET vendor_email_sent=TRUE, vendor_email_sent_at=NOW(),
                        stage='Vendor Notified', updated_at=NOW()
                    WHERE id=:id"""),
            {"id": order_id},
        )
        db.commit()

    notify_order_created(db, order_code, item["name"], req.trigger_type)

    return {
        "order_id":   order_id,
        "order_code": order_code,
        "stage":      "Vendor Notified" if sent else "Pending Verification",
        "email_sent": sent,
        "message":    f"Order {order_code} created. Vendor email {'sent' if sent else 'queued'}.",
    }


# ────────────────────────────────────────────────────────────────────────────
# LIST ORDERS
# ────────────────────────────────────────────────────────────────────────────

@router.get("/orders")
def list_orders(
    stage:   Optional[str] = Query(None),
    item_id: Optional[str] = Query(None),
    limit:   int = Query(50, le=200),
    offset:  int = Query(0),
    db: Session = Depends(get_db),
):
    filters = "WHERE 1=1"
    params: dict = {"limit": limit, "offset": offset}
    if stage:
        filters += " AND o.stage = :stage"
        params["stage"] = stage
    if item_id:
        filters += " AND o.item_id = :item_id"
        params["item_id"] = item_id

    rows = db.execute(
        text(f"""
            SELECT o.*, i.name AS item_name, i.unit,
                   v.name AS vendor_name, v.email AS vendor_email
            FROM procurement_orders o
            JOIN inventory_items i ON i.item_id = o.item_id
            JOIN vendors v ON v.id = o.vendor_id
            {filters}
            ORDER BY o.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()

    total = db.execute(
        text(f"""
            SELECT COUNT(*) FROM procurement_orders o {filters}
        """),
        params,
    ).scalar()

    return {
        "total":  total,
        "orders": [_order_to_dict(dict(r)) for r in rows],
    }


# ────────────────────────────────────────────────────────────────────────────
# ORDER DETAIL
# ────────────────────────────────────────────────────────────────────────────

@router.get("/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    checkins = db.execute(
        text("""
            SELECT * FROM delivery_checkins
            WHERE order_id = :id ORDER BY checkin_at ASC
        """),
        {"id": order_id},
    ).mappings().all()
    audit = db.execute(
        text("""
            SELECT * FROM contract_audit_log
            WHERE order_id = :id ORDER BY performed_at ASC
        """),
        {"id": order_id},
    ).mappings().all()
    return {
        "order":    _order_to_dict(order),
        "checkins": [dict(c) for c in checkins],
        "audit":    [dict(a) for a in audit],
    }


# ────────────────────────────────────────────────────────────────────────────
# VENDOR EMAIL CONFIRMATION (link in email)
# ────────────────────────────────────────────────────────────────────────────

@router.post("/confirm/{token}")
def vendor_confirm(token: str, db: Session = Depends(get_db)):
    row = db.execute(
        text("""
            SELECT o.id, o.order_code, o.item_id, o.vendor_id, o.quantity,
                   o.unit_price, o.expected_delivery, o.stage,
                   i.name AS item_name, i.unit,
                   v.name AS vendor_name, v.email AS vendor_email
            FROM procurement_orders o
            JOIN inventory_items i ON i.item_id = o.item_id
            JOIN vendors v ON v.id = o.vendor_id
            WHERE o.vendor_confirm_token = :token
        """),
        {"token": token},
    ).mappings().first()

    if not row:
        raise HTTPException(404, "Invalid or expired confirmation token")
    if row["stage"] not in ("Pending Verification", "Vendor Notified"):
        return {"message": f"Order {row['order_code']} already processed (stage: {row['stage']})"}

    order_id = str(row["id"])

    # Generate smart contract
    contract = create_smart_contract(
        order_code        = row["order_code"],
        item_name         = row["item_name"],
        quantity          = row["quantity"],
        unit              = row["unit"],
        vendor_name       = row["vendor_name"],
        vendor_email      = row["vendor_email"],
        unit_price        = row["unit_price"],
        expected_delivery = str(row["expected_delivery"]),
    )

    # Vendor auto-signs on confirmation
    contract_data = sign_contract(
        contract_hash = contract["contract_hash"],
        signatory     = row["vendor_name"],
        role          = "vendor",
        contract_data = contract["contract_data"],
    )

    db.execute(
        text("""
            UPDATE procurement_orders SET
              vendor_confirmed      = TRUE,
              vendor_confirmed_at   = NOW(),
              vendor_confirm_token  = NULL,
              stage                 = 'Contract Signed',
              contract_status       = 'Signed',
              contract_hash         = :hash,
              contract_signed_at    = NOW(),
              smart_contract_data   = :data::jsonb,
              updated_at            = NOW()
            WHERE id = :id
        """),
        {
            "hash": contract["contract_hash"],
            "data": json.dumps(contract_data),
            "id":   order_id,
        },
    )

    # Audit log
    db.execute(
        text("""
            INSERT INTO contract_audit_log
              (id, order_id, action, tx_hash, block_number, payload, performed_at)
            VALUES
              (:id, :oid, 'VendorConfirmed', :hash, :block, :payload::jsonb, NOW())
        """),
        {
            "id":      str(uuid.uuid4()),
            "oid":     order_id,
            "hash":    contract["contract_hash"],
            "block":   contract["block_number"],
            "payload": json.dumps({"vendor": row["vendor_name"]}),
        },
    )
    db.commit()

    # Notify vendor contract is ready
    send_contract_ready_email(
        vendor_email  = row["vendor_email"],
        vendor_name   = row["vendor_name"],
        order_code    = row["order_code"],
        contract_hash = contract["contract_hash"],
    )

    notify_vendor_confirmed(db, row["order_code"], row["vendor_name"])
    notify_contract_signed(db, row["order_code"], contract["contract_hash"])

    return {
        "message":       f"Order {row['order_code']} confirmed. Smart contract created.",
        "contract_hash": contract["contract_hash"],
        "contract_id":   contract_data["contract_id"],
    }


# ────────────────────────────────────────────────────────────────────────────
# OPERATOR SIGNS CONTRACT
# ────────────────────────────────────────────────────────────────────────────

@router.post("/sign/{order_id}")
def operator_sign(order_id: str, req: SignContractRequest, db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    if not order.get("contract_hash"):
        raise HTTPException(400, "No smart contract exists for this order yet")

    contract_data = order.get("smart_contract_data") or {}
    if isinstance(contract_data, str):
        contract_data = json.loads(contract_data)

    contract_data = sign_contract(
        contract_hash = order["contract_hash"],
        signatory     = req.signatory,
        role          = req.role,
        contract_data = contract_data,
    )

    new_status = "Signed" if contract_data.get("status") == "Signed" else "Pending"

    db.execute(
        text("""
            UPDATE procurement_orders SET
              contract_status   = :cs,
              smart_contract_data = :data::jsonb,
              updated_at        = NOW()
            WHERE id = :id
        """),
        {"cs": new_status, "data": json.dumps(contract_data), "id": order_id},
    )
    db.execute(
        text("""
            INSERT INTO contract_audit_log
              (id, order_id, action, tx_hash, payload, performed_at)
            VALUES (:id, :oid, :action, :hash, :payload::jsonb, NOW())
        """),
        {
            "id":      str(uuid.uuid4()),
            "oid":     order_id,
            "action":  "OperatorSigned",
            "hash":    order["contract_hash"],
            "payload": json.dumps({"signatory": req.signatory}),
        },
    )
    db.commit()
    return {
        "message":        "Contract signed successfully",
        "contract_status": new_status,
        "contract_data":  contract_data,
    }


# ────────────────────────────────────────────────────────────────────────────
# DELIVERY CHECK-IN
# ────────────────────────────────────────────────────────────────────────────

@router.post("/checkin/{order_id}")
def delivery_checkin(
    order_id: str,
    req: DeliveryCheckinRequest,
    db: Session = Depends(get_db),
):
    order = _get_order(db, order_id)

    checkin_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO delivery_checkins
              (id, order_id, checked_by, location, status,
               quantity_received, condition, notes, is_final, checkin_at)
            VALUES
              (:id, :oid, :by, :loc, :status,
               :qty, :cond, :notes, :final, NOW())
        """),
        {
            "id":     checkin_id,
            "oid":    order_id,
            "by":     req.checked_by,
            "loc":    req.location,
            "status": req.status,
            "qty":    req.quantity_received,
            "cond":   req.condition,
            "notes":  req.notes,
            "final":  req.is_final,
        },
    )

    # Append to tracking_events on the order
    tracking_event = {
        "ts":       datetime.utcnow().isoformat() + "Z",
        "status":   req.status,
        "location": req.location,
        "notes":    req.notes or "",
    }
    db.execute(
        text("""
            UPDATE procurement_orders SET
              tracking_events = tracking_events || :evt::jsonb,
              updated_at = NOW()
            WHERE id = :id
        """),
        {"evt": json.dumps([tracking_event]), "id": order_id},
    )

    executed = False
    exec_result = None

    # Final check-in: auto-execute contract if delivery is Good
    if req.is_final:
        new_stage = "Delivered"
        db.execute(
            text("""
                UPDATE procurement_orders SET
                  stage = 'Delivered',
                  actual_delivery = NOW()::DATE,
                  delivery_confirmed = TRUE,
                  delivery_confirmed_at = NOW(),
                  delivery_confirmed_by = :by,
                  delivery_condition = :cond,
                  delivery_notes = :notes,
                  updated_at = NOW()
                WHERE id = :id
            """),
            {
                "by":    req.checked_by,
                "cond":  req.condition,
                "notes": req.notes,
                "id":    order_id,
            },
        )

        contract_data = order.get("smart_contract_data") or {}
        if isinstance(contract_data, str):
            contract_data = json.loads(contract_data)

        if req.condition == "Good" and order.get("contract_hash"):
            exec_result = execute_contract(order["contract_hash"], contract_data)
            db.execute(
                text("""
                    UPDATE procurement_orders SET
                      contract_status = 'Executed',
                      contract_executed_at = NOW(),
                      smart_contract_data = :data::jsonb
                    WHERE id = :id
                """),
                {"data": json.dumps(exec_result["contract_data"]), "id": order_id},
            )
            db.execute(
                text("""
                    INSERT INTO contract_audit_log
                      (id, order_id, action, tx_hash, payload, performed_at)
                    VALUES (:id, :oid, 'Executed', :hash, :payload::jsonb, NOW())
                """),
                {
                    "id":      str(uuid.uuid4()),
                    "oid":     order_id,
                    "action":  "Executed",
                    "hash":    exec_result["execution_hash"],
                    "payload": json.dumps({"condition": req.condition}),
                },
            )
            executed = True

        elif req.condition == "Damaged" and order.get("contract_hash"):
            reject_contract(order["contract_hash"], contract_data, "Damaged delivery")
            db.execute(
                text("""UPDATE procurement_orders
                         SET contract_status='Rejected', updated_at=NOW()
                         WHERE id=:id"""),
                {"id": order_id},
            )

        # Update inventory stock after delivery
        if req.condition in ("Good", "Partial"):
            db.execute(
                text("""
                    UPDATE inventory_items
                    SET current_stock = current_stock + :qty,
                        last_updated  = NOW()
                    WHERE item_id = :item_id
                """),
                {"qty": req.quantity_received, "item_id": order["item_id"]},
            )
            _update_inventory_status(db, order["item_id"])

        # Send vendor delivery email
        send_delivery_notification_email(
            vendor_email      = order["vendor_email"],
            vendor_name       = order["vendor_name"],
            order_code        = order["order_code"],
            condition         = req.condition,
            quantity_received = req.quantity_received,
            unit              = order["unit"],
        )

    db.commit()

    notify_delivery_checkin(
        db,
        order_code        = order["order_code"],
        item_name         = order["item_name"],
        condition         = req.condition,
        quantity_received = req.quantity_received,
    )

    return {
        "checkin_id":        checkin_id,
        "message":           f"Check-in recorded. Condition: {req.condition}.",
        "contract_executed": executed,
        "execution_hash":    exec_result["execution_hash"] if exec_result else None,
    }


# ────────────────────────────────────────────────────────────────────────────
# GET CHECK-INS FOR AN ORDER
# ────────────────────────────────────────────────────────────────────────────

@router.get("/checkins/{order_id}")
def get_checkins(order_id: str, db: Session = Depends(get_db)):
    rows = db.execute(
        text("""
            SELECT * FROM delivery_checkins
            WHERE order_id = :id ORDER BY checkin_at ASC
        """),
        {"id": order_id},
    ).mappings().all()
    return {"checkins": [dict(r) for r in rows]}


# ────────────────────────────────────────────────────────────────────────────
# MANUAL REORDER (quick path)
# ────────────────────────────────────────────────────────────────────────────

@router.post("/manual-reorder")
def manual_reorder(req: ManualReorderRequest, db: Session = Depends(get_db)):
    item = _get_item(db, req.item_id)
    return create_order(
        CreateOrderRequest(
            item_id      = req.item_id,
            quantity     = req.quantity or item["reorder_quantity"],
            unit_price   = req.unit_price,
            trigger_type = "Manual",
        ),
        db,
    )
