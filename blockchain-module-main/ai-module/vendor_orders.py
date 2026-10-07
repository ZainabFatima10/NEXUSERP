"""
NEXUS ERP — Vendor Orders (Phase 2)
Order -> vendor accept (n8n, no vendor login) -> real on-chain smart
contract (ShipmentEscrow via shipment_chain_service.py) -> shipment
tracking -> orderer approval/dispute -> execution -> payment capture ->
scheduled vendor payout -> invoice. All money is PKR; the payment
lifecycle itself lives in payments.py.

Entirely new tables/routes — procurement_orders / procurement.py (the
original low-stock auto-reorder flow) are untouched. "Receiver" always
means the orderer who placed the order; there is no separate receiver
field, and only the orderer can confirm arrival, approve receipt, or
dispute — enforced here, not just in the UI.
"""
import hashlib
import json
import os
import secrets
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from rbac import require_role, ROLE_ADMIN, ROLE_PROCUREMENT_MANAGER, get_current_user
from notification_engine import notify, auto_resolve
from n8n_service import (
    trigger_vendor_order_email,
    trigger_vendor_order_shipment_link_email,
    trigger_vendor_order_status_checkin_email,
)
import shipment_chain_service as chain
import payments
from invoice_service import generate_invoice_pdf

router = APIRouter(tags=["Vendor Orders"])
_staff = Depends(require_role(ROLE_PROCUREMENT_MANAGER))

BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:5173")
VENDOR_ORDER_RESPONSE_HOURS = int(os.getenv("VENDOR_ORDER_RESPONSE_HOURS", "72"))
VENDOR_REMINDER_HOURS_BEFORE_EXPIRY = int(os.getenv("VENDOR_REMINDER_HOURS_BEFORE_EXPIRY", "24"))
ARRIVAL_REMINDER_HOURS_AFTER_ETA = int(os.getenv("ARRIVAL_REMINDER_HOURS_AFTER_ETA", "24"))
APPROVAL_REMINDER_HOURS_AFTER_ARRIVAL = int(os.getenv("APPROVAL_REMINDER_HOURS_AFTER_ARRIVAL", "48"))
# 3x/day while a shipment is in flight (Preparing..OutForDelivery) — stops
# the moment it leaves those states (Arrived/Executed/Cancelled/Disputed).
VENDOR_STATUS_CHECKIN_INTERVAL_HOURS = int(os.getenv("VENDOR_STATUS_CHECKIN_INTERVAL_HOURS", "8"))
IN_FLIGHT_CONTRACT_STATUSES = ("Preparing", "Dispatched", "InTransit", "OutForDelivery")

SHIPPABLE_CONTRACT_STATUSES = ("Preparing", "Dispatched", "InTransit", "OutForDelivery")

# Rate limit for the public, multi-use shipment-update link — in-process,
# same documented limitation as the Phase 1 application rate limiter.
_SHIP_UPDATE_WINDOW_S = 3600
_SHIP_UPDATE_MAX_PER_ORDER = 20
_ship_update_log: dict = {}


def _check_ship_update_rate_limit(order_id: str):
    now = time.time()
    hits = [t for t in _ship_update_log.get(order_id, []) if now - t < _SHIP_UPDATE_WINDOW_S]
    if len(hits) >= _SHIP_UPDATE_MAX_PER_ORDER:
        raise HTTPException(429, "Too many shipment updates for this order recently — please try again later.")
    hits.append(now)
    _ship_update_log[order_id] = hits


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _destination_string(order: dict) -> str:
    """Canonical destination string — hashed identically at contract-create
    time and at confirm-arrival time; any drift would make confirmArrival
    revert with a (confusing) destination-mismatch error, so build this
    exactly the same way everywhere it's used."""
    parts = [order.get("destination_name") or "", order.get("destination_city") or "", order.get("destination_address") or ""]
    return " | ".join(p for p in parts if p)


def _order_terms_summary(items: List[dict]) -> str:
    """Deterministic string of the accepted items/qty/prices — hashed into
    orderHash, making the agreed terms tamper-evident."""
    rows = sorted(
        [f"{i['name']}|{i['sku'] or ''}|{i['unit']}|{float(i['quantity'])}|{float(i['unit_price'])}" for i in items]
    )
    return ";".join(rows)


def _get_order(db: Session, order_id: str) -> dict:
    row = db.execute(
        text("""
            SELECT o.*, v.name AS vendor_name, v.order_email AS vendor_email,
                   u.name AS orderer_name, u.email AS orderer_email
            FROM vendor_orders o
            JOIN vendors v ON v.id = o.vendor_id
            JOIN users u ON u.id = o.orderer_user_id
            WHERE o.id = :id
        """),
        {"id": order_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, f"Order {order_id} not found")
    return dict(row)

def _get_order_by_code(db: Session, order_code: str) -> Optional[dict]:
    row = db.execute(
        text("""
            SELECT o.*, v.name AS vendor_name, v.order_email AS vendor_email,
                   u.name AS orderer_name, u.email AS orderer_email
            FROM vendor_orders o
            JOIN vendors v ON v.id = o.vendor_id
            JOIN users u ON u.id = o.orderer_user_id
            WHERE o.order_code = :code
        """),
        {"code": order_code},
    ).mappings().first()
    return dict(row) if row else None


def _get_items(db: Session, order_id: str) -> List[dict]:
    rows = db.execute(
        text("SELECT * FROM vendor_order_items WHERE order_id = :id ORDER BY name"), {"id": order_id}
    ).mappings().all()
    return [dict(r) for r in rows]


def _get_shipment(db: Session, order_id: str) -> Optional[dict]:
    row = db.execute(text("SELECT * FROM shipments WHERE order_id = :id"), {"id": order_id}).mappings().first()
    return dict(row) if row else None


def _get_events(db: Session, order_id: str) -> List[dict]:
    rows = db.execute(
        text("SELECT * FROM shipment_events WHERE order_id = :id ORDER BY created_at ASC"), {"id": order_id}
    ).mappings().all()
    return [dict(r) for r in rows]


def _insert_event(
    db: Session, order_id: str, status: str, actor_type: str, *,
    location: str = None, note: str = None, actor_user_id: str = None, actor_label: str = None,
    chain_result: dict = None,
) -> str:
    event_id = str(uuid.uuid4())
    chain_result = chain_result or {}
    db.execute(
        text("""
            INSERT INTO shipment_events
              (id, order_id, status, location, note, actor_type, actor_user_id, actor_label,
               tx_hash, block_number, chain_confirmed_at, created_at)
            VALUES
              (:id, :oid, :status, :location, :note, :actor_type, :actor_user_id, :actor_label,
               :tx_hash, :block_number, :confirmed_at, NOW())
        """),
        {
            "id": event_id, "oid": order_id, "status": status, "location": location, "note": note,
            "actor_type": actor_type, "actor_user_id": actor_user_id, "actor_label": actor_label,
            "tx_hash": chain_result.get("tx_hash"), "block_number": chain_result.get("block_number"),
            "confirmed_at": datetime.now(timezone.utc) if chain_result.get("confirmed") else None,
        },
    )
    return event_id


def _invoice_data(order: dict, items: List[dict]) -> dict:
    """Same output shape as invoice_service.generate_invoice_data(), built
    for a *multi*-line-item order (vendor_orders can have >1 item; the
    original function is hardcoded to exactly one — see VENDOR_ONBOARDING.md
    follow-ups). generate_invoice_pdf() itself is reused completely
    unchanged — only this data-shaping step is new, because the input
    shape genuinely differs."""
    subtotal = float(order["subtotal"])
    fee_rate = payments.PLATFORM_FEE_RATE
    fee = float(order.get("platform_fee") or 0)
    total = float(order["total_amount"])
    return {
        "invoice_number": "INV-" + order["order_code"].replace("VO-", ""),
        "order_code": order["order_code"],
        "issued_at": str(order.get("created_at", datetime.now(timezone.utc).isoformat())),
        "status": "Generated",
        "company": {
            "name": "NEXUS ERP PowerGrid Optimizer",
            "tagline": "Smart Grid & Automated Procurement Network",
            "address": "Islamabad Electric Supply Company (IESCO) HQ, Islamabad, Pakistan",
            "email": "procurement@nexus.pk",
        },
        "vendor": {"name": order["vendor_name"], "email": order["vendor_email"]},
        "line_items": [
            {
                "description": i["name"], "item_id": i["sku"] or "—",
                "quantity": float(i["quantity"]), "unit": i["unit"],
                "unit_price": float(i["unit_price"]), "line_total": float(i["line_total"]),
            }
            for i in items
        ],
        "subtotal": subtotal,
        "blockchain_fee_rate": fee_rate,
        "blockchain_fee": fee,
        "tax_rate": 0.0,
        "tax": 0.0,
        "total": total,
        "currency": "PKR",
        "contract_hash": order.get("chain_order_id"),
        "contract_status": order.get("contract_status"),
        "expected_delivery": str(order.get("requested_delivery_date")) if order.get("requested_delivery_date") else None,
        "trigger_type": "Vendor Catalogue Order",
        "pricing_pending": False,
    }


# ════════════════════════════════════════════════════════════════════════════
# PLACE ORDER (Admin + Procurement Manager)
# ════════════════════════════════════════════════════════════════════════════

class PlaceOrderItemRequest(BaseModel):
    vendor_item_id: str
    quantity: float


class PlaceOrderRequest(BaseModel):
    vendor_id: str
    items: List[PlaceOrderItemRequest]
    destination_name: str
    destination_city: Optional[str] = None
    destination_address: Optional[str] = None
    requested_delivery_date: Optional[str] = None


@router.post("/api/vendor-orders", dependencies=[_staff])
def place_vendor_order(req: PlaceOrderRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    vendor = db.execute(
        text("SELECT * FROM vendors WHERE id = :id AND status = 'active'"), {"id": req.vendor_id}
    ).mappings().first()
    if not vendor:
        raise HTTPException(404, "Vendor not found or not approved")
    if not req.items:
        raise HTTPException(400, "At least one item is required")

    line_items = []
    subtotal = 0.0
    for it in req.items:
        vi = db.execute(
            text("SELECT * FROM vendor_items WHERE id = :id AND vendor_id = :vid AND is_active = TRUE"),
            {"id": it.vendor_item_id, "vid": req.vendor_id},
        ).mappings().first()
        if not vi:
            raise HTTPException(400, f"Item {it.vendor_item_id} not found in this vendor's catalogue")
        if it.quantity <= 0:
            raise HTTPException(400, f"Quantity for {vi['name']} must be positive")
        line_total = round(float(it.quantity) * float(vi["unit_price"]), 2)
        subtotal += line_total
        line_items.append({
            "vendor_item_id": vi["id"], "name": vi["name"], "sku": vi["sku"],
            "unit": vi["unit"], "quantity": float(it.quantity), "unit_price": float(vi["unit_price"]),
            "line_total": line_total,
        })

    amounts = payments.compute_order_amounts(subtotal)
    payments.check_order_cap(amounts["total_amount"])
    order_id = str(uuid.uuid4())
    order_code = "VO-" + uuid.uuid4().hex[:6].upper()
    expires_at = datetime.now(timezone.utc) + timedelta(hours=VENDOR_ORDER_RESPONSE_HOURS)

    db.execute(
        text("""
            INSERT INTO vendor_orders (
              id, order_code, vendor_id, orderer_user_id,
              destination_name, destination_city, destination_address,
              requested_delivery_date, subtotal, platform_fee, total_amount, vendor_payout_amount, currency,
              status, expires_at
            ) VALUES (
              :id, :code, :vendor_id, :orderer_id,
              :dest_name, :dest_city, :dest_address,
              :delivery_date, :subtotal, :fee, :total, :payout, 'PKR',
              'PENDING_VENDOR', :expires_at
            )
        """),
        {
            "id": order_id, "code": order_code, "vendor_id": req.vendor_id, "orderer_id": user["id"],
            "dest_name": req.destination_name, "dest_city": req.destination_city, "dest_address": req.destination_address,
            "delivery_date": req.requested_delivery_date, "subtotal": amounts["subtotal"], "fee": amounts["platform_fee"],
            "total": amounts["total_amount"], "payout": amounts["vendor_payout_amount"],
            "expires_at": expires_at,
        },
    )
    for li in line_items:
        db.execute(
            text("""
                INSERT INTO vendor_order_items (id, order_id, vendor_item_id, name, sku, unit, quantity, unit_price, line_total)
                VALUES (:id, :oid, :vid, :name, :sku, :unit, :qty, :price, :total)
            """),
            {"id": str(uuid.uuid4()), "oid": order_id, "vid": li["vendor_item_id"], "name": li["name"],
             "sku": li["sku"], "unit": li["unit"], "qty": li["quantity"], "price": li["unit_price"], "total": li["line_total"]},
        )

    # Respond token (single-use, per spec's 72h default)
    token = secrets.token_urlsafe(32)
    db.execute(
        text("""
            INSERT INTO vendor_order_tokens (id, order_id, purpose, token_hash, expires_at)
            VALUES (:id, :oid, 'respond', :hash, :expires_at)
        """),
        {"id": str(uuid.uuid4()), "oid": order_id, "hash": _hash_token(token), "expires_at": expires_at},
    )

    # Give the orderer a chain wallet now, so it's ready by the time they
    # need to confirm/approve — avoids a first-use delay later.
    chain.get_or_create_user_wallet(db, user["id"])

    db.commit()

    order = _get_order(db, order_id)
    accept_url = f"{FRONTEND_URL}/vendor/respond?order_id={order_id}&token={token}&decision=accept"
    reject_url = f"{FRONTEND_URL}/vendor/respond?order_id={order_id}&token={token}&decision=reject"
    n8n_result = trigger_vendor_order_email(order, line_items, accept_url, reject_url, str(expires_at))

    notify(
        db, "order.placed", {"orderer_user_id": user["id"]},
        title=f"Order Placed — {order_code}",
        body=f"Order {order_code} ({vendor['name']}, PKR {amounts['total_amount']:,.2f}) sent for vendor confirmation. "
             f"Expires {expires_at.strftime('%Y-%m-%d %H:%M')} UTC.",
        entity_type="vendor_order", entity_id=order_id, action_path=f"/tracking/{order_id}",
        metadata={"order_id": order_id, "order_code": order_code},
    )
    db.commit()

    return {
        "order_id": order_id, "order_code": order_code, "status": "PENDING_VENDOR", **amounts,
        "vendor_email_status": n8n_result["status"],
        "message": f"Order {order_code} placed. Vendor notified, awaiting their response.",
    }


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC — vendor accept/reject (no login)
# ════════════════════════════════════════════════════════════════════════════

def _validate_respond_token(db: Session, order_id: str, token: str) -> dict:
    row = db.execute(
        text("""
            SELECT * FROM vendor_order_tokens
            WHERE order_id = :oid AND purpose = 'respond' AND token_hash = :hash
        """),
        {"oid": order_id, "hash": _hash_token(token)},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Invalid response link")
    if row["revoked_at"] is not None:
        raise HTTPException(410, "This link has been revoked")
    if row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(410, "This link has expired")
    return dict(row)


@router.get("/api/public/vendor-orders/{order_id}")
def public_get_vendor_order(order_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    _validate_respond_token(db, order_id, token)
    order = _get_order(db, order_id)
    items = _get_items(db, order_id)
    return {
        "order_code": order["order_code"], "vendor_name": order["vendor_name"],
        "destination_name": order["destination_name"], "destination_city": order["destination_city"],
        "requested_delivery_date": order["requested_delivery_date"], "status": order["status"],
        "subtotal": float(order["subtotal"]), "total_amount": float(order["total_amount"]),
        "platform_fee": float(order["platform_fee"] or 0),
        "vendor_payout_amount": float(order["vendor_payout_amount"] or order["subtotal"]),
        "currency": order["currency"], "expires_at": order["expires_at"],
        "already_responded": order["status"] != "PENDING_VENDOR",
        "items": [{"name": i["name"], "unit": i["unit"], "quantity": float(i["quantity"]),
                    "unit_price": float(i["unit_price"]), "line_total": float(i["line_total"])} for i in items],
    }


class VendorRespondRequest(BaseModel):
    order_id: str
    token: str
    decision: str  # accept | reject
    reason: Optional[str] = None


@router.post("/api/public/vendor-orders/respond")
def public_respond_vendor_order(req: VendorRespondRequest, db: Session = Depends(get_db)):
    if req.decision not in ("accept", "reject"):
        raise HTTPException(400, "decision must be 'accept' or 'reject'")

    token_row = _validate_respond_token(db, req.order_id, req.token)
    order = _get_order(db, req.order_id)

    if order["status"] != "PENDING_VENDOR":
        # Idempotent: a repeated click / retry never double-processes.
        return {"message": f"Order {order['order_code']} already recorded a response: {order['status']}"}

    # Atomically claim the token — guards a race between two near-simultaneous
    # clicks (e.g. a double-click, or an email client prefetch racing the
    # real click) from both succeeding.
    claimed = db.execute(
        text("UPDATE vendor_order_tokens SET used_at = NOW() WHERE id = :id AND used_at IS NULL"),
        {"id": token_row["id"]},
    )
    db.commit()
    if claimed.rowcount == 0:
        return {"message": f"Order {order['order_code']} already recorded a response"}

    items = _get_items(db, req.order_id)

    if req.decision == "reject":
        db.execute(
            text("""
                UPDATE vendor_orders SET status = 'REJECTED', vendor_rejection_reason = :reason,
                  payout_status = 'Not Applicable', vendor_responded_at = NOW(), updated_at = NOW()
                WHERE id = :id
            """),
            {"reason": req.reason, "id": req.order_id},
        )
        notify(
            db, "order.vendor_rejected", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Vendor Rejected — {order['order_code']}",
            body=f"{order['vendor_name']} rejected order {order['order_code']}"
                 + (f": {req.reason}" if req.reason else "") + ". Pick another vendor.",
            entity_type="vendor_order", entity_id=req.order_id, action_path="/vendor-catalogue",
            metadata={"order_id": req.order_id},
        )
        db.commit()
        return {"message": f"Order {order['order_code']} rejected. Orderer notified."}

    # --- accept ---
    destination = _destination_string(order)
    terms_summary = _order_terms_summary(items)
    receiver_address = chain.get_or_create_user_wallet(db, order["orderer_user_id"])
    amount_paisa = payments.to_paisa(order["total_amount"])  # PKR -> paisa, informational on-chain

    # Hold the funds first, so the escrow contract is created already
    # bound to this payment (its paymentRef is the hash of payment_ref).
    payment_result = payments.authorize_for_order(db, req.order_id)
    db.commit()

    chain_result = chain.create_contract(
        db, req.order_id, order["order_code"], receiver_address,
        order["vendor_id"], destination, terms_summary, amount_paisa,
        payment_ref=payment_result.get("payment_ref"),
    )

    db.execute(
        text("""
            UPDATE vendor_orders SET
              status = 'ACCEPTED', vendor_responded_at = NOW(),
              chain_order_id = :chain_order_id, chain_network = :network,
              destination_hash = :dest_hash, order_hash = :order_hash,
              contract_status = 'Preparing',
              next_status_checkin_due = NOW() + (:checkin_hours * INTERVAL '1 hour'),
              updated_at = NOW()
            WHERE id = :id
        """),
        {
            "chain_order_id": chain_result.get("chain_order_id"), "network": chain.CHAIN_NETWORK,
            "dest_hash": chain_result.get("destination_hash"), "order_hash": chain_result.get("order_hash"),
            "checkin_hours": VENDOR_STATUS_CHECKIN_INTERVAL_HOURS,
            "id": req.order_id,
        },
    )
    db.execute(
        text("INSERT INTO shipments (id, order_id, status) VALUES (:id, :oid, 'Preparing')"),
        {"id": str(uuid.uuid4()), "oid": req.order_id},
    )
    _insert_event(
        db, req.order_id, "Preparing", "system",
        note="Vendor accepted — smart contract created, "
             + ("payment authorized and held in escrow." if payment_result["status"] == "Authorized"
                else "payment NOT yet authorized (no default payment method)."),
        chain_result=chain_result,
    )
    db.commit()

    # Ship-update token (multi-use, long-lived) + confirmation email to vendor
    ship_token = secrets.token_urlsafe(32)
    db.execute(
        text("""
            INSERT INTO vendor_order_tokens (id, order_id, purpose, token_hash, expires_at)
            VALUES (:id, :oid, 'ship_update', :hash, :expires_at)
        """),
        {"id": str(uuid.uuid4()), "oid": req.order_id, "hash": _hash_token(ship_token),
         "expires_at": datetime.now(timezone.utc) + timedelta(days=30)},
    )
    db.commit()
    ship_url = f"{FRONTEND_URL}/vendor/shipment?order_id={req.order_id}&token={ship_token}"
    try:
        trigger_vendor_order_shipment_link_email(order, ship_url)
    except Exception as e:
        print(f"[WARN] shipment-link email failed: {e}")

    notify(
        db, "order.vendor_accepted", {"orderer_user_id": order["orderer_user_id"]},
        title=f"Vendor Accepted — {order['order_code']}",
        body=f"{order['vendor_name']} accepted order {order['order_code']}. Smart contract created; "
             + (f"PKR {float(order['total_amount']):,.2f} authorized and held until you approve receipt."
                if payment_result["status"] == "Authorized"
                else "payment is waiting on an admin to add a payment method."),
        entity_type="vendor_order", entity_id=req.order_id, action_path=f"/tracking/{req.order_id}",
        metadata={"order_id": req.order_id},
    )
    db.commit()

    return {"message": f"Order {order['order_code']} accepted. Smart contract created."}


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC — vendor shipment updates (no login, multi-use token)
# ════════════════════════════════════════════════════════════════════════════

class VendorShipmentUpdateRequest(BaseModel):
    order_id: str
    token: str
    action: str  # dispatch | checkpoint
    carrier: Optional[str] = None
    tracking_no: Optional[str] = None
    eta: Optional[str] = None
    dispatch_date: Optional[str] = None
    status: Optional[str] = None  # for checkpoint: InTransit | OutForDelivery
    location: Optional[str] = None
    note: Optional[str] = None


def _validate_ship_token(db: Session, order_id: str, token: str) -> dict:
    row = db.execute(
        text("""
            SELECT * FROM vendor_order_tokens
            WHERE order_id = :oid AND purpose = 'ship_update' AND token_hash = :hash
        """),
        {"oid": order_id, "hash": _hash_token(token)},
    ).mappings().first()
    if not row:
        raise HTTPException(404, "Invalid shipment-update link")
    if row["revoked_at"] is not None:
        raise HTTPException(410, "This link has been revoked")
    if row["expires_at"] < datetime.now(timezone.utc):
        raise HTTPException(410, "This link has expired")
    return dict(row)


@router.get("/api/public/vendor-orders/{order_id}/shipment")
def public_get_shipment(order_id: str, token: str = Query(...), db: Session = Depends(get_db)):
    _validate_ship_token(db, order_id, token)
    order = _get_order(db, order_id)
    shipment = _get_shipment(db, order_id)
    return {
        "order_code": order["order_code"], "vendor_name": order["vendor_name"],
        "contract_status": order["contract_status"],
        "shipment": shipment,
    }


def _do_shipment_update(db: Session, order_id: str, req: VendorShipmentUpdateRequest, actor_type: str, actor_user_id=None, actor_label=None):
    order = _get_order(db, order_id)
    if order["contract_status"] not in SHIPPABLE_CONTRACT_STATUSES:
        raise HTTPException(400, f"Order is not in a shippable state (currently {order['contract_status']})")

    if req.action == "dispatch":
        if order["contract_status"] != "Preparing":
            raise HTTPException(400, "Order has already been dispatched")
        new_status = "Dispatched"
        db.execute(
            text("""
                UPDATE shipments SET carrier=:carrier, tracking_no=:tracking, dispatch_date=:dd, eta=:eta,
                  status=:status, updated_at=NOW()
                WHERE order_id=:oid
            """),
            {"carrier": req.carrier, "tracking": req.tracking_no, "dd": req.dispatch_date or str(datetime.now(timezone.utc).date()),
             "eta": req.eta, "status": new_status, "oid": order_id},
        )
        note = req.note or f"Dispatched via {req.carrier or 'carrier'} ({req.tracking_no or 'no tracking #'})"
    elif req.action == "checkpoint":
        if req.status not in ("InTransit", "OutForDelivery"):
            raise HTTPException(400, "status must be 'InTransit' or 'OutForDelivery' for a checkpoint")
        new_status = req.status
        db.execute(text("UPDATE shipments SET status=:status, updated_at=NOW() WHERE order_id=:oid"),
                   {"status": new_status, "oid": order_id})
        note = req.note
    else:
        raise HTTPException(400, "action must be 'dispatch' or 'checkpoint'")

    chain_result = chain.record_checkpoint(db, order_id, order["order_code"], new_status, req.location, note, actor_type)
    # A real status update (from the vendor or staff) is itself the thing
    # the check-in nudges are chasing — push the next one out a full
    # interval rather than nagging again a few minutes later.
    db.execute(
        text("""
            UPDATE vendor_orders SET contract_status=:s,
              next_status_checkin_due = NOW() + (:checkin_hours * INTERVAL '1 hour'),
              updated_at=NOW()
            WHERE id=:id
        """),
        {"s": new_status, "checkin_hours": VENDOR_STATUS_CHECKIN_INTERVAL_HOURS, "id": order_id},
    )
    _insert_event(db, order_id, new_status, actor_type, location=req.location, note=note,
                  actor_user_id=actor_user_id, actor_label=actor_label, chain_result=chain_result)
    db.commit()

    label = {"Dispatched": "dispatched", "InTransit": "in transit", "OutForDelivery": "out for delivery"}[new_status]
    event_type = {"Dispatched": "shipment.dispatched", "InTransit": "shipment.in_transit", "OutForDelivery": "shipment.out_for_delivery"}[new_status]
    notify(
        db, event_type, {"orderer_user_id": order["orderer_user_id"]},
        title=f"Order {label.title()} — {order['order_code']}",
        body=f"{order['order_code']} is now {label}." + (f" Location: {req.location}." if req.location else ""),
        entity_type="vendor_order", entity_id=order_id, action_path=f"/tracking/{order_id}",
        metadata={"order_id": order_id},
    )
    db.commit()
    return {"message": f"Shipment update recorded ({new_status}).", "chain": chain_result}


@router.post("/api/public/vendor-orders/shipment-update")
def public_shipment_update(req: VendorShipmentUpdateRequest, db: Session = Depends(get_db)):
    _validate_ship_token(db, req.order_id, req.token)
    _check_ship_update_rate_limit(req.order_id)
    order = _get_order(db, req.order_id)
    return _do_shipment_update(db, req.order_id, req, "vendor_link", actor_label=order["vendor_name"])


# ════════════════════════════════════════════════════════════════════════════
# STAFF — shipment checkpoints, chain status
# ════════════════════════════════════════════════════════════════════════════

class StaffShipmentUpdateRequest(BaseModel):
    action: str
    carrier: Optional[str] = None
    tracking_no: Optional[str] = None
    eta: Optional[str] = None
    dispatch_date: Optional[str] = None
    status: Optional[str] = None
    location: Optional[str] = None
    note: Optional[str] = None


@router.post("/api/shipments/{order_id}/checkpoints", dependencies=[_staff])
def staff_shipment_checkpoint(order_id: str, req: StaffShipmentUpdateRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    full_req = VendorShipmentUpdateRequest(order_id=order_id, token="", **req.dict())
    return _do_shipment_update(db, order_id, full_req, "staff", actor_user_id=user["id"], actor_label=user["name"])


@router.get("/api/chain/status", dependencies=[_staff])
def get_chain_status():
    return chain.chain_status()


# ════════════════════════════════════════════════════════════════════════════
# ORDERER-ONLY — confirm arrival, approve receipt, dispute
# ════════════════════════════════════════════════════════════════════════════

def _payout_message(order: dict) -> str:
    if order["payment_status"] != "Captured":
        return (f"Receipt approved and contract executed, but payment capture failed "
                f"({order['payment_status']}) — an admin can retry it from Payments.")
    payout = float(order["vendor_payout_amount"] or order["subtotal"])
    if order["payout_status"] == "Paid":
        return f"Receipt approved. Contract executed, PKR {payout:,.2f} paid to {order['vendor_name']}."
    if order["payout_status"] == "Awaiting Transfer":
        return (f"Receipt approved. Contract executed — an admin will now transfer PKR {payout:,.2f} to "
                f"{order['vendor_name']}.")
    return (f"Receipt approved. Contract executed and payment captured — PKR {payout:,.2f} will be paid to "
            f"{order['vendor_name']} within {payments.PAYOUT_SETTLEMENT_HOURS}h.")


def _is_order_owner(order: dict, user: dict) -> bool:
    # order["orderer_user_id"] comes back from pg8000 as a uuid.UUID object;
    # user["id"] is always a str (JWT claims are string-encoded) — compare
    # as strings or this silently rejects the real orderer every time.
    return str(order["orderer_user_id"]) == str(user["id"])


def _require_orderer(order: dict, user: dict):
    if not _is_order_owner(order, user):
        raise HTTPException(403, "Only the orderer who placed this order can perform this action")


@router.post("/api/shipments/{order_id}/confirm-arrival")
def confirm_arrival_endpoint(order_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    _require_orderer(order, user)
    if order["contract_status"] not in ("OutForDelivery", "InTransit"):
        raise HTTPException(400, f"Order is not out for delivery (currently {order['contract_status']})")

    destination = _destination_string(order)
    chain_result = chain.confirm_arrival(db, order_id, order["order_code"], destination, user["id"])
    db.execute(
        text("UPDATE vendor_orders SET contract_status='Arrived', next_status_checkin_due=NULL, updated_at=NOW() WHERE id=:id"),
        {"id": order_id},
    )
    _insert_event(db, order_id, "Arrived", "receiver", actor_user_id=user["id"], actor_label=user["name"], chain_result=chain_result)

    # Confirming arrival is itself the action that closes out the
    # "out for delivery / confirm arrival" notification(s) raised earlier.
    auto_resolve(db, "vendor_order", order_id, user_id=user["id"])
    notify(
        db, "shipment.arrived", {"orderer_user_id": user["id"]},
        title=f"Arrived — {order['order_code']}",
        body="Inspect the delivery, then approve receipt or raise a dispute.",
        entity_type="vendor_order", entity_id=order_id, action_path=f"/tracking/{order_id}",
        metadata={"order_id": order_id},
    )
    db.commit()
    return {"message": "Arrival confirmed.", "chain": chain_result}


@router.post("/api/shipments/{order_id}/approve-receipt")
def approve_receipt_endpoint(order_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    _require_orderer(order, user)
    if order["contract_status"] != "Arrived":
        raise HTTPException(400, f"Order has not been confirmed as arrived (currently {order['contract_status']})")

    # Funds must be held before the contract executes — executing an
    # escrow contract nobody can pay for would be irreversible on-chain.
    if order["payment_status"] != "Authorized":
        auth = payments.authorize_for_order(db, order_id, actor_user_id=user["id"])
        db.commit()
        if auth["status"] != "Authorized":
            raise HTTPException(409, "Payment for this order is not authorized — an admin needs to add a default "
                                     "payment method under Payments before receipt can be approved.")

    chain_result = chain.approve_receipt(db, order_id, order["order_code"], user["id"])
    db.execute(text("UPDATE vendor_orders SET contract_status='Executed', updated_at=NOW() WHERE id=:id"), {"id": order_id})
    payment_result = payments.capture_for_order(db, order_id, actor_user_id=user["id"])
    _insert_event(db, order_id, "Executed", "receiver",
                  note="Receipt approved — contract executed, "
                       + ("payment captured, vendor payout scheduled." if payment_result["status"] == "Captured"
                          else f"payment capture FAILED ({payment_result.get('error') or payment_result['status']})."),
                  actor_user_id=user["id"], actor_label=user["name"], chain_result=chain_result)
    db.commit()

    if payment_result["status"] == "Captured" and payments.PAYOUT_SETTLEMENT_HOURS == 0:
        payments.release_payout(db, order_id)
        db.commit()

    order = _get_order(db, order_id)
    auto_resolve(db, "vendor_order", order_id, user_id=user["id"])
    notify(
        db, "contract.executed", {"orderer_user_id": order["orderer_user_id"]},
        title=f"Executed — {order['order_code']}",
        body=f"{order['order_code']} receipt approved — contract executed, PKR {float(order['total_amount']):,.2f} "
             f"captured. Invoice available.",
        entity_type="vendor_order", entity_id=order_id, action_path=f"/tracking/{order_id}",
        metadata={"order_id": order_id},
    )
    db.commit()
    return {"message": _payout_message(order), "chain": chain_result}


class DisputeRequest(BaseModel):
    reason: str


@router.post("/api/shipments/{order_id}/dispute")
def dispute_endpoint(order_id: str, req: DisputeRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    _require_orderer(order, user)
    if order["contract_status"] != "Arrived":
        raise HTTPException(400, "Can only dispute after arrival has been confirmed")
    if not req.reason or not req.reason.strip():
        raise HTTPException(400, "A reason is required")

    chain_result = chain.dispute(db, order_id, order["order_code"], req.reason, user["id"])
    db.execute(
        text("""
            UPDATE vendor_orders SET contract_status='Disputed', dispute_reason=:reason, dispute_opened_at=NOW(), updated_at=NOW()
            WHERE id=:id
        """),
        {"reason": req.reason, "id": order_id},
    )
    _insert_event(db, order_id, "Disputed", "receiver", note=req.reason, actor_user_id=user["id"],
                  actor_label=user["name"], chain_result=chain_result)
    db.commit()

    auto_resolve(db, "vendor_order", order_id, user_id=user["id"])
    notify(
        db, "dispute.opened", {"actor_user_id": user["id"]},
        title=f"Disputed — {order['order_code']}",
        body=f"{user['name']} disputed order {order['order_code']}: {req.reason}",
        entity_type="vendor_order", entity_id=order_id, action_path=f"/tracking/{order_id}",
        metadata={"order_id": order_id},
    )
    db.commit()
    return {"message": "Dispute opened. Contract frozen pending admin resolution.", "chain": chain_result}


class ResolveDisputeRequest(BaseModel):
    resolution: str  # Arrived | Cancelled | Executed
    notes: Optional[str] = None


@router.post("/api/shipments/{order_id}/resolve-dispute", dependencies=[Depends(require_role(ROLE_ADMIN))])
def resolve_dispute_endpoint(order_id: str, req: ResolveDisputeRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    if order["contract_status"] != "Disputed":
        raise HTTPException(400, "Order is not currently disputed")
    if req.resolution not in ("Arrived", "Cancelled", "Executed"):
        raise HTTPException(400, "resolution must be 'Arrived', 'Cancelled' or 'Executed'")

    if req.resolution == "Executed" and order["payment_status"] != "Authorized":
        auth = payments.authorize_for_order(db, order_id, actor_user_id=user["id"])
        db.commit()
        if auth["status"] != "Authorized":
            raise HTTPException(409, "Payment is not authorized — add a default payment method under Payments first.")

    chain_result = chain.resolve_dispute(db, order_id, order["order_code"], req.resolution)

    db.execute(
        text("""
            UPDATE vendor_orders SET contract_status=:status,
              dispute_resolved_at=NOW(), dispute_resolution=:resolution, dispute_resolution_notes=:notes,
              updated_at=NOW()
            WHERE id=:id
        """),
        {"status": req.resolution, "resolution": req.resolution, "notes": req.notes, "id": order_id},
    )
    if req.resolution == "Cancelled":
        payments.cancel_for_order(db, order_id, actor_user_id=user["id"], note="Dispute resolved: cancelled")
    elif req.resolution == "Executed":
        payments.capture_for_order(db, order_id, actor_user_id=user["id"])
    _insert_event(db, order_id, req.resolution, "staff", note=req.notes or f"Dispute resolved: {req.resolution}",
                  actor_user_id=user["id"], actor_label=user["name"], chain_result=chain_result)
    db.commit()
    if req.resolution == "Executed" and payments.PAYOUT_SETTLEMENT_HOURS == 0:
        payments.release_payout(db, order_id, actor_user_id=user["id"])
        db.commit()

    notify(
        db, "dispute.resolved", {"orderer_user_id": order["orderer_user_id"]},
        title=f"Dispute Resolved — {order['order_code']}",
        body=f"Resolved to {req.resolution}.",
        entity_type="vendor_order", entity_id=order_id, action_path=f"/tracking/{order_id}",
        metadata={"order_id": order_id},
    )
    db.commit()
    return {"message": f"Dispute resolved to {req.resolution}.", "chain": chain_result}


# ════════════════════════════════════════════════════════════════════════════
# ORDER TRACKING — list, summary, detail
# ════════════════════════════════════════════════════════════════════════════

ACTION_NEEDED_STATUSES = {
    "OutForDelivery": "confirm_arrival",
    "InTransit": "confirm_arrival",
    "Arrived": "approve_or_dispute",
}


def _action_needed(order: dict) -> Optional[str]:
    if order["status"] == "ACCEPTED" and order["contract_status"] in ACTION_NEEDED_STATUSES:
        return ACTION_NEEDED_STATUSES[order["contract_status"]]
    return None


def _is_delayed(order: dict, shipment: Optional[dict]) -> bool:
    if not shipment or not shipment.get("eta"):
        return False
    if order["contract_status"] in ("Arrived", "Approved", "Executed", "Cancelled", "Disputed") or order["status"] != "ACCEPTED":
        return False
    return shipment["eta"] < datetime.now(timezone.utc).date()


@router.get("/api/tracking", dependencies=[_staff])
def list_tracking(
    scope: str = Query("mine"),
    status: Optional[str] = Query(None),
    vendor_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    filters = "WHERE 1=1"
    params: dict = {"limit": limit, "offset": offset}
    if scope != "all":
        filters += " AND o.orderer_user_id = :uid"
        params["uid"] = user["id"]
    if status:
        filters += " AND o.status = :status"
        params["status"] = status
    if vendor_id:
        filters += " AND o.vendor_id = :vendor_id"
        params["vendor_id"] = vendor_id
    if search:
        filters += " AND (o.order_code ILIKE :search OR v.name ILIKE :search)"
        params["search"] = f"%{search}%"

    rows = db.execute(
        text(f"""
            SELECT o.*, v.name AS vendor_name, s.status AS shipment_status, s.carrier, s.tracking_no, s.eta
            FROM vendor_orders o
            JOIN vendors v ON v.id = o.vendor_id
            LEFT JOIN shipments s ON s.order_id = o.id
            {filters}
            ORDER BY
              CASE WHEN o.status = 'ACCEPTED' AND o.contract_status IN ('Arrived','OutForDelivery','InTransit') THEN 0 ELSE 1 END,
              s.eta ASC NULLS LAST, o.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()

    out = []
    for r in rows:
        row = dict(r)
        shipment = {"status": row.get("shipment_status"), "carrier": row.get("carrier"), "tracking_no": row.get("tracking_no"), "eta": row.get("eta")}
        row["action_needed"] = _action_needed(row)
        row["delayed"] = _is_delayed(row, shipment if row.get("shipment_status") else None)
        out.append(row)

    return {"orders": out}


@router.get("/api/tracking/summary", dependencies=[_staff])
def tracking_summary(scope: str = Query("mine"), user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    filters = "WHERE 1=1"
    params: dict = {}
    if scope != "all":
        filters += " AND o.orderer_user_id = :uid"
        params["uid"] = user["id"]

    rows = db.execute(
        text(f"""
            SELECT o.id, o.status, o.contract_status, s.eta
            FROM vendor_orders o LEFT JOIN shipments s ON s.order_id = o.id
            {filters}
        """),
        params,
    ).mappings().all()

    counts = {
        "awaiting_vendor": 0, "in_progress": 0, "action_needed": 0,
        "delayed": 0, "completed": 0, "rejected_expired_disputed": 0,
    }
    for r in rows:
        row = dict(r)
        if row["status"] == "PENDING_VENDOR":
            counts["awaiting_vendor"] += 1
        elif row["status"] in ("REJECTED", "EXPIRED", "CANCELLED") or row["contract_status"] in ("Disputed", "Cancelled"):
            counts["rejected_expired_disputed"] += 1
        elif row["contract_status"] == "Executed":
            counts["completed"] += 1
        elif row["status"] == "ACCEPTED":
            counts["in_progress"] += 1
            if _action_needed(row):
                counts["action_needed"] += 1
            if _is_delayed(row, {"eta": row["eta"]} if row["eta"] else None):
                counts["delayed"] += 1

    return counts


@router.get("/api/tracking/{order_id}", dependencies=[_staff])
def tracking_detail(order_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    if not _is_order_owner(order, user) and user["role"] not in (ROLE_ADMIN, ROLE_PROCUREMENT_MANAGER):
        raise HTTPException(403, "Not authorized to view this order")

    items = _get_items(db, order_id)
    shipment = _get_shipment(db, order_id)
    events = _get_events(db, order_id)
    chain_live_state = chain.get_state(order["order_code"])
    chain_txs = db.execute(
        text("""
            SELECT id, action, status, attempts, last_error, tx_hash, block_number, created_at, updated_at
            FROM chain_tx_queue WHERE order_id = :id ORDER BY created_at ASC
        """),
        {"id": order_id},
    ).mappings().all()
    payment_txs = db.execute(
        text("SELECT id, kind, amount, currency, status, provider_ref, note, created_at FROM payment_transactions WHERE order_id = :id ORDER BY created_at ASC"),
        {"id": order_id},
    ).mappings().all()

    return {
        "order": {**order, "action_needed": _action_needed(order), "delayed": _is_delayed(order, shipment),
                   "is_orderer": _is_order_owner(order, user)},
        "items": items,
        "shipment": shipment,
        "events": events,
        "chain_live_state": chain_live_state,
        "chain_txs": [dict(r) for r in chain_txs],
        "payment_transactions": [{**dict(r), "amount": float(r["amount"])} for r in payment_txs],
        "payment_config": {"platform_fee_rate": payments.PLATFORM_FEE_RATE,
                           "payout_settlement_hours": payments.PAYOUT_SETTLEMENT_HOURS},
    }


@router.get("/api/tracking/{order_id}/invoice/pdf", dependencies=[_staff])
def tracking_invoice_pdf(order_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    if not _is_order_owner(order, user) and user["role"] not in (ROLE_ADMIN, ROLE_PROCUREMENT_MANAGER):
        raise HTTPException(403, "Not authorized to view this order")
    items = _get_items(db, order_id)
    invoice = _invoice_data(order, items)
    pdf_bytes = generate_invoice_pdf(invoice)
    return Response(content=pdf_bytes, media_type="application/pdf",
                     headers={"Content-Disposition": f"attachment; filename=invoice-{order['order_code']}.pdf"})


class ResendRequest(BaseModel):
    pass


@router.post("/api/vendor-orders/{order_id}/resend-vendor-request", dependencies=[_staff])
def resend_vendor_request(order_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    _require_orderer(order, user)
    if order["status"] != "PENDING_VENDOR":
        raise HTTPException(400, f"Order is not awaiting vendor response (status: {order['status']})")

    db.execute(text("UPDATE vendor_order_tokens SET revoked_at = NOW() WHERE order_id=:id AND purpose='respond' AND used_at IS NULL"), {"id": order_id})
    token = secrets.token_urlsafe(32)
    expires_at = datetime.now(timezone.utc) + timedelta(hours=VENDOR_ORDER_RESPONSE_HOURS)
    db.execute(
        text("INSERT INTO vendor_order_tokens (id, order_id, purpose, token_hash, expires_at) VALUES (:id, :oid, 'respond', :hash, :exp)"),
        {"id": str(uuid.uuid4()), "oid": order_id, "hash": _hash_token(token), "exp": expires_at},
    )
    db.execute(text("UPDATE vendor_orders SET expires_at=:exp, vendor_reminder_sent_at=NULL, updated_at=NOW() WHERE id=:id"),
               {"exp": expires_at, "id": order_id})
    db.commit()

    items = _get_items(db, order_id)
    accept_url = f"{FRONTEND_URL}/vendor/respond?order_id={order_id}&token={token}&decision=accept"
    reject_url = f"{FRONTEND_URL}/vendor/respond?order_id={order_id}&token={token}&decision=reject"
    result = trigger_vendor_order_email(order, items, accept_url, reject_url, str(expires_at))
    notify(
        db, "order.resent", {"orderer_user_id": user["id"]},
        title=f"Request Resent — {order['order_code']}",
        body=f"Resent the Accept/Reject request to {order['vendor_name']} for order {order['order_code']}.",
        entity_type="vendor_order", entity_id=order_id, action_path=f"/tracking/{order_id}",
        metadata={"order_id": order_id},
    )
    db.commit()
    return {"message": f"Resent to {order['vendor_name']}.", "vendor_email_status": result["status"]}


@router.post("/api/vendor-orders/{order_id}/cancel", dependencies=[_staff])
def cancel_vendor_order(order_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _get_order(db, order_id)
    if order["status"] != "PENDING_VENDOR":
        raise HTTPException(400, "Can only cancel while awaiting vendor response")

    db.execute(text("UPDATE vendor_order_tokens SET revoked_at = NOW() WHERE order_id=:id AND used_at IS NULL"), {"id": order_id})
    db.execute(
        text("""
            UPDATE vendor_orders SET status='CANCELLED', payout_status='Not Applicable',
              cancelled_at=NOW(), cancelled_by=:uid, updated_at=NOW()
            WHERE id=:id
        """),
        {"uid": user["id"], "id": order_id},
    )
    db.commit()
    return {"message": f"Order {order['order_code']} cancelled."}


class CancelContractRequest(BaseModel):
    reason: str


@router.post("/api/vendor-orders/{order_id}/cancel-contract", dependencies=[Depends(require_role(ROLE_ADMIN))])
def cancel_vendor_contract(order_id: str, req: CancelContractRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Admin-only: cancel an accepted order whose goods have not arrived yet
    (ShipmentEscrow.cancel() is blocked on-chain once Arrived — after that
    only the dispute path can cancel). Releases the payment hold."""
    order = _get_order(db, order_id)
    if order["status"] != "ACCEPTED" or order["contract_status"] not in SHIPPABLE_CONTRACT_STATUSES:
        raise HTTPException(400, f"Only an in-flight contract can be cancelled (currently {order['contract_status']})")
    if not req.reason or not req.reason.strip():
        raise HTTPException(400, "A reason is required")

    chain_result = chain.cancel(db, order_id, order["order_code"])
    db.execute(text("UPDATE vendor_order_tokens SET revoked_at = NOW() WHERE order_id=:id AND revoked_at IS NULL"), {"id": order_id})
    db.execute(
        text("""
            UPDATE vendor_orders SET contract_status='Cancelled', next_status_checkin_due=NULL,
              cancelled_at=NOW(), cancelled_by=:uid, updated_at=NOW()
            WHERE id=:id
        """),
        {"uid": user["id"], "id": order_id},
    )
    db.execute(text("UPDATE shipments SET status='Cancelled', updated_at=NOW() WHERE order_id=:id"), {"id": order_id})
    payments.cancel_for_order(db, order_id, actor_user_id=user["id"], note=req.reason)
    _insert_event(db, order_id, "Cancelled", "staff", note=req.reason, actor_user_id=user["id"],
                  actor_label=user["name"], chain_result=chain_result)
    auto_resolve(db, "vendor_order", order_id)
    notify(
        db, "contract.cancelled", {"orderer_user_id": order["orderer_user_id"]},
        title=f"Contract Cancelled — {order['order_code']}",
        body=f"An admin cancelled {order['order_code']}: {req.reason}. Any payment hold has been released.",
        entity_type="vendor_order", entity_id=order_id, action_path=f"/tracking/{order_id}",
        metadata={"order_id": order_id},
    )
    db.commit()
    return {"message": f"Contract for {order['order_code']} cancelled, payment hold released.", "chain": chain_result}


# ════════════════════════════════════════════════════════════════════════════
# SCHEDULED JOBS — plain functions, wired into reminder_scheduler.py's
# existing APScheduler (see that file) rather than adding a second one.
# In-app + staff email via notification_engine.notify() (Phase 3); vendor-
# facing reminder emails still go straight through n8n, as built in Phase 2.
# ════════════════════════════════════════════════════════════════════════════

def check_vendor_order_expiry(db: Session) -> int:
    """PENDING_VENDOR orders whose response window has passed -> EXPIRED."""
    rows = db.execute(
        text("""
            SELECT o.*, v.name AS vendor_name, v.order_email AS vendor_email
            FROM vendor_orders o JOIN vendors v ON v.id = o.vendor_id
            WHERE o.status = 'PENDING_VENDOR' AND o.expires_at <= NOW()
        """)
    ).mappings().all()
    for row in rows:
        order = dict(row)
        db.execute(text("UPDATE vendor_order_tokens SET revoked_at = NOW() WHERE order_id=:id AND used_at IS NULL"), {"id": order["id"]})
        db.execute(text("UPDATE vendor_orders SET status='EXPIRED', payout_status='Not Applicable', updated_at=NOW() WHERE id=:id"), {"id": order["id"]})
        notify(
            db, "order.expired", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Vendor Didn't Respond — {order['order_code']}",
            body=f"{order['vendor_name']} did not respond to {order['order_code']} in time. It has expired.",
            entity_type="vendor_order", entity_id=str(order["id"]), action_path=f"/tracking/{order['id']}",
            metadata={"order_id": str(order["id"])},
        )
        db.commit()
    return len(rows)


def check_vendor_order_reminders(db: Session) -> int:
    """PENDING_VENDOR orders nearing expiry, not yet reminded -> resend with
    a fresh token (the same mechanism as a manual resend)."""
    rows = db.execute(
        text("""
            SELECT o.*, v.name AS vendor_name, v.order_email AS vendor_email
            FROM vendor_orders o JOIN vendors v ON v.id = o.vendor_id
            WHERE o.status = 'PENDING_VENDOR' AND o.vendor_reminder_sent_at IS NULL
              AND o.expires_at <= NOW() + (:hours * INTERVAL '1 hour')
        """),
        {"hours": VENDOR_REMINDER_HOURS_BEFORE_EXPIRY},
    ).mappings().all()
    for row in rows:
        order = dict(row)
        db.execute(text("UPDATE vendor_order_tokens SET revoked_at = NOW() WHERE order_id=:id AND purpose='respond' AND used_at IS NULL"), {"id": order["id"]})
        token = secrets.token_urlsafe(32)
        db.execute(
            text("INSERT INTO vendor_order_tokens (id, order_id, purpose, token_hash, expires_at) VALUES (:id, :oid, 'respond', :hash, :exp)"),
            {"id": str(uuid.uuid4()), "oid": order["id"], "hash": _hash_token(token), "exp": order["expires_at"]},
        )
        db.execute(text("UPDATE vendor_orders SET vendor_reminder_sent_at=NOW() WHERE id=:id"), {"id": order["id"]})
        db.commit()
        items = _get_items(db, order["id"])
        accept_url = f"{FRONTEND_URL}/vendor/respond?order_id={order['id']}&token={token}&decision=accept"
        reject_url = f"{FRONTEND_URL}/vendor/respond?order_id={order['id']}&token={token}&decision=reject"
        trigger_vendor_order_email(order, items, accept_url, reject_url, str(order["expires_at"]))
    return len(rows)


def check_arrival_reminders(db: Session) -> int:
    """OutForDelivery/InTransit orders whose ETA passed a while ago with no
    arrival confirmation yet -> nudge the orderer once."""
    rows = db.execute(
        text("""
            SELECT o.*, s.eta FROM vendor_orders o
            JOIN shipments s ON s.order_id = o.id
            WHERE o.status = 'ACCEPTED' AND o.contract_status IN ('OutForDelivery', 'InTransit')
              AND o.arrival_reminder_sent_at IS NULL AND s.eta IS NOT NULL
              AND s.eta <= (NOW() - (:hours * INTERVAL '1 hour'))::date
        """),
        {"hours": ARRIVAL_REMINDER_HOURS_AFTER_ETA},
    ).mappings().all()
    for row in rows:
        order = dict(row)
        notify(
            db, "shipment.arrival_reminder", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Confirm Arrival? — {order['order_code']}",
            body="The ETA has passed — if this has arrived, please confirm so you can inspect and approve it.",
            entity_type="vendor_order", entity_id=str(order["id"]), action_path=f"/tracking/{order['id']}",
            dedupe_key=f"shipment.arrival_reminder:{order['id']}",
            metadata={"order_id": str(order["id"])},
        )
        db.execute(text("UPDATE vendor_orders SET arrival_reminder_sent_at=NOW() WHERE id=:id"), {"id": order["id"]})
        db.commit()
    return len(rows)


def check_approval_reminders(db: Session) -> int:
    """Arrived orders with no approve/dispute decision after a while ->
    nudge the orderer once."""
    rows = db.execute(
        text("""
            SELECT * FROM vendor_orders
            WHERE status = 'ACCEPTED' AND contract_status = 'Arrived'
              AND approval_reminder_sent_at IS NULL
              AND updated_at <= NOW() - (:hours * INTERVAL '1 hour')
        """),
        {"hours": APPROVAL_REMINDER_HOURS_AFTER_ARRIVAL},
    ).mappings().all()
    for row in rows:
        order = dict(row)
        notify(
            db, "shipment.approval_reminder", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Approve Receipt? — {order['order_code']}",
            body="This order has been sitting at Arrived — approve receipt or raise a dispute when you can.",
            entity_type="vendor_order", entity_id=str(order["id"]), action_path=f"/tracking/{order['id']}",
            dedupe_key=f"shipment.approval_reminder:{order['id']}",
            metadata={"order_id": str(order["id"])},
        )
        db.execute(text("UPDATE vendor_orders SET approval_reminder_sent_at=NOW() WHERE id=:id"), {"id": order["id"]})
        db.commit()
    return len(rows)


def check_delayed_shipments(db: Session) -> int:
    """ETA passed, not yet arrived -> notify orderer + PMs once. 'Delayed'
    stays a derived flag everywhere else (see _is_delayed) — this job only
    fires the one-time notification."""
    rows = db.execute(
        text("""
            SELECT o.*, s.eta FROM vendor_orders o
            JOIN shipments s ON s.order_id = o.id
            WHERE o.status = 'ACCEPTED'
              AND o.contract_status NOT IN ('Arrived', 'Approved', 'Executed', 'Cancelled', 'Disputed')
              AND o.delay_notified_at IS NULL AND s.eta IS NOT NULL AND s.eta < NOW()::date
        """)
    ).mappings().all()
    for row in rows:
        order = dict(row)
        notify(
            db, "shipment.delayed", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Delayed — {order['order_code']}",
            body=f"{order['order_code']} is delayed — ETA has passed with no arrival yet.",
            entity_type="vendor_order", entity_id=str(order["id"]), action_path=f"/tracking/{order['id']}",
            dedupe_key=f"shipment.delayed:{order['id']}",
            metadata={"order_id": str(order["id"])},
        )
        db.execute(text("UPDATE vendor_orders SET delay_notified_at=NOW() WHERE id=:id"), {"id": order["id"]})
        db.commit()
    return len(rows)


def check_vendor_status_checkins(db: Session) -> int:
    """3x/day (every VENDOR_STATUS_CHECKIN_INTERVAL_HOURS, default 8h)
    while a shipment is in flight: email the vendor their existing
    reusable shipment-update link again as a "what's the status?" nudge.
    Stops the moment contract_status leaves IN_FLIGHT_CONTRACT_STATUSES —
    confirm_arrival_endpoint clears next_status_checkin_due outright, and
    this WHERE clause is the second line of defense. Each nudge also drops
    a low-priority in-app notification for the orderer so "3 check-ins
    went out today" is visible on the order without digging into email."""
    rows = db.execute(
        text("""
            SELECT o.*, v.name AS vendor_name, v.order_email AS vendor_email
            FROM vendor_orders o JOIN vendors v ON v.id = o.vendor_id
            WHERE o.status = 'ACCEPTED'
              AND o.contract_status = ANY(:in_flight)
              AND o.next_status_checkin_due IS NOT NULL
              AND o.next_status_checkin_due <= NOW()
        """),
        {"in_flight": list(IN_FLIGHT_CONTRACT_STATUSES)},
    ).mappings().all()
    for row in rows:
        order = dict(row)
        # Tokens are stored hashed (see _hash_token) — the raw token from
        # acceptance isn't recoverable here, so mint a fresh 'ship_update'
        # token for this nudge rather than trying to reuse the original.
        # The original keeps working too (multiple live tokens per order
        # are fine, same as 'respond' tokens during a resend).
        new_token = secrets.token_urlsafe(32)
        db.execute(
            text("""
                INSERT INTO vendor_order_tokens (id, order_id, purpose, token_hash, expires_at)
                VALUES (:id, :oid, 'ship_update', :hash, :expires_at)
            """),
            {"id": str(uuid.uuid4()), "oid": order["id"], "hash": _hash_token(new_token),
             "expires_at": datetime.now(timezone.utc) + timedelta(days=30)},
        )
        ship_url = f"{FRONTEND_URL}/vendor/shipment?order_id={order['id']}&token={new_token}"
        items = _get_items(db, order["id"])
        trigger_vendor_order_status_checkin_email(order, items, ship_url)

        db.execute(
            text("""
                UPDATE vendor_orders SET
                  status_checkin_count = status_checkin_count + 1,
                  last_status_checkin_at = NOW(),
                  next_status_checkin_due = NOW() + (:checkin_hours * INTERVAL '1 hour')
                WHERE id = :id
            """),
            {"checkin_hours": VENDOR_STATUS_CHECKIN_INTERVAL_HOURS, "id": order["id"]},
        )
        notify(
            db, "shipment.status_checkin_sent", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Status Check-in Sent — {order['order_code']}",
            body=f"Asked {order['vendor_name']} for a delivery status update on {order['order_code']} "
                 f"(currently {order['contract_status']}).",
            entity_type="vendor_order", entity_id=str(order["id"]), action_path=f"/tracking/{order['id']}",
            metadata={"order_id": str(order["id"])},
        )
        db.commit()
    return len(rows)


_CHAIN_UNREACHABLE_NOTIFIED = False  # in-process edge-trigger: notify once per outage, once per recovery


def check_chain_health(db: Session) -> bool:
    """Admins get nudged once when the chain becomes unreachable (not on
    every 2-minute scheduler tick while it stays down) and the state resets
    once it reconnects, so a second outage notifies again."""
    global _CHAIN_UNREACHABLE_NOTIFIED
    status = chain.chain_status()
    # rpc_configured (CHAIN_RPC_URL set at all) is the real "chain
    # integration was intended" signal — `configured` (contract loaded)
    # is False both for a node that's down from the very first attempt
    # *and* for genuine dev mode, so gating on `configured` alone missed
    # exactly the "misconfigured from boot" case this check exists for.
    unreachable = status["rpc_configured"] and not status["connected"]
    if unreachable and not _CHAIN_UNREACHABLE_NOTIFIED:
        # No dedupe_key here deliberately — the (user_id, dedupe_key) unique
        # index would otherwise silently block every *future* outage
        # notification too, not just repeats of this one. The
        # _CHAIN_UNREACHABLE_NOTIFIED flag above already does the
        # once-per-outage edge-triggering within this process's lifetime.
        notify(
            db, "chain.unreachable", {},
            title="Blockchain node unreachable",
            body=f"Could not reach the {status['network']} chain node. On-chain confirmations will "
                 f"queue and retry automatically — business actions are not blocked.",
            entity_type="chain", entity_id=None, action_path="/tracking",
        )
        db.commit()
        _CHAIN_UNREACHABLE_NOTIFIED = True
    elif not unreachable:
        _CHAIN_UNREACHABLE_NOTIFIED = False
    return unreachable
