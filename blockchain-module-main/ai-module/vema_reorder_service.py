"""
NEXUS ERP — VEMA Auto-Reorder Service

Deterministic stock-scan -> proposal pipeline, additive and parallel to the
existing <=20%-of-min_threshold auto-trigger (inventory_v2.run_inventory_check
-> procurement.create_pending_approval_order — see that function's docstring
and procurement.py's "AUTOMATED REORDERING" section). That flow is untouched.

This one proposes BEFORE any order exists: scan_and_create_requests() writes
a vema_reorder_requests row (status='pending_approval') with a deterministic
quantity, a ranked vendor + alternatives, and a plain-English rationale. A
Procurement Manager or Admin reviews and decides via vema_reorder_router.py's
/approve or /reject — only on approve does a real procurement_orders row get
created, reusing procurement.create_pending_approval_order() +
procurement.approve_reorder() exactly as they are (see approve_request()
below) — never duplicated.

Quantity, vendor ranking, and the deterministic rationale fallback are ALL
plain arithmetic — no LLM involved in any number a Procurement Manager acts
on. The LLM (see llm_client.py — Gemini primary) is used ONLY to phrase an
already-decided set of numbers into readable prose; chat_text() never
raises and a canned template is used whenever it's unavailable or fails.
"""
import json
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from llm_client import chat_text, is_available as llm_available

# ---------------------------------------------------------------------------
# Config — all overridable via env, per the task's own requirement that
# threshold/cooldown/expiry/approver-roles be easy to change without a
# code change. See docs/VEMA_AUTO_REORDER.md "Configuration".
# ---------------------------------------------------------------------------
VEMA_REORDER_THRESHOLD_PCT = float(os.getenv("VEMA_REORDER_THRESHOLD_PCT", "20"))
VEMA_REORDER_COOLDOWN_HOURS = float(os.getenv("VEMA_REORDER_COOLDOWN_HOURS", "24"))
VEMA_REORDER_EXPIRY_HOURS = float(os.getenv("VEMA_REORDER_EXPIRY_HOURS", "72"))

# Vendor ranking weights — a simple, disclosed heuristic (no historical
# delivery-performance data exists anywhere in this schema to add a fourth
# signal; see docs/VEMA_AUTO_REORDER.md "Known limitations"). Must sum to 1.
_WEIGHT_PRICE = 0.4
_WEIGHT_LEAD_TIME = 0.3
_WEIGHT_ACCEPT_RATE = 0.3

# Orders in any of these procurement_orders.stage values are "still in
# progress" for dedup purposes — matches run_inventory_check()'s own
# open_set definition (stage NOT IN ('Delivered','Cancelled')) plus the two
# approval-gate-specific terminal stages it predates.
_OPEN_ORDER_STAGES_EXCLUDED = ("Delivered", "Cancelled", "Cancelled by PM", "Vendor Rejected")


# ---------------------------------------------------------------------------
# Request code
# ---------------------------------------------------------------------------

def _next_request_code(db: Session) -> str:
    """VRO-<year>-<seq>, sequential per year. Matches complaints.py's
    VEMA-<CODE>-<date>-<seq> idiom (human-readable, sortable) but yearly
    rather than daily since reorder volume is much lower than complaints."""
    year = datetime.now(timezone.utc).strftime("%Y")
    prefix = f"VRO-{year}-"
    count = db.execute(
        text("SELECT COUNT(*) FROM vema_reorder_requests WHERE request_code LIKE :p"),
        {"p": f"{prefix}%"},
    ).scalar() or 0
    return f"{prefix}{count + 1:04d}"


# ---------------------------------------------------------------------------
# Quantity
# ---------------------------------------------------------------------------

def _resolve_par_level(item: dict) -> int:
    """max_stock_level if set, else min_threshold * 2 — the same dummy-
    forecast multiplier inventory_v2.calculate_prediction() already uses
    when no trained model is loaded, so an unconfigured item still gets a
    reasonable, consistent-with-existing-conventions target."""
    par = item.get("max_stock_level")
    if par:
        return int(par)
    return int(item.get("min_threshold") or 0) * 2


def _inbound_qty(db: Session, item_id: str) -> float:
    """Quantity already on order (any non-terminal procurement_orders row)
    for this item — subtracted so an item with stock already inbound isn't
    double-ordered."""
    row = db.execute(
        text(f"""
            SELECT COALESCE(SUM(quantity), 0) FROM procurement_orders
            WHERE item_id = :id AND stage NOT IN {_OPEN_ORDER_STAGES_EXCLUDED}
        """),
        {"id": item_id},
    ).scalar()
    return float(row or 0)


def _forecast_demand(item: dict) -> float:
    """Reads inventory_v2's existing prediction function read-only — never
    reimplemented. Returns 0 (forecast term skipped) if the import/call
    itself fails for any reason, per the task's "if unavailable, skip the
    forecast term" instruction. calculate_prediction() itself never raises
    in normal operation (it has its own MODEL_LOADED dummy fallback) — this
    guards only against something unexpected like the saved model files
    being missing/corrupt mid-call."""
    try:
        from inventory_v2 import calculate_prediction
        return float(calculate_prediction(
            item.get("category", "Operational"),
            float(item.get("current_stock", 0)),
            int(item.get("min_threshold") or 0),
        ))
    except Exception as e:
        print(f"[WARN] vema_reorder_service: forecast unavailable ({e}), skipping forecast term")
        return 0.0


def _compute_quantity(db: Session, item: dict, par_level: int, vendor_moq: Optional[float]) -> int:
    """qty = par_level - current_stock - inbound + forecast_demand, floored
    at 1 and raised to the vendor's MOQ if one applies and would otherwise
    be violated. Every input is a real number from the DB or the existing
    forecast service — nothing here is LLM-generated."""
    current_stock = float(item.get("current_stock", 0))
    inbound = _inbound_qty(db, item["item_id"])
    forecast = _forecast_demand(item)
    qty = par_level - current_stock - inbound + forecast
    qty = max(1, round(qty))
    if vendor_moq and qty < vendor_moq:
        qty = int(round(vendor_moq))
    return qty


# ---------------------------------------------------------------------------
# Vendor ranking
# ---------------------------------------------------------------------------

def _vendor_accept_rate(db: Session, vendor_id: str) -> Optional[float]:
    """Fraction of this vendor's past orders they accepted (vendor_decision
    on procurement_orders) — the only historical "performance" signal that
    actually exists anywhere in this schema (confirmed: no rating/on-time/
    delivery-performance column exists on vendors, vendor_items, or
    vendor_orders). Returns None (treated as neutral) if this vendor has no
    decided history yet, so a brand-new vendor isn't penalized for having
    no track record."""
    row = db.execute(
        text("""
            SELECT COUNT(*) FILTER (WHERE vendor_decision = 'Accepted') AS accepted,
                   COUNT(*) FILTER (WHERE vendor_decision IS NOT NULL) AS decided
            FROM procurement_orders WHERE vendor_id = :vid
        """),
        {"vid": vendor_id},
    ).mappings().first()
    if not row or not row["decided"]:
        return None
    return float(row["accepted"]) / float(row["decided"])


def _normalize(value: float, lo: float, hi: float) -> float:
    """0..1, higher is better, for a "lower raw value is better" metric
    (price, lead time). Flat 1.0 when every candidate ties."""
    if hi <= lo:
        return 1.0
    return max(0.0, min(1.0, 1.0 - (value - lo) / (hi - lo)))


def _rank_vendors(db: Session, item: dict) -> tuple[Optional[dict], list[dict], dict]:
    """
    Returns (best_candidate_or_None, other_candidates, score_breakdown).
    Each candidate: {vendor_id, vendor_name, vendor_email, unit_price,
    lead_time_days, moq, accept_rate, score}.

    Candidates are the union of:
      (a) active (status='active') vendors with a matching vendor_items row
          (category, case-insensitive, matches this item's category) — the
          Phase 1 vendor-onboarding catalogue, which has real price/MOQ/
          lead-time data per vendor.
      (b) this item's own directly-assigned vendor (inventory_items.vendor_id),
          if still active — the original seed-data linkage, which predates
          vendor_items and has no catalogue row of its own; its price comes
          from the item's own unit_price and its lead time defaults to 14
          days (matching procurement.create_order's own default delivery
          window) since no vendor_items.lead_time_days exists for it.
    This keeps every pre-existing item orderable even though most seed
    vendors (Siemens, ABB, ...) were never given a vendor_items catalogue.
    """
    candidates: dict[str, dict] = {}

    rows = db.execute(
        text("""
            SELECT v.id AS vendor_id, v.name AS vendor_name, v.email AS vendor_email,
                   vi.unit_price, vi.lead_time_days, vi.moq, vi.category
            FROM vendor_items vi
            JOIN vendors v ON v.id = vi.vendor_id
            WHERE v.status = 'active' AND vi.is_active = TRUE
        """)
    ).mappings().all()
    item_category = (item.get("category") or "").strip().lower()
    for r in rows:
        if (r["category"] or "").strip().lower() != item_category:
            continue
        candidates[str(r["vendor_id"])] = {
            "vendor_id": str(r["vendor_id"]), "vendor_name": r["vendor_name"], "vendor_email": r["vendor_email"],
            "unit_price": float(r["unit_price"]), "lead_time_days": r["lead_time_days"] or 14,
            "moq": float(r["moq"]) if r["moq"] else None,
        }

    if item.get("vendor_id"):
        row = db.execute(
            text("SELECT id, name, email FROM vendors WHERE id = :id AND status = 'active'"),
            {"id": item["vendor_id"]},
        ).mappings().first()
        if row and str(row["id"]) not in candidates and item.get("unit_price") is not None:
            candidates[str(row["id"])] = {
                "vendor_id": str(row["id"]), "vendor_name": row["name"], "vendor_email": row["email"],
                "unit_price": float(item["unit_price"]), "lead_time_days": 14, "moq": None,
            }

    if not candidates:
        return None, [], {}

    prices = [c["unit_price"] for c in candidates.values()]
    lead_times = [c["lead_time_days"] for c in candidates.values()]
    price_lo, price_hi = min(prices), max(prices)
    lt_lo, lt_hi = min(lead_times), max(lead_times)

    scored = []
    for c in candidates.values():
        accept_rate = _vendor_accept_rate(db, c["vendor_id"])
        accept_score = accept_rate if accept_rate is not None else 0.5  # neutral — no history yet
        price_score = _normalize(c["unit_price"], price_lo, price_hi)
        lead_time_score = _normalize(c["lead_time_days"], lt_lo, lt_hi)
        score = round(
            _WEIGHT_PRICE * price_score + _WEIGHT_LEAD_TIME * lead_time_score + _WEIGHT_ACCEPT_RATE * accept_score, 4
        )
        scored.append({
            **c, "accept_rate": accept_rate, "price_score": round(price_score, 3),
            "lead_time_score": round(lead_time_score, 3), "score": score,
        })

    # When several vendors clash for the same item, the lowest unit price
    # wins; the weighted score above only breaks a price tie.
    scored.sort(key=lambda c: (c["unit_price"], -c["score"]))
    breakdown = {c["vendor_id"]: c for c in scored}
    return scored[0], scored[1:], breakdown


# ---------------------------------------------------------------------------
# Rationale
# ---------------------------------------------------------------------------

_RATIONALE_SYSTEM_PROMPT = """You are VEMA, the automated reorder assistant
for a Pakistani electricity utility's procurement team. You're given the
already-decided numbers behind a reorder proposal — turn them into a clear,
confident 2-3 sentence plain-English explanation for a Procurement Manager
who will approve or reject it. Do not invent any numbers not given to you,
and do not change the recommendation — you are only phrasing it."""


def _rationale_fallback(item: dict, stock_pct: float, qty: int, vendor: Optional[dict]) -> str:
    vendor_part = (
        f"Recommended vendor: {vendor['vendor_name']} (score {vendor['score']:.2f}, "
        f"PKR {vendor['unit_price']:,.2f}/unit, ~{vendor['lead_time_days']}-day lead time)."
        if vendor else
        "No eligible vendor was found — please choose one manually before approving."
    )
    return (
        f"{item['name']} stock is at {stock_pct:.0f}% of its target level "
        f"({item.get('current_stock')} {item.get('unit', 'units')}). "
        f"Suggested reorder quantity: {qty} {item.get('unit', 'units')}. {vendor_part}"
    )


def _generate_rationale(item: dict, stock_pct: float, qty: int, vendor: Optional[dict]) -> str:
    """LLM phrasing only — every number it could reference is already fixed
    before this call; never blocks or changes the proposal if unavailable."""
    fallback = _rationale_fallback(item, stock_pct, qty, vendor)
    if not llm_available():
        return fallback
    if vendor:
        accept_rate_str = "n/a" if vendor["accept_rate"] is None else f"{vendor['accept_rate']:.0%}"
        vendor_desc = (
            f"{vendor['vendor_name']}, score {vendor['score']:.2f} (price PKR {vendor['unit_price']:,.2f}, "
            f"lead time {vendor['lead_time_days']} days, accept rate {accept_rate_str})"
        )
    else:
        vendor_desc = "none found"
    user_message = (
        f"Item: {item['name']} ({item.get('category')})\n"
        f"Current stock: {item.get('current_stock')} {item.get('unit', 'units')} "
        f"({stock_pct:.0f}% of target level)\n"
        f"Suggested quantity: {qty} {item.get('unit', 'units')}\n"
        f"Chosen vendor: {vendor_desc}"
    )
    result = chat_text(_RATIONALE_SYSTEM_PROMPT, user_message, temperature=0.3)
    return result or fallback


# ---------------------------------------------------------------------------
# Dedup
# ---------------------------------------------------------------------------

def _is_duplicate_or_cooling_down(db: Session, item_id: str) -> bool:
    """True if this item already has a pending VEMA request, an open
    procurement order (either system's — the existing <=20% auto-trigger
    and plain manual orders both write procurement_orders directly, so
    dedup has to look there too, not just this module's own table), or was
    rejected within the cooldown window."""
    pending = db.execute(
        text("SELECT 1 FROM vema_reorder_requests WHERE item_id = :id AND status = 'pending_approval' LIMIT 1"),
        {"id": item_id},
    ).first()
    if pending:
        return True

    open_order = db.execute(
        text(f"""
            SELECT 1 FROM procurement_orders
            WHERE item_id = :id AND stage NOT IN {_OPEN_ORDER_STAGES_EXCLUDED} LIMIT 1
        """),
        {"id": item_id},
    ).first()
    if open_order:
        return True

    cooling_down = db.execute(
        text("""
            SELECT 1 FROM vema_reorder_requests
            WHERE item_id = :id AND status = 'rejected'
              AND decided_at > NOW() - (:hours * INTERVAL '1 hour')
            LIMIT 1
        """),
        {"id": item_id, "hours": VEMA_REORDER_COOLDOWN_HOURS},
    ).first()
    return bool(cooling_down)


# ---------------------------------------------------------------------------
# Scan entry point
# ---------------------------------------------------------------------------

def scan_and_create_requests(db: Session) -> list[dict]:
    """
    One item at a time, never let one bad item abort the scan (per the
    repo-wide defensive-scan convention — see complaints.py/rag/ingest.py
    for the same pattern). Called both from inventory_v2's existing scan/
    stock-update paths and from the scheduled job in reminder_scheduler.py.
    """
    rows = db.execute(text("SELECT * FROM inventory_items")).mappings().all()
    created = []
    for row in rows:
        item = dict(row)
        try:
            result = _create_request_for_item(db, item)
            if result:
                created.append(result)
        except Exception as e:
            print(f"[WARN] vema_reorder_service: skipping {item.get('item_id')} ({e})")
            db.rollback()
    return created


def _create_request_for_item(db: Session, item: dict) -> Optional[dict]:
    current_stock = float(item.get("current_stock", 0))
    par_level = _resolve_par_level(item)
    if par_level <= 0:
        return None
    threshold_qty = par_level * (VEMA_REORDER_THRESHOLD_PCT / 100.0)
    if current_stock > threshold_qty:
        return None
    if _is_duplicate_or_cooling_down(db, item["item_id"]):
        return None

    vendor, alt_vendors, breakdown = _rank_vendors(db, item)
    qty = _compute_quantity(db, item, par_level, vendor["moq"] if vendor else None)
    unit_price_est = vendor["unit_price"] if vendor else item.get("unit_price")
    total_est = round(qty * float(unit_price_est), 2) if unit_price_est is not None else None
    stock_pct = round((current_stock / par_level) * 100, 1) if par_level else 0.0
    rationale = _generate_rationale(item, stock_pct, qty, vendor)

    request_id = str(uuid.uuid4())
    request_code = _next_request_code(db)
    db.execute(
        text("""
            INSERT INTO vema_reorder_requests (
              id, request_code, item_id, stock_at_trigger, par_level, threshold_pct,
              suggested_qty, unit_price_est, total_est, vendor_id,
              alt_vendor_ids, vendor_score_breakdown, rationale, status
            ) VALUES (
              :id, :code, :item_id, :stock, :par, :threshold,
              :qty, :price, :total, :vendor_id,
              CAST(:alt AS jsonb), CAST(:breakdown AS jsonb), :rationale, 'pending_approval'
            )
        """),
        {
            "id": request_id, "code": request_code, "item_id": item["item_id"],
            "stock": current_stock, "par": par_level, "threshold": VEMA_REORDER_THRESHOLD_PCT,
            "qty": qty, "price": unit_price_est, "total": total_est,
            "vendor_id": vendor["vendor_id"] if vendor else None,
            "alt": json.dumps([v["vendor_id"] for v in alt_vendors]),
            "breakdown": json.dumps(breakdown), "rationale": rationale,
        },
    )
    db.execute(
        text("""
            INSERT INTO vema_reorder_audit_log (id, request_id, action, note)
            VALUES (:id, :rid, 'created', :note)
        """),
        {
            "id": str(uuid.uuid4()), "rid": request_id,
            "note": f"Triggered: stock {current_stock} <= {VEMA_REORDER_THRESHOLD_PCT:.0f}% of par ({par_level}).",
        },
    )
    db.commit()

    from notification_service import notify_role
    from rbac import ROLE_PROCUREMENT_MANAGER
    try:
        notify_role(
            db, ROLE_PROCUREMENT_MANAGER,
            category="VEMA Auto-Reorders",
            title=f"Reorder Proposal — {item['name']} ({request_code})",
            description=rationale,
            metadata={"request_id": request_id, "request_code": request_code, "item_id": item["item_id"]},
        )
    except Exception as e:
        print(f"[WARN] vema_reorder_service: notify failed ({e})")

    return {"request_id": request_id, "request_code": request_code, "item_id": item["item_id"], "suggested_qty": qty}


def expire_stale_requests(db: Session) -> int:
    """Pending requests older than VEMA_REORDER_EXPIRY_HOURS become
    'expired' and notify approvers once. Never fails the caller — any
    error here is logged and swallowed, consistent with every other
    scheduled job in reminder_scheduler.py."""
    rows = db.execute(
        text("""
            SELECT id, request_code, item_id FROM vema_reorder_requests
            WHERE status = 'pending_approval'
              AND created_at < NOW() - (:hours * INTERVAL '1 hour')
        """),
        {"hours": VEMA_REORDER_EXPIRY_HOURS},
    ).mappings().all()
    if not rows:
        return 0

    from notification_service import notify_role
    from rbac import ROLE_PROCUREMENT_MANAGER
    for r in rows:
        db.execute(
            text("UPDATE vema_reorder_requests SET status = 'expired', updated_at = NOW() WHERE id = :id"),
            {"id": r["id"]},
        )
        db.execute(
            text("INSERT INTO vema_reorder_audit_log (id, request_id, action) VALUES (:id, :rid, 'expired')"),
            {"id": str(uuid.uuid4()), "rid": r["id"]},
        )
        db.commit()
        try:
            notify_role(
                db, ROLE_PROCUREMENT_MANAGER,
                category="VEMA Auto-Reorders",
                title=f"Reorder Proposal Expired — {r['request_code']}",
                description=f"No decision was made within {VEMA_REORDER_EXPIRY_HOURS:.0f}h; it will be re-proposed if stock is still low.",
                metadata={"request_id": str(r["id"]), "item_id": r["item_id"]},
            )
        except Exception as e:
            print(f"[WARN] vema_reorder_service: expiry notify failed ({e})")
    return len(rows)
