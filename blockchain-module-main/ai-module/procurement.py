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
import os, secrets, uuid, json
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
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
    notify_role,
)
from n8n_service import trigger_vendor_reorder_email, trigger_contract_confirmation_email
from rbac import require_role, ROLE_PROCUREMENT_MANAGER, get_current_user
from stock_thresholds import stock_status

router = APIRouter(prefix="/api/procurement", tags=["Procurement"])
_pm = Depends(require_role(ROLE_PROCUREMENT_MANAGER))

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


# ────────────────────────────────────────────────────────────────────────────
# Pydantic models
# ────────────────────────────────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    item_id:           str
    quantity:          float = Field(gt=0)            # no zero/negative orders (or totals)
    unit_price:        Optional[float] = Field(default=None, ge=0)
    trigger_type:      str = "Manual"    # VEMA-Triggered | Auto-Generated | Manual
    triggered_by:      Optional[str] = None
    expected_delivery: Optional[str] = None   # YYYY-MM-DD, default +14 days


class DeliveryCheckinRequest(BaseModel):
    location:          Optional[str] = "Main Warehouse"
    status:            str            # Arrived at Warehouse | Inspected | Accepted | Rejected
    quantity_received: float = Field(ge=0)
    condition:         str            # Good | Partial | Damaged
    notes:             Optional[str] = None
    is_final:          bool = False
    checked_by:        Optional[str] = None


class SignContractRequest(BaseModel):
    signatory:  str   # operator name / user ID
    role:       str = "operator"


class ManualReorderRequest(BaseModel):
    item_id:    str
    quantity:   float = Field(gt=0)
    unit_price: Optional[float] = Field(default=None, ge=0)


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
    status = stock_status(item["current_stock"], item["min_threshold"])
    db.execute(
        text("UPDATE inventory_items SET status=:s, last_updated=NOW() WHERE item_id=:id"),
        {"s": status, "id": item_id},
    )


def _validate_order_amounts(quantity: float, unit_price: Optional[float] = None):
    """Same rules as the frontend's src/lib/validation.ts — plain 400s so the
    UI's apiFetch can show the message (a pydantic 422 detail is a list)."""
    if quantity is None or quantity <= 0:
        raise HTTPException(400, "Quantity cannot be negative" if quantity is not None and quantity < 0
                            else "Quantity must be greater than 0")
    if unit_price is not None and unit_price < 0:
        raise HTTPException(400, "Unit price cannot be negative")


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

@router.post("/orders", dependencies=[_pm])
def create_order(req: CreateOrderRequest, db: Session = Depends(get_db)):
    _validate_order_amounts(req.quantity, req.unit_price)
    item = _get_item(db, req.item_id)
    if not item.get("vendor_name"):
        raise HTTPException(400, "Item has no vendor assigned")

    order_id      = str(uuid.uuid4())
    order_code    = "ORD-" + uuid.uuid4().hex[:6].upper()
    confirm_token = generate_confirm_token()
    delivery_date = req.expected_delivery or (
        datetime.now() + timedelta(days=14)
    ).strftime("%Y-%m-%d")
    unit_price = req.unit_price if req.unit_price is not None else item.get("unit_price")
    total_price = (
        round(float(req.quantity) * float(unit_price), 2) if unit_price is not None else None
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
            "unit_price": unit_price, "total_price": total_price,
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

    # Log the send so this order appears in the Vendor Communication panel.
    # Manual / directly-placed orders email the vendor here (not via the n8n
    # approve flow), so without this row they'd never show up there.
    db.execute(
        text("""
            INSERT INTO vendor_comm_log (id, order_id, channel, status, triggered_by, response_body, sent_at)
            VALUES (:id, :oid, 'direct-email', :status, :uid, :body, NOW())
        """),
        {
            "id": str(uuid.uuid4()), "oid": order_id,
            "status": "Sent" if sent else "Failed",
            "uid": req.triggered_by,
            "body": (
                f"Purchase order {order_code} emailed to {item['vendor_email']}"
                if sent else
                f"Vendor email for {order_code} could not be sent"
            ),
        },
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

@router.get("/orders", dependencies=[_pm])
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

@router.get("/orders/{order_id}", dependencies=[_pm])
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
    # (quantity/unit_price come back as decimal.Decimal from NUMERIC columns —
    # cast to float here since contract_service.py JSON-serializes the payload
    # and doesn't know about SQL types; contract_service.py itself is unmodified)
    contract = create_smart_contract(
        order_code        = row["order_code"],
        item_name         = row["item_name"],
        quantity          = float(row["quantity"]),
        unit              = row["unit"],
        vendor_name       = row["vendor_name"],
        vendor_email      = row["vendor_email"],
        unit_price        = float(row["unit_price"]) if row["unit_price"] is not None else None,
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
              smart_contract_data   = CAST(:data AS jsonb),
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
              (:id, :oid, 'VendorConfirmed', :hash, :block, CAST(:payload AS jsonb), NOW())
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

@router.post("/sign/{order_id}", dependencies=[_pm])
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
              smart_contract_data = CAST(:data AS jsonb),
              updated_at        = NOW()
            WHERE id = :id
        """),
        {"cs": new_status, "data": json.dumps(contract_data), "id": order_id},
    )
    db.execute(
        text("""
            INSERT INTO contract_audit_log
              (id, order_id, action, tx_hash, payload, performed_at)
            VALUES (:id, :oid, :action, :hash, CAST(:payload AS jsonb), NOW())
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

@router.post("/checkin/{order_id}", dependencies=[_pm])
def delivery_checkin(
    order_id: str,
    req: DeliveryCheckinRequest,
    db: Session = Depends(get_db),
):
    if req.quantity_received < 0:
        raise HTTPException(400, "Quantity received cannot be negative")
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
              tracking_events = tracking_events || CAST(:evt AS jsonb),
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
                      smart_contract_data = CAST(:data AS jsonb)
                    WHERE id = :id
                """),
                {"data": json.dumps(exec_result["contract_data"]), "id": order_id},
            )
            db.execute(
                text("""
                    INSERT INTO contract_audit_log
                      (id, order_id, action, tx_hash, payload, performed_at)
                    VALUES (:id, :oid, 'Executed', :hash, CAST(:payload AS jsonb), NOW())
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

@router.get("/checkins/{order_id}", dependencies=[_pm])
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

@router.post("/manual-reorder", dependencies=[_pm])
def manual_reorder(req: ManualReorderRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    _validate_order_amounts(req.quantity, req.unit_price)
    item = _get_item(db, req.item_id)
    return create_order(
        CreateOrderRequest(
            item_id      = req.item_id,
            quantity     = req.quantity or item["reorder_quantity"],
            unit_price   = req.unit_price,
            trigger_type = "Manual",
            triggered_by = user["id"],
        ),
        db,
    )


# ────────────────────────────────────────────────────────────────────────────
# INVOICE / BILLING
# ────────────────────────────────────────────────────────────────────────────

@router.get("/orders/{order_id}/invoice", dependencies=[_pm])
def get_order_invoice(order_id: str, db: Session = Depends(get_db)):
    from invoice_service import generate_invoice_data
    order = _get_order(db, order_id)
    return generate_invoice_data(order)


@router.get("/orders/{order_id}/invoice/pdf", dependencies=[_pm])
def get_order_invoice_pdf(order_id: str, db: Session = Depends(get_db)):
    from fastapi.responses import Response
    from invoice_service import generate_invoice_data, generate_invoice_pdf
    order = _get_order(db, order_id)
    invoice = generate_invoice_data(order)
    pdf_bytes = generate_invoice_pdf(invoice)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f"attachment; filename=invoice-{order['order_code']}.pdf"
        }
    )


# ────────────────────────────────────────────────────────────────────────────
# AUTOMATED REORDERING — Admin / Procurement Manager approval workflow
# (Section 3). Triggered by inventory_v2.run_inventory_check() for every
# auto-reorder trigger — Critical (<=20% of min_threshold), Low, and
# Demand > Stock — so no vendor is ever emailed without a human sign-off.
# Reuses create_smart_contract / execute_contract / reject_contract /
# generate_invoice_data / generate_invoice_pdf as-is — nothing in
# contract_service.py or invoice_service.py is touched here.
#
# Lifecycle:
#   auto trigger -> cheapest vendor picked, smart contract created, stage='Pending PM Approval'
#     -> Admin/PM approves -> n8n emails vendor an Accept/Reject link, stage='Vendor Notified'
#        Admin/PM rejects  -> contract rejected, stage='Cancelled by PM'
#     -> vendor Accept -> contract executed, stage='Order Placed'
#        vendor Reject -> contract rejected, stage='Vendor Rejected' (needs manual follow-up)
# ────────────────────────────────────────────────────────────────────────────

def select_lowest_price_vendor(db: Session, item: dict, quantity: float) -> Optional[dict]:
    """
    Pick the vendor to reorder `item` from: the one with the lowest unit
    price among the item's default vendor (inventory_items.vendor_id at
    inventory_items.unit_price) and every active approved vendor whose
    catalogue (vendor_items) carries the same item in the same unit and
    whose MOQ the reorder quantity meets. A catalogue row matches via its
    inventory_item_id link, or — if unlinked — by exact case-insensitive
    name. Ties go to the default vendor, then the shorter lead time.

    Returns {"vendor_id", "vendor_name", "vendor_email", "unit_price",
    "source", "vendor_item_id", "lead_time_days", "candidates": [...]}
    or None when no vendor can supply the item.
    """
    candidates = []

    if item.get("vendor_id"):
        default = db.execute(
            text("""
                SELECT id, name, email FROM vendors
                WHERE id = :id AND COALESCE(status, 'active') = 'active'
                  AND COALESCE(is_active, TRUE)
            """),
            {"id": item["vendor_id"]},
        ).mappings().first()
        if default:
            candidates.append({
                "vendor_id": str(default["id"]), "vendor_name": default["name"],
                "vendor_email": default["email"],
                "unit_price": float(item["unit_price"]) if item.get("unit_price") is not None else None,
                "source": "inventory_default", "vendor_item_id": None, "lead_time_days": None,
            })

    rows = db.execute(
        text("""
            SELECT vi.id AS vendor_item_id, vi.unit_price, vi.lead_time_days,
                   v.id AS vendor_id, v.name AS vendor_name, v.email AS vendor_email
            FROM vendor_items vi
            JOIN vendors v ON v.id = vi.vendor_id
            WHERE vi.is_active = TRUE
              AND v.status = 'active' AND COALESCE(v.is_active, TRUE)
              AND (vi.inventory_item_id = :item_id
                   OR (vi.inventory_item_id IS NULL AND LOWER(TRIM(vi.name)) = LOWER(TRIM(:name))))
              AND LOWER(TRIM(vi.unit)) = LOWER(TRIM(:unit))
              AND (vi.moq IS NULL OR vi.moq <= :qty)
        """),
        {"item_id": item["item_id"], "name": item["name"], "unit": item["unit"], "qty": float(quantity)},
    ).mappings().all()
    for r in rows:
        candidates.append({
            "vendor_id": str(r["vendor_id"]), "vendor_name": r["vendor_name"],
            "vendor_email": r["vendor_email"], "unit_price": float(r["unit_price"]),
            "source": "vendor_catalogue", "vendor_item_id": str(r["vendor_item_id"]),
            "lead_time_days": r["lead_time_days"],
        })

    if not candidates:
        return None

    def _rank(c: dict):
        return (
            c["unit_price"] is None,                     # priced offers first
            c["unit_price"] if c["unit_price"] is not None else 0,
            c["source"] != "inventory_default",          # tie -> default vendor
            c["lead_time_days"] if c["lead_time_days"] is not None else float("inf"),
        )

    # One entry per vendor (its cheapest offer), cheapest vendor first.
    best_per_vendor: dict = {}
    for c in sorted(candidates, key=_rank):
        best_per_vendor.setdefault(c["vendor_id"], c)
    ranked = list(best_per_vendor.values())

    return {**ranked[0], "candidates": ranked}


def _given_vendor_selection(item: dict) -> Optional[dict]:
    """The vendor/price already set on `item`, as a one-candidate selection."""
    if not item.get("vendor_id") or not item.get("vendor_name"):
        return None
    candidate = {
        "vendor_id": str(item["vendor_id"]), "vendor_name": item["vendor_name"],
        "vendor_email": item.get("vendor_email"),
        "unit_price": float(item["unit_price"]) if item.get("unit_price") is not None else None,
        "source": "given", "vendor_item_id": None, "lead_time_days": None,
    }
    return {**candidate, "candidates": [candidate]}


def create_pending_approval_order(
    db: Session,
    item: dict,
    trigger_type: str = "VEMA-Triggered",
    reason: str = "stock below 21% of min_threshold",
    pick_lowest_price_vendor: bool = False,
) -> dict:
    """
    Creates the order + smart contract immediately, but does NOT email the
    vendor yet — that only happens once an Admin or Procurement Manager
    approves it.

    pick_lowest_price_vendor=True (inventory_v2's auto-reorder trigger and
    startup check): choose the cheapest vendor via select_lowest_price_vendor.
    Default False: use the vendor/unit_price already on `item` unchanged —
    vema_reorder_router.approve_vema_request relies on this to keep the
    vendor its approver picked.
    """
    quantity = item["reorder_quantity"]
    selection = (select_lowest_price_vendor(db, item, quantity) if pick_lowest_price_vendor
                 else _given_vendor_selection(item))
    if not selection:
        return {"skipped": True, "item_id": item["item_id"], "reason": "no vendor supplies this item"}

    order_id   = str(uuid.uuid4())
    order_code = "ORD-" + uuid.uuid4().hex[:6].upper()
    unit_price = selection["unit_price"]
    total_price = round(float(quantity) * float(unit_price), 2) if unit_price is not None else None
    delivery_date = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")
    below_20pct = item.get("status") in ("Critical", "Out of Stock")

    contract = create_smart_contract(
        order_code        = order_code,
        item_name         = item["name"],
        quantity          = float(quantity),
        unit              = item["unit"],
        vendor_name       = selection["vendor_name"],
        vendor_email      = selection["vendor_email"],
        unit_price        = unit_price,
        expected_delivery = delivery_date,
    )

    db.execute(
        text("""
            INSERT INTO procurement_orders (
              id, order_code, item_id, vendor_id, quantity, unit,
              unit_price, total_price, trigger_type, stage,
              expected_delivery, tracking_events,
              below_20pct_trigger, pm_approval_status,
              contract_status, contract_hash, smart_contract_data,
              vendor_selection, created_at, updated_at
            ) VALUES (
              :id, :code, :item_id, :vendor_id, :qty, :unit,
              :unit_price, :total_price, :trigger, 'Pending PM Approval',
              :delivery, '[]'::jsonb,
              :below_20pct, 'Pending',
              'Pending', :hash, CAST(:contract_data AS jsonb),
              CAST(:selection AS jsonb), NOW(), NOW()
            )
        """),
        {
            "id": order_id, "code": order_code,
            "item_id": item["item_id"], "vendor_id": selection["vendor_id"],
            "qty": quantity, "unit": item["unit"],
            "unit_price": unit_price, "total_price": total_price,
            "trigger": trigger_type, "below_20pct": below_20pct,
            "delivery": delivery_date,
            "hash": contract["contract_hash"],
            "contract_data": json.dumps(contract["contract_data"]),
            "selection": json.dumps({
                "rule": "lowest_unit_price",
                "selected_vendor_id": selection["vendor_id"],
                "candidates": selection["candidates"],
            }),
        },
    )
    db.execute(
        text("""
            INSERT INTO contract_audit_log (id, order_id, action, tx_hash, block_number, payload, performed_at)
            VALUES (:id, :oid, 'Created', :hash, :block, CAST(:payload AS jsonb), NOW())
        """),
        {
            "id": str(uuid.uuid4()), "oid": order_id,
            "hash": contract["contract_hash"], "block": contract["block_number"],
            "payload": json.dumps({
                "reason": reason,
                "vendor_selection": f"lowest unit price of {len(selection['candidates'])} vendor(s)",
            }),
        },
    )
    db.commit()

    n_vendors = len(selection["candidates"])
    price_note = (
        f" — lowest unit price of {n_vendors} vendors"
        if n_vendors > 1 else ""
    )
    for role in (ROLE_PROCUREMENT_MANAGER, "admin"):
        try:
            notify_role(
                db, role,
                category    = "Procurement Approvals",
                title       = f"Reorder Approval Needed — {item['name']}",
                description = (
                    f"{item['name']} stock is at {item['current_stock']} {item['unit']} ({reason}). "
                    f"A smart contract order for {quantity} {item['unit']} from "
                    f"{selection['vendor_name']}{price_note} is awaiting approval. "
                    f"The vendor will not be emailed until it is approved."
                ),
                metadata    = {"order_id": order_id, "order_code": order_code, "item_id": item["item_id"]},
            )
        except Exception as e:
            # Non-fatal — the order is already committed and visible in both
            # approvals queues; a failed notification mustn't undo or abort it.
            db.rollback()
            print(f"[WARN] Approval notification to {role} failed for {order_code}: {e}")

    return {
        "order_id": order_id, "order_code": order_code, "stage": "Pending PM Approval",
        "vendor_name": selection["vendor_name"], "unit_price": unit_price,
    }


@router.get("/pending-approvals", dependencies=[_pm])
def list_pending_approvals(db: Session = Depends(get_db)):
    rows = db.execute(
        text("""
            SELECT o.*, i.name AS item_name, i.unit,
                   v.name AS vendor_name, v.email AS vendor_email
            FROM procurement_orders o
            JOIN inventory_items i ON i.item_id = o.item_id
            JOIN vendors v ON v.id = o.vendor_id
            WHERE o.pm_approval_status = 'Pending'
            ORDER BY o.created_at DESC
        """)
    ).mappings().all()
    return {"orders": [_order_to_dict(dict(r)) for r in rows]}


@router.post("/approve/{order_id}", dependencies=[_pm])
def approve_reorder(order_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    from invoice_service import generate_invoice_data

    order = _get_order(db, order_id)
    if order["pm_approval_status"] != "Pending":
        raise HTTPException(400, f"Order is not pending approval (status: {order['pm_approval_status']})")

    token = secrets.token_urlsafe(32)
    db.execute(
        text("""
            UPDATE procurement_orders SET
              pm_approval_status = 'Approved',
              pm_approved_by     = :uid,
              pm_approved_at     = NOW(),
              vendor_response_token = :token,
              updated_at = NOW()
            WHERE id = :id
        """),
        {"uid": user["id"], "token": token, "id": order_id},
    )
    db.commit()

    order = _get_order(db, order_id)
    invoice = generate_invoice_data(order)
    accept_url = f"{BASE_URL}/api/procurement/vendor-response/{order_id}?decision=accept&token={token}"
    reject_url = f"{BASE_URL}/api/procurement/vendor-response/{order_id}?decision=reject&token={token}"
    invoice_pdf_url = f"{BASE_URL}/api/procurement/vendor-invoice/{order_id}?token={token}"

    result = trigger_vendor_reorder_email(order, invoice, accept_url, reject_url, invoice_pdf_url)

    db.execute(
        text("""
            INSERT INTO vendor_comm_log (id, order_id, channel, status, triggered_by, response_body, sent_at)
            VALUES (:id, :oid, 'n8n-email', :status, :uid, :body, NOW())
        """),
        {
            "id": str(uuid.uuid4()), "oid": order_id,
            "status": result["status"], "uid": user["id"], "body": result["response_body"],
        },
    )
    db.execute(
        text("UPDATE procurement_orders SET stage='Vendor Notified', vendor_email_sent=TRUE, vendor_email_sent_at=NOW() WHERE id=:id"),
        {"id": order_id},
    )
    db.commit()

    return {
        "message": f"Order {order['order_code']} approved. Vendor email {result['status'].lower()}.",
        "vendor_email_status": result["status"],
    }


class EditReorderRequest(BaseModel):
    quantity:          float = Field(gt=0)
    expected_delivery: Optional[str] = None   # YYYY-MM-DD, today or later


@router.put("/approvals/{order_id}", dependencies=[Depends(require_role())])
def edit_pending_reorder(order_id: str, req: EditReorderRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """
    Admin-only: change a pending auto-reorder's quantity (and optionally its
    expected delivery date) before approving it. The vendor and unit price
    stay as picked by select_lowest_price_vendor. The pending smart contract
    was issued with the old terms, so it is rejected as superseded and a new
    one is created with the new terms — both via contract_service as-is —
    and both steps are written to contract_audit_log. All in one commit.
    """
    order = _get_order(db, order_id)
    if order["pm_approval_status"] != "Pending":
        raise HTTPException(400, f"Only a pending reorder can be edited (status: {order['pm_approval_status']})")

    new_qty = float(req.quantity)
    old_qty = float(order["quantity"])
    old_delivery = str(order["expected_delivery"]) if order.get("expected_delivery") else None
    new_delivery = old_delivery
    if req.expected_delivery:
        try:
            parsed = datetime.strptime(req.expected_delivery, "%Y-%m-%d").date()
        except ValueError:
            raise HTTPException(400, "Expected delivery must be a date (YYYY-MM-DD)")
        if parsed < datetime.now().date():
            raise HTTPException(400, "Expected delivery cannot be in the past")
        new_delivery = parsed.isoformat()

    if new_qty == old_qty and new_delivery == old_delivery:
        raise HTTPException(400, "Nothing changed")

    unit_price = float(order["unit_price"]) if order.get("unit_price") is not None else None
    total_price = round(new_qty * unit_price, 2) if unit_price is not None else None
    changes = {}
    if new_qty != old_qty:
        changes["quantity"] = {"from": old_qty, "to": new_qty}
    if new_delivery != old_delivery:
        changes["expected_delivery"] = {"from": old_delivery, "to": new_delivery}

    old_data = order.get("smart_contract_data") or {}
    if isinstance(old_data, str):
        old_data = json.loads(old_data)
    if order.get("contract_hash"):
        rejected = reject_contract(order["contract_hash"], old_data, "Superseded — reorder edited by admin before approval")
        db.execute(
            text("""
                INSERT INTO contract_audit_log (id, order_id, action, performed_by, tx_hash, payload, performed_at)
                VALUES (:id, :oid, 'Rejected', :uid, :hash, CAST(:payload AS jsonb), NOW())
            """),
            {"id": str(uuid.uuid4()), "oid": order_id, "uid": user["id"], "hash": order["contract_hash"],
             "payload": json.dumps({"reason": "superseded by edit", "contract": rejected})},
        )

    contract = create_smart_contract(
        order_code        = order["order_code"],
        item_name         = order["item_name"],
        quantity          = new_qty,
        unit              = order["unit"],
        vendor_name       = order["vendor_name"],
        vendor_email      = order["vendor_email"],
        unit_price        = unit_price,
        expected_delivery = new_delivery,
    )
    db.execute(
        text("""
            UPDATE procurement_orders SET
              quantity = :qty, total_price = :total, expected_delivery = :delivery,
              contract_hash = :hash, smart_contract_data = CAST(:data AS jsonb),
              contract_status = 'Pending', updated_at = NOW()
            WHERE id = :id
        """),
        {"qty": new_qty, "total": total_price, "delivery": new_delivery, "hash": contract["contract_hash"],
         "data": json.dumps(contract["contract_data"]), "id": order_id},
    )
    db.execute(
        text("""
            INSERT INTO contract_audit_log (id, order_id, action, performed_by, tx_hash, block_number, payload, performed_at)
            VALUES (:id, :oid, 'Created', :uid, :hash, :block, CAST(:payload AS jsonb), NOW())
        """),
        {"id": str(uuid.uuid4()), "oid": order_id, "uid": user["id"], "hash": contract["contract_hash"],
         "block": contract["block_number"], "payload": json.dumps({"reason": "reorder edited by admin", "changes": changes})},
    )
    db.commit()

    return {
        "message": f"{order['order_code']} updated — new smart contract issued.",
        "order": _order_to_dict(_get_order(db, order_id)),
        "changes": changes,
    }


class RejectApprovalRequest(BaseModel):
    reason: Optional[str] = None


@router.post("/reject/{order_id}", dependencies=[_pm])
def reject_reorder(order_id: str, req: RejectApprovalRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    if order["pm_approval_status"] != "Pending":
        raise HTTPException(400, f"Order is not pending approval (status: {order['pm_approval_status']})")

    contract_data = order.get("smart_contract_data") or {}
    if isinstance(contract_data, str):
        contract_data = json.loads(contract_data)
    reject_contract(order["contract_hash"], contract_data, req.reason or "Rejected by Procurement Manager")

    db.execute(
        text("""
            UPDATE procurement_orders SET
              pm_approval_status = 'Rejected',
              pm_approved_by     = :uid,
              pm_approved_at     = NOW(),
              pm_decision_notes  = :notes,
              stage              = 'Cancelled by PM',
              contract_status    = 'Rejected',
              updated_at = NOW()
            WHERE id = :id
        """),
        {"uid": user["id"], "notes": req.reason, "id": order_id},
    )
    db.commit()

    notify_role(db, ROLE_PROCUREMENT_MANAGER, "Procurement Approvals",
                f"Reorder Rejected — {order['order_code']}",
                f"You rejected the auto-triggered reorder for {order['item_name']}. No vendor email was sent.")
    return {"message": f"Order {order['order_code']} rejected. No vendor email sent."}


@router.post("/vendor-response/{order_id}")
def vendor_response(
    order_id: str,
    decision: str = Query(..., pattern="^(accept|reject)$"),
    token: str = Query(...),
    db: Session = Depends(get_db),
):
    """
    Public — reached from the Accept/Reject buttons in the n8n vendor email.
    Authenticated by the per-order signed token, not a login (the vendor has
    no NEXUS ERP account). Mirrors /confirm/{token}'s "public, token-secured"
    pattern used by the existing manual-order flow.
    """
    order = _get_order(db, order_id)
    if order["vendor_response_token"] != token or not token:
        raise HTTPException(404, "Invalid or expired response link")
    if order["pm_approval_status"] != "Approved":
        raise HTTPException(400, "This order is not awaiting a vendor response")
    if order.get("vendor_decision"):
        return {"message": f"Order {order['order_code']} already recorded a vendor decision: {order['vendor_decision']}"}

    contract_data = order.get("smart_contract_data") or {}
    if isinstance(contract_data, str):
        contract_data = json.loads(contract_data)

    if decision == "accept":
        contract_data = sign_contract(order["contract_hash"], order["vendor_name"], "vendor", contract_data)
        exec_result = execute_contract(order["contract_hash"], contract_data)
        db.execute(
            text("""
                UPDATE procurement_orders SET
                  vendor_decision = 'Accepted', vendor_responded_at = NOW(),
                  stage = 'Order Placed', contract_status = 'Executed',
                  contract_executed_at = NOW(), vendor_confirmed = TRUE, vendor_confirmed_at = NOW(),
                  smart_contract_data = CAST(:data AS jsonb), updated_at = NOW()
                WHERE id = :id
            """),
            {"data": json.dumps(exec_result["contract_data"]), "id": order_id},
        )
        db.commit()
        notify_role(db, "admin", "Confirmations", f"Reorder Placed — {order['order_code']}",
                    f"The reorder has been placed — {order['item_name']}, {order['vendor_name']}, "
                    f"{order['quantity']:.0f} {order['unit']}.")
        notify_role(db, ROLE_PROCUREMENT_MANAGER, "Confirmations", f"Reorder Placed — {order['order_code']}",
                    f"The reorder has been placed — {order['item_name']}, {order['vendor_name']}, "
                    f"{order['quantity']:.0f} {order['unit']}.")

        # Send the vendor a copy of the now-executed smart contract / bill,
        # confirming the order is locked in. Reuses the same
        # vendor_response_token (not cleared on accept) for the invoice link —
        # same token-secured pattern the initial reorder email already uses.
        from invoice_service import generate_invoice_data
        confirmed_order = _get_order(db, order_id)
        invoice = generate_invoice_data(confirmed_order)
        invoice_pdf_url = f"{BASE_URL}/api/procurement/vendor-invoice/{order_id}?token={token}"
        confirm_result = trigger_contract_confirmation_email(
            confirmed_order, invoice, invoice_pdf_url,
            order["contract_hash"], exec_result["execution_hash"],
        )
        db.execute(
            text("""
                INSERT INTO vendor_comm_log (id, order_id, channel, status, triggered_by, response_body, sent_at)
                VALUES (:id, :oid, 'n8n-contract-confirmation', :status, NULL, :body, NOW())
            """),
            {
                "id": str(uuid.uuid4()), "oid": order_id,
                "status": confirm_result["status"], "body": confirm_result["response_body"],
            },
        )
        db.commit()

        return {"message": f"Order {order['order_code']} accepted. Smart contract executed. Confirmation copy sent to vendor."}
    else:
        reject_contract(order["contract_hash"], contract_data, "Vendor rejected the reorder")
        db.execute(
            text("""
                UPDATE procurement_orders SET
                  vendor_decision = 'Rejected', vendor_responded_at = NOW(),
                  stage = 'Vendor Rejected', contract_status = 'Rejected', updated_at = NOW()
                WHERE id = :id
            """),
            {"id": order_id},
        )
        db.commit()
        msg = (f"Vendor {order['vendor_name']} declined reorder {order['order_code']} "
               f"({order['item_name']}). Manual follow-up needed.")
        notify_role(db, "admin", "Updates", f"Reorder Declined — {order['order_code']}", msg)
        notify_role(db, ROLE_PROCUREMENT_MANAGER, "Updates", f"Reorder Declined — {order['order_code']}", msg)
        return {"message": f"Order {order['order_code']} rejected by vendor. Contract not finalized."}


@router.get("/vendor-invoice/{order_id}")
def vendor_invoice_pdf(order_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    """Public, token-secured invoice download for the vendor email's invoice link."""
    from fastapi.responses import Response
    from invoice_service import generate_invoice_data, generate_invoice_pdf

    order = _get_order(db, order_id)
    if order["vendor_response_token"] != token or not token:
        raise HTTPException(404, "Invalid or expired invoice link")
    invoice = generate_invoice_data(order)
    pdf_bytes = generate_invoice_pdf(invoice)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=invoice-{order['order_code']}.pdf"},
    )


@router.get("/vendor-comm-log/{order_id}", dependencies=[_pm])
def get_vendor_comm_log(order_id: str, db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT * FROM vendor_comm_log WHERE order_id = :id ORDER BY sent_at DESC"),
        {"id": order_id},
    ).mappings().all()
    return {"log": [dict(r) for r in rows]}


@router.post("/vendor-comm-log/{order_id}/resend", dependencies=[_pm])
def resend_vendor_email(order_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Re-fires the same n8n vendor email using the order's existing token."""
    from invoice_service import generate_invoice_data

    order = _get_order(db, order_id)
    if not order.get("vendor_response_token"):
        raise HTTPException(400, "This order was never approved for a vendor email")

    token = order["vendor_response_token"]
    invoice = generate_invoice_data(order)
    accept_url = f"{BASE_URL}/api/procurement/vendor-response/{order_id}?decision=accept&token={token}"
    reject_url = f"{BASE_URL}/api/procurement/vendor-response/{order_id}?decision=reject&token={token}"
    invoice_pdf_url = f"{BASE_URL}/api/procurement/vendor-invoice/{order_id}?token={token}"

    result = trigger_vendor_reorder_email(order, invoice, accept_url, reject_url, invoice_pdf_url)
    db.execute(
        text("""
            INSERT INTO vendor_comm_log (id, order_id, channel, status, triggered_by, response_body, sent_at)
            VALUES (:id, :oid, 'n8n-email', :status, :uid, :body, NOW())
        """),
        {"id": str(uuid.uuid4()), "oid": order_id, "status": result["status"], "uid": user["id"], "body": result["response_body"]},
    )
    db.commit()
    return {"message": f"Vendor email resent ({result['status']}).", "vendor_email_status": result["status"]}

