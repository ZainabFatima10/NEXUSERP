"""
NEXUS ERP — Payments (PKR only)
Organisation payment methods, the per-order payment ledger, and the
escrow -> capture -> vendor payout lifecycle that runs alongside the
on-chain ShipmentEscrow contract (see SHIPMENT_ESCROW.md, "Payments").

When money moves, for a vendor order:
  1. Vendor accepts         -> authorize_for_order(): hold total_amount on
                               the default payment method. The resulting
                               payment_ref is hashed into the on-chain
                               contract at creation. No method configured ->
                               'Payment Required' + admins notified.
  2. Orderer approves receipt (only possible after confirmed arrival — the
     contract enforces this) -> contract executes on-chain, then
                               capture_for_order() captures the hold and
                               schedules the vendor payout for
                               NOW() + PAYOUT_SETTLEMENT_HOURS.
  3. Payout due             -> process_due_payouts() (scheduler, every 5
                               min) pays vendor_payout_amount (subtotal —
                               the platform fee stays with the org) to the
                               vendor's IBAN on file and emails the vendor.
                               An admin can also release a payout early.
  Cancel / dispute-cancel   -> cancel_for_order() releases the hold.

Which processor moves the money is set by PAYMENT_PROVIDER (see
payment_providers.py): 'mock' simulates everything, 'manual' is the real
bank-transfer process — the payout waits as 'Awaiting Transfer' until an
admin records the bank transaction ID of the Raast/IBFT transfer they made.

Helpers in this module never commit — the caller commits once, the same
convention notification_engine.notify() uses.
"""
import csv
import io
import os
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from rbac import require_role, ROLE_ADMIN, ROLE_PROCUREMENT_MANAGER, get_current_user
from notification_engine import notify, auto_resolve
from n8n_service import trigger_vendor_order_payment_released_email
import payment_providers

router = APIRouter(tags=["Payments"])
_admin = Depends(require_role(ROLE_ADMIN))
_staff = Depends(require_role(ROLE_PROCUREMENT_MANAGER))

CURRENCY = payment_providers.CURRENCY
processor = payment_providers.get_provider()
PLATFORM_FEE_RATE = float(os.getenv("PLATFORM_FEE_RATE", "0.005"))   # 0.5% blockchain verification fee
# Cooling-off window between capture and vendor payout — gives an admin
# time to catch a mistaken approval before money leaves. 0 = pay instantly.
PAYOUT_SETTLEMENT_HOURS = int(os.getenv("PAYOUT_SETTLEMENT_HOURS", "24"))
# Ceiling on a single vendor order's total. Keeps each escrow hold/transfer
# within what a corporate Raast/IBFT transfer will clear in one go — set it
# to your bank's per-transaction limit. 0 = no cap.
PAYMENT_MAX_ORDER_PKR = float(os.getenv("PAYMENT_MAX_ORDER_PKR", "10000000"))


def check_order_cap(total_amount: float):
    if PAYMENT_MAX_ORDER_PKR and float(total_amount) > PAYMENT_MAX_ORDER_PKR:
        raise HTTPException(
            400,
            f"Order total PKR {float(total_amount):,.2f} exceeds the per-order payment limit of "
            f"PKR {PAYMENT_MAX_ORDER_PKR:,.0f}. Split it into smaller orders.",
        )

METHOD_TYPES = {
    "bank_transfer": "Bank Transfer (IBFT)",
    "raast": "Raast",
    "jazzcash": "JazzCash",
    "easypaisa": "Easypaisa",
}


# ────────────────────────────────────────────────────────────────────────────
# Money math
# ────────────────────────────────────────────────────────────────────────────

def compute_order_amounts(subtotal: float) -> dict:
    """subtotal (vendor's price) + platform fee = total the org pays.
    The vendor is paid the subtotal."""
    subtotal = round(float(subtotal), 2)
    fee = round(subtotal * PLATFORM_FEE_RATE, 2)
    return {"subtotal": subtotal, "platform_fee": fee, "total_amount": round(subtotal + fee, 2),
            "vendor_payout_amount": subtotal}


def to_paisa(amount: float) -> int:
    """PKR -> paisa, the smallest unit, for the on-chain `amount` field."""
    return int(round(float(amount) * 100))


def mask(identifier: Optional[str]) -> Optional[str]:
    if not identifier:
        return identifier
    s = identifier.replace(" ", "")
    return ("•" * max(len(s) - 4, 0)) + s[-4:]


# ────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ────────────────────────────────────────────────────────────────────────────

def get_default_method(db: Session) -> Optional[dict]:
    row = db.execute(
        text("SELECT * FROM payment_methods WHERE is_default = TRUE AND is_active = TRUE LIMIT 1")
    ).mappings().first()
    return dict(row) if row else None


def _load_order(db: Session, order_id: str) -> dict:
    row = db.execute(
        text("""
            SELECT o.*, v.name AS vendor_name, v.order_email AS vendor_email,
                   v.bank_name AS vendor_bank_name, v.bank_iban AS vendor_bank_iban,
                   v.bank_account_title AS vendor_bank_account_title
            FROM vendor_orders o JOIN vendors v ON v.id = o.vendor_id
            WHERE o.id = :id
        """),
        {"id": order_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, f"Order {order_id} not found")
    return dict(row)


def _log_txn(db: Session, order_id, kind: str, amount: float, status: str, *,
             provider_ref: str = None, method_id=None, note: str = None, actor_user_id=None):
    db.execute(
        text("""
            INSERT INTO payment_transactions
              (id, order_id, kind, amount, currency, status, provider_ref, payment_method_id, note, actor_user_id)
            VALUES (:id, :oid, :kind, :amount, 'PKR', :status, :ref, :mid, :note, :actor)
        """),
        {"id": str(uuid.uuid4()), "oid": str(order_id), "kind": kind, "amount": round(float(amount), 2),
         "status": status, "ref": provider_ref, "mid": str(method_id) if method_id else None,
         "note": note, "actor": actor_user_id},
    )


# ────────────────────────────────────────────────────────────────────────────
# Lifecycle — called from vendor_orders.py and the admin endpoints below
# ────────────────────────────────────────────────────────────────────────────

def authorize_for_order(db: Session, order_id: str, actor_user_id: str = None) -> dict:
    """Hold total_amount on the default method. Idempotent — an already
    authorized/captured order is returned unchanged."""
    order = _load_order(db, order_id)
    if order["payment_status"] in ("Authorized", "Captured"):
        return {"status": order["payment_status"], "payment_ref": order["payment_ref"]}

    method = get_default_method(db)
    total = float(order["total_amount"])
    result = processor.authorize(order["order_code"], total, order["currency"], method)

    db.execute(
        text("""
            UPDATE vendor_orders SET payment_status = :ps, payment_ref = :ref, payment_method_id = :mid,
              payment_authorized_at = CASE WHEN :authorized THEN NOW() ELSE payment_authorized_at END,
              updated_at = NOW()
            WHERE id = :id
        """),
        {"ps": result["status"], "ref": result["payment_ref"], "mid": str(method["id"]) if method else None,
         "authorized": result["status"] == "Authorized", "id": order_id},
    )
    _log_txn(db, order_id, "authorize", total,
             "Succeeded" if result["status"] == "Authorized" else ("Skipped" if result["status"] == "Payment Required" else "Failed"),
             provider_ref=result["payment_ref"], method_id=method["id"] if method else None,
             note=result.get("error"), actor_user_id=actor_user_id)

    if result["status"] == "Payment Required":
        notify(
            db, "payment.required", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Payment Method Needed — {order['order_code']}",
            body=f"{order['vendor_name']} accepted {order['order_code']} (PKR {total:,.2f}) but no default payment "
                 f"method is configured, so funds could not be held. Add one under Payments.",
            entity_type="vendor_order", entity_id=str(order_id), action_path="/payments",
            metadata={"order_id": str(order_id)},
        )
    elif result["status"] == "Failed":
        notify(
            db, "payment.failed", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Payment Authorization Failed — {order['order_code']}",
            body=f"Could not hold PKR {total:,.2f} for {order['order_code']}: {result.get('error') or 'unknown error'}.",
            entity_type="vendor_order", entity_id=str(order_id), action_path="/payments",
            metadata={"order_id": str(order_id)},
        )
    return result


def capture_for_order(db: Session, order_id: str, actor_user_id: str = None) -> dict:
    """Capture the escrowed funds and schedule the vendor payout. Only
    valid once the contract has executed (or is executing in this same
    request — the caller checks contract state, not this function)."""
    order = _load_order(db, order_id)
    if order["payment_status"] == "Captured":
        return {"status": "Captured", "payment_ref": order["payment_ref"]}
    if order["payment_status"] != "Authorized":
        return {"status": order["payment_status"], "payment_ref": order["payment_ref"],
                "error": "Funds are not authorized for this order"}

    total = float(order["total_amount"])
    result = processor.capture(order["order_code"], order["payment_ref"], total, order["currency"])

    if result["status"] == "Captured":
        db.execute(
            text("""
                UPDATE vendor_orders SET payment_status = 'Captured', payment_captured_at = NOW(),
                  payout_status = 'Scheduled',
                  payout_due_at = NOW() + (:hours * INTERVAL '1 hour'),
                  updated_at = NOW()
                WHERE id = :id
            """),
            {"hours": PAYOUT_SETTLEMENT_HOURS, "id": order_id},
        )
        _log_txn(db, order_id, "capture", total, "Succeeded", provider_ref=result["payment_ref"],
                 method_id=order["payment_method_id"], actor_user_id=actor_user_id)
        payout = float(order["vendor_payout_amount"] or order["subtotal"])
        when = "immediately" if PAYOUT_SETTLEMENT_HOURS == 0 else f"in {PAYOUT_SETTLEMENT_HOURS}h"
        notify(
            db, "payment.captured", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Payment Captured — {order['order_code']}",
            body=f"PKR {total:,.2f} captured for {order['order_code']}. PKR {payout:,.2f} will be paid out to "
                 f"{order['vendor_name']} {when}.",
            entity_type="vendor_order", entity_id=str(order_id), action_path=f"/tracking/{order_id}",
            metadata={"order_id": str(order_id)},
        )
    else:
        db.execute(text("UPDATE vendor_orders SET payment_status = 'Failed', updated_at = NOW() WHERE id = :id"),
                   {"id": order_id})
        _log_txn(db, order_id, "capture", total, "Failed", provider_ref=order["payment_ref"],
                 method_id=order["payment_method_id"], note=result.get("error"), actor_user_id=actor_user_id)
        notify(
            db, "payment.failed", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Payment Capture Failed — {order['order_code']}",
            body=f"The contract for {order['order_code']} executed but capturing PKR {total:,.2f} failed: "
                 f"{result.get('error') or 'unknown error'}. Retry from Payments.",
            entity_type="vendor_order", entity_id=str(order_id), action_path="/payments",
            metadata={"order_id": str(order_id)},
        )
    return result


def cancel_for_order(db: Session, order_id: str, actor_user_id: str = None, note: str = None) -> dict:
    """Release any hold and mark the payout as not applicable."""
    order = _load_order(db, order_id)
    status = order["payment_status"]
    if status == "Authorized":
        result = processor.cancel(order["order_code"], order["payment_ref"])
        _log_txn(db, order_id, "cancel", float(order["total_amount"]), "Succeeded",
                 provider_ref=order["payment_ref"], method_id=order["payment_method_id"],
                 note=note, actor_user_id=actor_user_id)
        status = result["status"]
    elif status == "Payment Required":
        status = "Cancelled"
    db.execute(
        text("UPDATE vendor_orders SET payment_status = :ps, payout_status = 'Not Applicable', updated_at = NOW() WHERE id = :id"),
        {"ps": status, "id": order_id},
    )
    return {"status": status}


def _mark_payout_paid(db: Session, order: dict, payout_ref: str, actor_user_id: str = None, note: str = None):
    amount = float(order["vendor_payout_amount"] or order["subtotal"])
    order_id = str(order["id"])
    db.execute(
        text("""
            UPDATE vendor_orders SET payout_status = 'Paid', payout_paid_at = NOW(), payout_ref = :ref,
              payout_confirmed_by = :actor, updated_at = NOW()
            WHERE id = :id
        """),
        {"ref": payout_ref, "actor": actor_user_id, "id": order_id},
    )
    _log_txn(db, order_id, "payout", amount, "Succeeded", provider_ref=payout_ref, note=note, actor_user_id=actor_user_id)
    try:
        trigger_vendor_order_payment_released_email({**order, "vendor_payout_amount": amount, "payout_ref": payout_ref})
    except Exception as e:
        print(f"[WARN] payment-released email failed: {e}")
    notify(
        db, "payment.payout_sent", {"orderer_user_id": order["orderer_user_id"]},
        title=f"Vendor Paid — {order['order_code']}",
        body=f"PKR {amount:,.2f} paid to {order['vendor_name']} for {order['order_code']} (ref {payout_ref}).",
        entity_type="vendor_order", entity_id=order_id, action_path=f"/tracking/{order_id}",
        metadata={"order_id": order_id},
    )


def release_payout(db: Session, order_id: str, actor_user_id: str = None) -> dict:
    """Start the vendor payout. With an automatic provider this pays the
    vendor; with 'manual' it raises an 'Awaiting Transfer' task for admins.
    Only for captured orders with a scheduled (or previously failed) payout."""
    order = _load_order(db, order_id)
    if order["payment_status"] != "Captured":
        raise HTTPException(400, f"Payment has not been captured (currently {order['payment_status']})")
    if order["payout_status"] in ("Paid", "Awaiting Transfer"):
        return {"status": order["payout_status"], "payout_ref": order["payout_ref"]}
    if order["payout_status"] not in ("Scheduled", "Failed"):
        raise HTTPException(400, f"Payout is not scheduled (currently {order['payout_status']})")

    amount = float(order["vendor_payout_amount"] or order["subtotal"])
    vendor = {"name": order["vendor_name"], "bank_iban": order["vendor_bank_iban"]}
    result = processor.payout(order["order_code"], amount, order["currency"], vendor)

    if result["status"] == "Paid":
        _mark_payout_paid(db, order, result["payout_ref"], actor_user_id)
    elif result["status"] == "Awaiting Transfer":
        db.execute(text("UPDATE vendor_orders SET payout_status = 'Awaiting Transfer', updated_at = NOW() WHERE id = :id"), {"id": order_id})
        notify(
            db, "payment.transfer_required", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Send Vendor Payment — {order['order_code']}",
            body=f"Transfer PKR {amount:,.2f} to {order['vendor_name']} (IBAN ending {(order['vendor_bank_iban'] or '')[-4:]}) "
                 f"via Raast/IBFT, then record the bank transaction ID under Payments.",
            entity_type="vendor_order", entity_id=str(order_id), action_path="/payments",
            metadata={"order_id": str(order_id)},
        )
    else:
        db.execute(text("UPDATE vendor_orders SET payout_status = 'Failed', updated_at = NOW() WHERE id = :id"), {"id": order_id})
        _log_txn(db, order_id, "payout", amount, "Failed", note=result.get("error"), actor_user_id=actor_user_id)
        notify(
            db, "payment.failed", {"orderer_user_id": order["orderer_user_id"]},
            title=f"Vendor Payout Failed — {order['order_code']}",
            body=f"Could not pay PKR {amount:,.2f} to {order['vendor_name']}: {result.get('error') or 'unknown error'}.",
            entity_type="vendor_order", entity_id=str(order_id), action_path="/payments",
            metadata={"order_id": str(order_id)},
        )
    return result


def confirm_manual_payout(db: Session, order_id: str, bank_reference: str, actor_user_id: str, note: str = None) -> dict:
    """An admin made the Raast/IBFT transfer in the bank portal — record it."""
    order = _load_order(db, order_id)
    if order["payout_status"] == "Paid":
        raise HTTPException(400, f"Already recorded as paid (ref {order['payout_ref']})")
    if order["payout_status"] != "Awaiting Transfer":
        raise HTTPException(400, f"Payout is not awaiting a transfer (currently {order['payout_status']})")
    ref = (bank_reference or "").strip()
    if not (4 <= len(ref) <= 100):
        raise HTTPException(400, "Enter the bank's transaction ID / reference (4-100 characters)")
    dup = db.execute(
        text("SELECT order_code FROM vendor_orders WHERE payout_ref = :ref AND id <> :id"), {"ref": ref, "id": order_id}
    ).scalar()
    if dup:
        raise HTTPException(409, f"That bank reference is already recorded against {dup}")
    _mark_payout_paid(db, order, ref, actor_user_id, note=note or "Bank transfer recorded by admin")
    auto_resolve(db, "vendor_order", order_id)  # closes the "Send Vendor Payment" task
    return {"status": "Paid", "payout_ref": ref}


def process_due_payouts(db: Session) -> int:
    """Scheduler job: pay every vendor whose payout window has elapsed."""
    ids = db.execute(
        text("""
            SELECT id FROM vendor_orders
            WHERE payout_status = 'Scheduled' AND payment_status = 'Captured' AND payout_due_at <= NOW()
            ORDER BY payout_due_at ASC LIMIT 50
        """)
    ).scalars().all()
    for oid in ids:
        release_payout(db, str(oid))
        db.commit()
    return len(ids)


def retry_payment_required(db: Session) -> int:
    """Called right after an admin sets a default method — authorize every
    accepted order that was stuck at 'Payment Required'."""
    ids = db.execute(
        text("""
            SELECT id FROM vendor_orders
            WHERE status = 'ACCEPTED' AND payment_status = 'Payment Required'
              AND contract_status NOT IN ('Cancelled')
        """)
    ).scalars().all()
    for oid in ids:
        authorize_for_order(db, str(oid))
    return len(ids)


# ════════════════════════════════════════════════════════════════════════════
# API — payment methods (admin)
# ════════════════════════════════════════════════════════════════════════════

def _method_out(row) -> dict:
    d = dict(row)
    d["account_identifier"] = mask(d["account_identifier"])
    d["method_type_label"] = METHOD_TYPES.get(d["method_type"], d["method_type"])
    return d


@router.get("/api/payments/config", dependencies=[_staff])
def payments_config(db: Session = Depends(get_db)):
    return {
        "currency": CURRENCY,
        "platform_fee_rate": PLATFORM_FEE_RATE,
        "payout_settlement_hours": PAYOUT_SETTLEMENT_HOURS,
        "method_types": [{"value": k, "label": v} for k, v in METHOD_TYPES.items()],
        "has_default_method": get_default_method(db) is not None,
        "provider": processor.name,
        "provider_label": processor.label,
        "automatic_payouts": processor.automatic_payouts,
        "max_order_total": PAYMENT_MAX_ORDER_PKR or None,
    }


@router.get("/api/payments/methods", dependencies=[_admin])
def list_payment_methods(db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT * FROM payment_methods WHERE is_active = TRUE ORDER BY is_default DESC, created_at ASC")
    ).mappings().all()
    return {"methods": [_method_out(r) for r in rows]}


class PaymentMethodRequest(BaseModel):
    method_type: str
    label: str
    account_title: str
    bank_name: Optional[str] = None
    account_identifier: str
    is_default: bool = False


@router.post("/api/payments/methods", dependencies=[_admin])
def create_payment_method(req: PaymentMethodRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    if req.method_type not in METHOD_TYPES:
        raise HTTPException(400, f"method_type must be one of: {', '.join(METHOD_TYPES)}")
    ident = req.account_identifier.replace(" ", "").upper()
    if req.method_type == "bank_transfer":
        if not (ident.startswith("PK") and len(ident) == 24 and ident[2:].isalnum()):
            raise HTTPException(400, "A Pakistani IBAN is 24 characters and starts with 'PK'")
        if not (req.bank_name or "").strip():
            raise HTTPException(400, "Bank name is required for bank transfers")
    elif req.method_type in ("jazzcash", "easypaisa"):
        digits = ident.lstrip("+")
        if digits.startswith("92"):
            digits = "0" + digits[2:]
        if not (digits.isdigit() and len(digits) == 11 and digits.startswith("03")):
            raise HTTPException(400, "Mobile wallet number must be 11 digits, e.g. 03001234567")
        ident = digits
    elif req.method_type == "raast":
        if len(ident) < 6:
            raise HTTPException(400, "Enter a Raast ID (mobile number) or IBAN")
    if not req.label.strip() or not req.account_title.strip():
        raise HTTPException(400, "Label and account title are required")

    has_default = get_default_method(db) is not None
    make_default = req.is_default or not has_default  # the first method is always the default
    if make_default:
        db.execute(text("UPDATE payment_methods SET is_default = FALSE, updated_at = NOW() WHERE is_default = TRUE"))
    method_id = str(uuid.uuid4())
    db.execute(
        text("""
            INSERT INTO payment_methods (id, method_type, label, account_title, bank_name, account_identifier,
                                         currency, is_default, created_by)
            VALUES (:id, :type, :label, :title, :bank, :ident, 'PKR', :is_default, :uid)
        """),
        {"id": method_id, "type": req.method_type, "label": req.label.strip(), "title": req.account_title.strip(),
         "bank": (req.bank_name or "").strip() or None, "ident": ident, "is_default": make_default, "uid": user["id"]},
    )
    db.commit()

    authorized = 0
    if make_default:
        authorized = retry_payment_required(db)
        db.commit()
    msg = "Payment method added" + (" and set as default" if make_default else "") + "."
    if authorized:
        msg += f" Authorized {authorized} order(s) that were waiting for a payment method."
    return {"id": method_id, "message": msg}


@router.post("/api/payments/methods/{method_id}/default", dependencies=[_admin])
def set_default_payment_method(method_id: str, db: Session = Depends(get_db)):
    row = db.execute(text("SELECT id FROM payment_methods WHERE id = :id AND is_active = TRUE"), {"id": method_id}).first()
    if not row:
        raise HTTPException(404, "Payment method not found")
    db.execute(text("UPDATE payment_methods SET is_default = FALSE, updated_at = NOW() WHERE is_default = TRUE"))
    db.execute(text("UPDATE payment_methods SET is_default = TRUE, updated_at = NOW() WHERE id = :id"), {"id": method_id})
    db.commit()
    authorized = retry_payment_required(db)
    db.commit()
    return {"message": "Default payment method updated." + (f" Authorized {authorized} waiting order(s)." if authorized else "")}


@router.delete("/api/payments/methods/{method_id}", dependencies=[_admin])
def remove_payment_method(method_id: str, db: Session = Depends(get_db)):
    """Soft-delete — existing orders keep pointing at it for the audit trail."""
    row = db.execute(text("SELECT is_default FROM payment_methods WHERE id = :id AND is_active = TRUE"), {"id": method_id}).mappings().first()
    if not row:
        raise HTTPException(404, "Payment method not found")
    held = db.execute(
        text("SELECT COUNT(*) FROM vendor_orders WHERE payment_method_id = :id AND payment_status = 'Authorized'"), {"id": method_id}
    ).scalar() or 0
    if held:
        raise HTTPException(409, f"{held} order(s) have funds held on this method — it can be removed once they settle.")
    db.execute(text("UPDATE payment_methods SET is_active = FALSE, is_default = FALSE, updated_at = NOW() WHERE id = :id"), {"id": method_id})
    db.commit()
    return {"message": "Payment method removed." + (" No default method is set now — add or choose one." if row["is_default"] else "")}


# ════════════════════════════════════════════════════════════════════════════
# API — ledger, summary, per-order transactions, admin actions
# ════════════════════════════════════════════════════════════════════════════

@router.get("/api/payments/summary", dependencies=[_admin])
def payments_summary(db: Session = Depends(get_db)):
    row = db.execute(
        text("""
            SELECT
              COALESCE(SUM(total_amount) FILTER (WHERE payment_status = 'Authorized'), 0)              AS held_in_escrow,
              COUNT(*)                   FILTER (WHERE payment_status = 'Authorized')                  AS held_count,
              COALESCE(SUM(total_amount) FILTER (WHERE payment_status = 'Payment Required'), 0)         AS awaiting_method,
              COUNT(*)                   FILTER (WHERE payment_status = 'Payment Required')            AS awaiting_method_count,
              COALESCE(SUM(vendor_payout_amount) FILTER (WHERE payout_status IN ('Scheduled','Awaiting Transfer','Failed')), 0) AS payouts_pending,
              COUNT(*)                   FILTER (WHERE payout_status IN ('Scheduled','Awaiting Transfer','Failed')) AS payouts_pending_count,
              COUNT(*)                   FILTER (WHERE payout_status = 'Awaiting Transfer')             AS awaiting_transfer_count,
              COALESCE(SUM(vendor_payout_amount) FILTER (WHERE payout_status = 'Paid'), 0)              AS paid_out,
              COUNT(*)                   FILTER (WHERE payout_status = 'Paid')                          AS paid_out_count,
              COALESCE(SUM(platform_fee) FILTER (WHERE payment_status = 'Captured'), 0)                 AS fees_collected,
              COUNT(*)                   FILTER (WHERE payment_status = 'Failed' OR payout_status = 'Failed') AS failed_count
            FROM vendor_orders
        """)
    ).mappings().first()
    out = {k: (float(v) if not k.endswith("_count") else int(v)) for k, v in dict(row).items()}
    out["currency"] = CURRENCY
    return out


@router.get("/api/payments/ledger", dependencies=[_admin])
def payments_ledger(
    payment_status: Optional[str] = Query(None),
    payout_status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    filters = "WHERE (o.status = 'ACCEPTED' OR o.payment_status <> 'Not Required')"
    params: dict = {"limit": limit}
    if payment_status:
        filters += " AND o.payment_status = :ps"
        params["ps"] = payment_status
    if payout_status:
        filters += " AND o.payout_status = :pos"
        params["pos"] = payout_status
    if search:
        filters += " AND (o.order_code ILIKE :q OR v.name ILIKE :q)"
        params["q"] = f"%{search}%"

    rows = db.execute(
        text(f"""
            SELECT o.id, o.order_code, o.status, o.contract_status, o.chain_order_id, o.chain_network,
                   o.payment_status, o.payment_ref, o.payout_status, o.payout_ref,
                   o.subtotal, o.platform_fee, o.total_amount, o.vendor_payout_amount, o.currency,
                   o.payment_authorized_at, o.payment_captured_at, o.payout_due_at, o.payout_paid_at,
                   o.created_at, o.updated_at,
                   v.name AS vendor_name, v.bank_name AS vendor_bank_name, v.bank_iban AS vendor_bank_iban,
                   v.payment_terms AS vendor_payment_terms,
                   u.name AS orderer_name, pm.label AS payment_method_label,
                   (SELECT COUNT(*) FROM chain_tx_queue q WHERE q.order_id = o.id AND q.status = 'pending') AS chain_pending,
                   (SELECT COUNT(*) FROM chain_tx_queue q WHERE q.order_id = o.id AND q.status = 'confirmed') AS chain_confirmed
            FROM vendor_orders o
            JOIN vendors v ON v.id = o.vendor_id
            JOIN users u ON u.id = o.orderer_user_id
            LEFT JOIN payment_methods pm ON pm.id = o.payment_method_id
            {filters}
            ORDER BY
              CASE WHEN o.payment_status IN ('Payment Required','Failed') OR o.payout_status IN ('Failed','Awaiting Transfer') THEN 0
                   WHEN o.payout_status = 'Scheduled' THEN 1 ELSE 2 END,
              o.updated_at DESC
            LIMIT :limit
        """),
        params,
    ).mappings().all()

    out = []
    for r in rows:
        d = dict(r)
        for k in ("subtotal", "platform_fee", "total_amount", "vendor_payout_amount"):
            d[k] = float(d[k]) if d[k] is not None else None
        d["vendor_bank_iban"] = mask(d["vendor_bank_iban"])
        d["chain_pending"] = int(d["chain_pending"] or 0)
        d["chain_confirmed"] = int(d["chain_confirmed"] or 0)
        out.append(d)
    return {"orders": out}


@router.get("/api/payments/orders/{order_id}/transactions", dependencies=[_staff])
def order_payment_transactions(order_id: str, db: Session = Depends(get_db)):
    rows = db.execute(
        text("""
            SELECT t.*, pm.label AS payment_method_label, u.name AS actor_name
            FROM payment_transactions t
            LEFT JOIN payment_methods pm ON pm.id = t.payment_method_id
            LEFT JOIN users u ON u.id = t.actor_user_id
            WHERE t.order_id = :id ORDER BY t.created_at ASC
        """),
        {"id": order_id},
    ).mappings().all()
    return {"transactions": [{**dict(r), "amount": float(r["amount"])} for r in rows]}


@router.post("/api/payments/orders/{order_id}/authorize", dependencies=[_admin])
def admin_authorize(order_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    order = _load_order(db, order_id)
    if order["status"] != "ACCEPTED" or order["contract_status"] in ("Cancelled", "Executed"):
        raise HTTPException(400, "Only accepted, open orders can be authorized")
    if order["payment_status"] not in ("Payment Required", "Failed"):
        raise HTTPException(400, f"Payment is already {order['payment_status']}")
    if order["payment_status"] == "Failed":
        db.execute(text("UPDATE vendor_orders SET payment_status = 'Payment Required' WHERE id = :id"), {"id": order_id})
    result = authorize_for_order(db, order_id, actor_user_id=user["id"])
    db.commit()
    if result["status"] != "Authorized":
        raise HTTPException(409, result.get("error") or f"Authorization did not succeed ({result['status']})")
    return {"message": f"PKR {float(order['total_amount']):,.2f} authorized and held for {order['order_code']}."}


@router.post("/api/payments/orders/{order_id}/capture", dependencies=[_admin])
def admin_retry_capture(order_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """For an executed contract whose capture failed."""
    order = _load_order(db, order_id)
    if order["contract_status"] != "Executed":
        raise HTTPException(400, "Funds can only be captured once the contract has executed")
    if order["payment_status"] == "Failed" and order["payment_ref"]:
        # A failed capture still has the original hold behind it
        db.execute(text("UPDATE vendor_orders SET payment_status = 'Authorized' WHERE id = :id"), {"id": order_id})
    elif order["payment_status"] in ("Payment Required", "Failed"):
        auth = authorize_for_order(db, order_id, actor_user_id=user["id"])
        if auth["status"] != "Authorized":
            db.commit()
            raise HTTPException(409, "Add a default payment method first")
    result = capture_for_order(db, order_id, actor_user_id=user["id"])
    if result["status"] == "Captured" and PAYOUT_SETTLEMENT_HOURS == 0:
        release_payout(db, order_id, actor_user_id=user["id"])
    db.commit()
    if result["status"] != "Captured":
        raise HTTPException(409, result.get("error") or "Capture failed")
    return {"message": f"Payment captured for {order['order_code']}."}


@router.post("/api/payments/orders/{order_id}/release-payout", dependencies=[_admin])
def admin_release_payout(order_id: str, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    result = release_payout(db, order_id, actor_user_id=user["id"])
    db.commit()
    if result["status"] == "Awaiting Transfer":
        return {"message": "Payout released — make the bank transfer, then record its transaction ID."}
    if result["status"] != "Paid":
        raise HTTPException(409, result.get("error") or "Payout failed")
    return {"message": f"Vendor paid (ref {result['payout_ref']})."}


# ════════════════════════════════════════════════════════════════════════════
# API — manual bank transfers (PAYMENT_PROVIDER=manual)
# ════════════════════════════════════════════════════════════════════════════

def _pending_transfers(db: Session) -> list:
    rows = db.execute(
        text("""
            SELECT o.id, o.order_code, o.vendor_payout_amount, o.subtotal, o.payment_captured_at, o.payout_due_at,
                   v.name AS vendor_name, v.bank_name, v.bank_account_title, v.bank_iban
            FROM vendor_orders o JOIN vendors v ON v.id = o.vendor_id
            WHERE o.payout_status = 'Awaiting Transfer'
            ORDER BY o.payout_due_at ASC NULLS LAST
        """)
    ).mappings().all()
    return [
        {**dict(r), "amount": float(r["vendor_payout_amount"] or r["subtotal"]),
         "transfer_reference": f"NEXUS {r['order_code']}"}
        for r in rows
    ]


@router.get("/api/payments/payouts/pending-transfers", dependencies=[_admin])
def pending_transfers(db: Session = Depends(get_db)):
    """Full (unmasked) beneficiary details — admin-only, needed to make the transfer."""
    items = _pending_transfers(db)
    for i in items:
        i.pop("vendor_payout_amount", None)
        i["subtotal"] = float(i["subtotal"])
    return {"transfers": items, "total": round(sum(i["amount"] for i in items), 2)}


@router.get("/api/payments/payouts/pending-transfers.csv", dependencies=[_admin])
def pending_transfers_csv(db: Session = Depends(get_db)):
    """One row per transfer — the columns most Pakistani corporate banking
    portals ask for in a bulk IBFT/Raast upload. Re-map column order to your
    bank's template if it differs."""
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Beneficiary Name", "Beneficiary Account Title", "Beneficiary Bank", "IBAN", "Amount (PKR)", "Reference", "Order Code"])
    for t in _pending_transfers(db):
        w.writerow([t["vendor_name"], t["bank_account_title"] or t["vendor_name"], t["bank_name"] or "",
                    (t["bank_iban"] or "").replace(" ", ""), f"{t['amount']:.2f}", t["transfer_reference"], t["order_code"]])
    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": "attachment; filename=nexus-vendor-payouts.csv"})


class ConfirmPayoutRequest(BaseModel):
    bank_reference: str
    note: Optional[str] = None


@router.post("/api/payments/orders/{order_id}/confirm-payout", dependencies=[_admin])
def admin_confirm_payout(order_id: str, req: ConfirmPayoutRequest, user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    result = confirm_manual_payout(db, order_id, req.bank_reference, user["id"], req.note)
    db.commit()
    return {"message": f"Transfer recorded (ref {result['payout_ref']}). Vendor notified."}
