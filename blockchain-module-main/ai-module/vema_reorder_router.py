"""
NEXUS ERP — VEMA Auto-Reorder Router
  GET  /api/procurement/vema-requests              — list, filters + pagination
  GET  /api/procurement/vema-requests/stats        — counts for badge + summary cards
  GET  /api/procurement/vema-requests/{id}         — detail
  POST /api/procurement/vema-requests/{id}/approve — creates the real order
  POST /api/procurement/vema-requests/{id}/reject

Approvers: Procurement Manager + Admin (admin always implicit via
require_role — rbac.py). Customer Representative has no access to this
feature at all — not in VEMA_REORDER_APPROVER_ROLES, so require_role()
403s before any handler runs; the frontend hides the nav entry too.
VEMA_REORDER_APPROVER_ROLES is the one list to edit if that changes.

On approve: reuses procurement.create_pending_approval_order() +
procurement.approve_reorder() exactly as they are — this router never
inserts into procurement_orders itself. See those functions' docstrings
and docs/VEMA_AUTO_REORDER.md for why (the "accept/reject webhook" vendor
email flow those two functions already implement is the one this task
asked to reuse, not create_order()'s separate direct-SMTP confirm-link
flow — the two are not interchangeable, see VEMA_AUTO_REORDER.md).
"""
import json
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from database import get_db
from rbac import require_role, get_current_user, ROLE_PROCUREMENT_MANAGER, ROLE_ADMIN
from notification_service import notify_role

router = APIRouter(prefix="/api/procurement", tags=["VEMA Auto-Reorders"])

VEMA_REORDER_APPROVER_ROLES = [ROLE_PROCUREMENT_MANAGER]
_approver = Depends(require_role(*VEMA_REORDER_APPROVER_ROLES))


def _row_to_dict(row: dict) -> dict:
    out = dict(row)
    for key in ("alt_vendor_ids", "vendor_score_breakdown"):
        if isinstance(out.get(key), str):
            try:
                out[key] = json.loads(out[key])
            except Exception:
                pass
    return out


def _get_request(db: Session, request_id: str) -> dict:
    row = db.execute(
        text("""
            SELECT r.*, i.name AS item_name, i.unit, i.category,
                   v.name AS vendor_name, v.email AS vendor_email
            FROM vema_reorder_requests r
            JOIN inventory_items i ON i.item_id = r.item_id
            LEFT JOIN vendors v ON v.id = r.vendor_id
            WHERE r.id = :id
        """),
        {"id": request_id},
    ).mappings().first()
    if not row:
        raise HTTPException(404, f"Request {request_id} not found")
    return _row_to_dict(dict(row))


def _notify_other_approvers(db: Session, acting_role: str, **kwargs):
    """'Notify the other approver role' (task section 4) — whichever of
    {Procurement Manager, Admin} did NOT make this decision. Never raises;
    a failed notification must never fail the approve/reject action itself."""
    all_roles = set(VEMA_REORDER_APPROVER_ROLES) | {ROLE_ADMIN}
    for role in all_roles - {acting_role}:
        try:
            notify_role(db, role, **kwargs)
        except Exception as e:
            print(f"[WARN] vema_reorder_router: notify {role} failed ({e})")


@router.get("/vema-requests", dependencies=[_approver])
def list_vema_requests(
    status: Optional[str] = Query(None),
    item_id: Optional[str] = Query(None),
    vendor_id: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    filters = ["1=1"]
    params = {"limit": limit, "offset": offset}
    if status:
        filters.append("r.status = :status")
        params["status"] = status
    if item_id:
        filters.append("r.item_id = :item_id")
        params["item_id"] = item_id
    if vendor_id:
        filters.append("r.vendor_id = :vendor_id")
        params["vendor_id"] = vendor_id
    if search:
        filters.append("(r.request_code ILIKE :search OR i.name ILIKE :search)")
        params["search"] = f"%{search}%"
    if date_from:
        filters.append("r.created_at >= :date_from")
        params["date_from"] = date_from
    if date_to:
        filters.append("r.created_at <= :date_to")
        params["date_to"] = date_to

    where = " AND ".join(filters)
    rows = db.execute(
        text(f"""
            SELECT r.*, i.name AS item_name, i.unit, i.category,
                   v.name AS vendor_name, v.email AS vendor_email
            FROM vema_reorder_requests r
            JOIN inventory_items i ON i.item_id = r.item_id
            LEFT JOIN vendors v ON v.id = r.vendor_id
            WHERE {where}
            ORDER BY r.created_at DESC
            LIMIT :limit OFFSET :offset
        """),
        params,
    ).mappings().all()
    count_params = {k: v for k, v in params.items() if k not in ("limit", "offset")}
    total = db.execute(
        text(f"""
            SELECT COUNT(*) FROM vema_reorder_requests r
            JOIN inventory_items i ON i.item_id = r.item_id
            WHERE {where}
        """),
        count_params,
    ).scalar()
    return {"requests": [_row_to_dict(dict(r)) for r in rows], "total": total}


@router.get("/vema-requests/stats", dependencies=[_approver])
def vema_request_stats(db: Session = Depends(get_db)):
    rows = db.execute(
        text("SELECT status, COUNT(*) AS n FROM vema_reorder_requests GROUP BY status")
    ).mappings().all()
    counts = {r["status"]: r["n"] for r in rows}
    pending = counts.get("pending_approval", 0)
    approved = counts.get("approved", 0)
    rejected = counts.get("rejected", 0)
    expired = counts.get("expired", 0)
    decided = approved + rejected
    approval_rate = round(approved / decided * 100, 1) if decided else None
    return {
        "pending": pending, "approved": approved, "rejected": rejected, "expired": expired,
        "approval_rate": approval_rate,
    }


@router.get("/vema-requests/{request_id}", dependencies=[_approver])
def get_vema_request(request_id: str, db: Session = Depends(get_db)):
    return _get_request(db, request_id)


class ApproveRequestBody(BaseModel):
    qty: Optional[int] = None
    vendor_id: Optional[str] = None
    note: Optional[str] = None


@router.post("/vema-requests/{request_id}/approve", dependencies=[_approver])
def approve_vema_request(
    request_id: str, body: ApproveRequestBody,
    user: dict = Depends(get_current_user), db: Session = Depends(get_db),
):
    from procurement import create_pending_approval_order, approve_reorder

    req = _get_request(db, request_id)
    if req["status"] != "pending_approval":
        raise HTTPException(409, f"Request is not pending approval (status: {req['status']})")

    final_vendor_id = body.vendor_id or req["vendor_id"]
    final_qty = body.qty if body.qty is not None else req["suggested_qty"]
    if not final_vendor_id:
        raise HTTPException(422, "No vendor selected — choose one before approving (vendor_id required)")
    if final_qty <= 0:
        raise HTTPException(422, "Quantity must be positive")

    vendor = db.execute(
        text("SELECT id, name, email FROM vendors WHERE id = :id AND status = 'active'"),
        {"id": final_vendor_id},
    ).mappings().first()
    if not vendor:
        raise HTTPException(422, "Selected vendor is not an approved/active vendor")

    item_row = db.execute(
        text("SELECT * FROM inventory_items WHERE item_id = :id"), {"id": req["item_id"]}
    ).mappings().first()
    if not item_row:
        raise HTTPException(404, f"Item {req['item_id']} no longer exists")

    item = dict(item_row)
    item["vendor_id"] = vendor["id"]
    item["vendor_name"] = vendor["name"]
    item["vendor_email"] = vendor["email"]
    item["reorder_quantity"] = final_qty
    if body.vendor_id and body.vendor_id != req["vendor_id"]:
        # Approver picked a different vendor than suggested — look up that
        # vendor's own catalogue price rather than reusing the original
        # (now-wrong) estimate.
        vi = db.execute(
            text("""
                SELECT unit_price FROM vendor_items
                WHERE vendor_id = :vid AND is_active = TRUE ORDER BY unit_price LIMIT 1
            """),
            {"vid": final_vendor_id},
        ).mappings().first()
        item["unit_price"] = float(vi["unit_price"]) if vi else item.get("unit_price")
    else:
        item["unit_price"] = req["unit_price_est"] if req["unit_price_est"] is not None else item.get("unit_price")

    order_result = create_pending_approval_order(db, item)
    if order_result.get("skipped"):
        raise HTTPException(422, f"Could not create order: {order_result.get('reason', 'unknown reason')}")

    approve_result = approve_reorder(order_result["order_id"], user, db)

    db.execute(
        text("""
            UPDATE vema_reorder_requests SET
              status = 'approved', decided_by = :uid, decided_at = NOW(),
              decision_note = :note, edited_qty = :eqty, edited_vendor_id = :evendor,
              resulting_order_id = :order_id, updated_at = NOW()
            WHERE id = :id
        """),
        {
            "uid": user["id"], "note": body.note,
            "eqty": body.qty, "evendor": body.vendor_id,
            "order_id": order_result["order_id"], "id": request_id,
        },
    )
    db.execute(
        text("""
            INSERT INTO vema_reorder_audit_log (id, request_id, action, actor_id, note, metadata)
            VALUES (:id, :rid, 'approved', :uid, :note, CAST(:meta AS jsonb))
        """),
        {
            "id": str(uuid.uuid4()), "rid": request_id, "uid": user["id"], "note": body.note,
            "meta": json.dumps({
                "order_id": order_result["order_id"],
                "vendor_email_status": approve_result.get("vendor_email_status"),
            }),
        },
    )
    db.commit()

    email_status = approve_result.get("vendor_email_status", "")
    description = f"{req['item_name']} — order {order_result['order_code']} created."
    if email_status == "Failed":
        description += " Vendor email failed to send — use Vendor Communication to resend."
    _notify_other_approvers(
        db, user["role"],
        category="VEMA Auto-Reorders",
        title=f"Reorder Proposal Approved — {req['request_code']}",
        description=description,
        metadata={"request_id": request_id, "order_id": order_result["order_id"]},
    )

    return {
        "message": f"Request {req['request_code']} approved. {approve_result['message']}",
        "order_id": order_result["order_id"],
        "order_code": order_result["order_code"],
        "vendor_email_status": email_status,
    }


class RejectRequestBody(BaseModel):
    reason: str


@router.post("/vema-requests/{request_id}/reject", dependencies=[_approver])
def reject_vema_request(
    request_id: str, body: RejectRequestBody,
    user: dict = Depends(get_current_user), db: Session = Depends(get_db),
):
    req = _get_request(db, request_id)
    if req["status"] != "pending_approval":
        raise HTTPException(409, f"Request is not pending approval (status: {req['status']})")
    if not body.reason or not body.reason.strip():
        raise HTTPException(422, "A reason is required to reject a reorder proposal")

    db.execute(
        text("""
            UPDATE vema_reorder_requests SET
              status = 'rejected', decided_by = :uid, decided_at = NOW(),
              decision_note = :note, updated_at = NOW()
            WHERE id = :id
        """),
        {"uid": user["id"], "note": body.reason, "id": request_id},
    )
    db.execute(
        text("""
            INSERT INTO vema_reorder_audit_log (id, request_id, action, actor_id, note)
            VALUES (:id, :rid, 'rejected', :uid, :note)
        """),
        {"id": str(uuid.uuid4()), "rid": request_id, "uid": user["id"], "note": body.reason},
    )
    db.commit()

    _notify_other_approvers(
        db, user["role"],
        category="VEMA Auto-Reorders",
        title=f"Reorder Proposal Rejected — {req['request_code']}",
        description=f"{req['item_name']}: {body.reason}",
        metadata={"request_id": request_id, "item_id": req["item_id"]},
    )

    return {"message": f"Request {req['request_code']} rejected."}
