"""
NEXUS ERP — Inventory Router (Module 2 — DB-connected)
Replaces the JSON-file based inventory_engine with PostgreSQL.
"""
import uuid, json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy import text

from database import get_db, SessionLocal
from notification_service import notify_stock_low
from stock_thresholds import stock_status, STATUS_CRITICAL, STATUS_LOW, STATUS_OK
from rbac import require_role, ROLE_PROCUREMENT_MANAGER

router = APIRouter(prefix="/api/inventory", tags=["Inventory"])
_pm_read = Depends(require_role(ROLE_PROCUREMENT_MANAGER))
_admin_only = Depends(require_role())


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _compute_status(stock: float, min_t: int, crit_t: int = None) -> str:
    """Critical < 21% <= Low < 36% <= OK, as a % of min_threshold — see
    stock_thresholds.py. crit_t is no longer used for labelling (kept so
    existing callers don't change), only for days_until_critical."""
    return stock_status(stock, min_t)


import joblib, numpy as np, os

# Load prediction model
current_dir = os.path.dirname(os.path.abspath(__file__))
BASE = os.path.join(current_dir, "models", "saved")
try:
    pred_model     = joblib.load(f"{BASE}/inventory_model.pkl")
    le_category    = joblib.load(f"{BASE}/le_category.pkl")
    le_region      = joblib.load(f"{BASE}/le_region.pkl")
    le_weather     = joblib.load(f"{BASE}/le_weather.pkl")
    le_seasonality = joblib.load(f"{BASE}/le_seasonality.pkl")
    MODEL_LOADED = True
except Exception:
    MODEL_LOADED = False

def safe_encode(encoder, value, default=0):
    try:
        return int(encoder.transform([value])[0])
    except:
        return default

def calculate_prediction(category: str, current_stock: float, min_thresh: int) -> int:
    if MODEL_LOADED:
        features = np.array([[
            safe_encode(le_category, category),
            safe_encode(le_region, "North"), # Default
            safe_encode(le_weather, "Clear"),
            safe_encode(le_seasonality, "Spring"),
            current_stock,
            50, # Units Sold dummy
            50, # Units Ordered dummy
            100.0, # Price dummy
            0.0, # Discount
            0, # Promotion
            100.0, # Competitor Pricing
            0, # Epidemic
            min_thresh,
            datetime.now().month,
            datetime.now().weekday()
        ]])
        return max(1, round(float(pred_model.predict(features)[0])))
    else:
        return int(min_thresh * 2) if current_stock < min_thresh else int(current_stock * 0.9)


def _enrich_item(row: dict) -> dict:
    """Add computed fields to an inventory row."""
    s  = float(row.get("current_stock", 0))
    mn = int(row.get("min_threshold", 0))
    dc = float(row.get("daily_consumption", 1))
    cr = int(row.get("critical_threshold", 0))
    cat = row.get("category", "Operational")
    row["status"]               = _compute_status(s, mn, cr)
    row["days_until_reorder"]   = max(0, round((s - mn)  / dc)) if dc > 0 and s > mn else 0
    row["days_until_critical"]  = max(0, round((s - cr)  / dc)) if dc > 0 and s > cr else 0
    row["stock_pct"]            = round((s / mn) * 100, 1) if mn > 0 else 100
    row["category"]             = cat
    row["predicted_demand"]     = calculate_prediction(cat, s, mn)
    return row


# ────────────────────────────────────────────────────────────────────────────
# GET /overview
# ────────────────────────────────────────────────────────────────────────────

@router.get("/overview", dependencies=[_pm_read])
def inventory_overview(db: Session = Depends(get_db)):
    rows = db.execute(
        text("""
            SELECT i.*, v.name AS vendor_name, v.email AS vendor_email
            FROM inventory_items i
            LEFT JOIN vendors v ON v.id = i.vendor_id
            ORDER BY i.item_id
        """)
    ).mappings().all()

    items = [_enrich_item(dict(r)) for r in rows]
    summary = {
        "total_items": len(items),
        "ok":       sum(1 for x in items if x["status"] == "OK"),
        "low":      sum(1 for x in items if x["status"] == "Low"),
        "critical": sum(1 for x in items if x["status"] == "Critical"),
        # Subset of "critical" (0% is labelled Critical), shown separately.
        "out_of_stock": sum(1 for x in items if float(x["current_stock"]) <= 0),
        "predicted_demand": sum(x.get("predicted_demand", 0) for x in items),
    }
    return {"summary": summary, "items": items, "timestamp": datetime.utcnow().isoformat()}


# ────────────────────────────────────────────────────────────────────────────
# GET /item/{item_id}
# ────────────────────────────────────────────────────────────────────────────

@router.get("/item/{item_id}", dependencies=[_pm_read])
def get_item(item_id: str, db: Session = Depends(get_db)):
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
    return _enrich_item(dict(row))


# ────────────────────────────────────────────────────────────────────────────
# Reorder triggering — shared by POST /check and the startup critical-stock run
# ────────────────────────────────────────────────────────────────────────────

def _inventory_rows(db: Session):
    return db.execute(
        text("""
            SELECT i.*, v.name AS vendor_name, v.email AS vendor_email
            FROM inventory_items i
            LEFT JOIN vendors v ON v.id = i.vendor_id
        """)
    ).mappings().all()


def _open_order_item_ids(db: Session) -> set:
    """Items that already have an open (non-Delivered) order — never
    reordered again, so neither a re-scan nor a restart duplicates one."""
    return set(db.execute(
        text("""
            SELECT item_id FROM procurement_orders
            WHERE stage NOT IN ('Delivered', 'Cancelled')
        """)
    ).scalars().all())


def _reorder_trigger(item: dict):
    """(trigger_type, reason) for an enriched item, or (None, None)."""
    if item["status"] == STATUS_CRITICAL:
        # Checked first so a Critical item keeps its Critical trigger type
        # even if the demand heuristic below would also fire.
        return "VEMA-Triggered", "stock below 21% of min_threshold"
    if item["current_stock"] < item.get("predicted_demand", 0):
        return "Auto-Generated (Demand > Stock)", "predicted demand exceeds stock"
    if item["status"] == STATUS_LOW:
        return "Auto-Generated", "stock between 21% and 35% of min_threshold"
    return None, None


def _safe_notify(fn, *args, **kwargs):
    """Notifications never abort a scan."""
    try:
        fn(*args, **kwargs)
    except Exception as e:
        print(f"[WARN] Reorder notification failed: {e}")


def _insert_shortage_notification(db: Session, item: dict):
    db.execute(text("""
        INSERT INTO notifications (user_id, category, title, description, created_at)
        VALUES (NULL, 'Updates', :title, :desc, NOW())
    """), {
        "title": f"Predicted Shortage: {item['name']}",
        "desc":  f"Predicted demand ({item['predicted_demand']} {item.get('unit', 'units')}) exceeds current stock ({item['current_stock']} {item.get('unit', 'units')}). Reorder created and awaiting approval."
    })
    db.commit()


def _trigger_reorder(db: Session, item: dict, trigger: str, reason: str) -> dict:
    """Every auto trigger — the smart contract is created immediately, but
    the vendor is NOT emailed until an Admin / Procurement Manager approves
    it (both roles are notified). See N8N_AUTOMATION_WIRING.md."""
    from procurement import create_pending_approval_order
    return create_pending_approval_order(db, item, trigger_type=trigger, reason=reason,
                                         pick_lowest_price_vendor=True)


# ────────────────────────────────────────────────────────────────────────────
# POST /check — scan all items and auto-generate orders for Low/Critical
# ────────────────────────────────────────────────────────────────────────────

@router.post("/check", dependencies=[_pm_read])
def run_inventory_check(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger inventory scan. For each Low/Critical/predicted-shortage item
    without an open order, create a reorder that waits for Admin /
    Procurement Manager approval before the vendor is emailed. The order
    goes to the vendor with the lowest unit price for the item (see
    procurement.select_lowest_price_vendor).
    """
    open_set = _open_order_item_ids(db)

    created, skipped, errors = [], [], []
    for r in _inventory_rows(db):
        item_id = r["item_id"]
        try:
            item = _enrich_item(dict(r))
            if item_id in open_set:
                continue
            trigger, reason = _reorder_trigger(item)
            if not trigger:
                continue

            if trigger == "Auto-Generated (Demand > Stock)":
                _safe_notify(_insert_shortage_notification, db, item)
            elif trigger == "Auto-Generated":
                background_tasks.add_task(
                    _safe_notify, notify_stock_low, db,
                    item["name"], item["current_stock"], item["item_id"]
                )

            result = _trigger_reorder(db, item, trigger, reason)
            (skipped if result.get("skipped") else created).append(result)
        except Exception as e:
            db.rollback()
            print(f"[ERROR] Inventory check failed for {item_id}: {e}")
            errors.append({"item_id": item_id, "error": str(e)})

    # VEMA auto-reorder scan (additive, parallel system — see
    # vema_reorder_service.py). Runs after the existing per-item loop above
    # so it never interferes with it; its own dedup checks procurement_orders
    # too, so an item this loop just created an order for is skipped.
    vema_requests = []
    try:
        import vema_reorder_service
        vema_requests = vema_reorder_service.scan_and_create_requests(db)
    except Exception as e:
        print(f"[WARN] inventory_v2: VEMA auto-reorder scan failed ({e})")

    return {
        "message":       f"{len(created)} new orders awaiting approval",
        "new_orders":    created,
        "skipped":       skipped,
        "errors":        errors,
        "vema_requests": vema_requests,
        "timestamp":     datetime.utcnow().isoformat(),
    }


def reorder_critical_items_on_startup() -> dict:
    """
    Run at backend startup (main.py): trigger the same reorder as
    POST /check, but only for items currently labelled Critical. Items that
    already have an open order are skipped, so restarting never duplicates
    an approval. Never raises — one bad item can't stop the rest, and a
    failure here can't stop the server from booting.
    """
    counts = {"critical": 0, "created": 0, "skipped_pending": 0, "skipped_no_vendor": 0, "errors": 0}
    db = SessionLocal()
    try:
        open_set = _open_order_item_ids(db)
        for r in _inventory_rows(db):
            item_id = r["item_id"]
            try:
                if stock_status(r["current_stock"], r["min_threshold"]) != STATUS_CRITICAL:
                    continue
                counts["critical"] += 1
                if item_id in open_set:
                    counts["skipped_pending"] += 1
                    print(f"[Startup reorder] {item_id} skipped — already has an open order")
                    continue
                item = _enrich_item(dict(r))
                result = _trigger_reorder(db, item, "VEMA-Triggered", "stock below 21% of min_threshold (startup check)")
                if result.get("skipped"):
                    counts["skipped_no_vendor"] += 1
                    print(f"[Startup reorder] {item_id} skipped — {result.get('reason')}")
                else:
                    counts["created"] += 1
                    open_set.add(item_id)
                    print(f"[Startup reorder] {item_id} -> {result['order_code']} awaiting approval ({result.get('vendor_name')})")
            except Exception as e:
                db.rollback()
                counts["errors"] += 1
                print(f"[ERROR] Startup reorder failed for {item_id}: {e}")
    except Exception as e:
        counts["errors"] += 1
        print(f"[ERROR] Startup reorder check aborted: {e}")
    finally:
        db.close()

    print(
        f"Startup re-order check: {counts['critical']} critical items, "
        f"{counts['created']} approvals created, "
        f"{counts['skipped_pending']} skipped (already pending), "
        f"{counts['skipped_no_vendor']} skipped (no vendor), "
        f"{counts['errors']} errors"
    )
    return counts


# ────────────────────────────────────────────────────────────────────────────
# PUT /item/{item_id}/stock — update stock level (e.g. after manual count)
# ────────────────────────────────────────────────────────────────────────────

class StockUpdateRequest(BaseModel):
    current_stock: float
    notes:         Optional[str] = None


@router.put("/item/{item_id}/stock", dependencies=[_admin_only])
def update_stock(item_id: str, req: StockUpdateRequest, db: Session = Depends(get_db)):
    row = db.execute(
        text("SELECT * FROM inventory_items WHERE item_id=:id"), {"id": item_id}
    ).mappings().first()
    if not row:
        raise HTTPException(404, f"Item {item_id} not found")

    item = dict(row)
    new_status = _compute_status(
        req.current_stock, item["min_threshold"], item["critical_threshold"]
    )
    db.execute(
        text("""
            UPDATE inventory_items
            SET current_stock=:s, status=:st, last_updated=NOW()
            WHERE item_id=:id
        """),
        {"s": req.current_stock, "st": new_status, "id": item_id},
    )
    db.commit()

    # VEMA auto-reorder scan — see run_inventory_check()'s equivalent hook
    # for why this is additive/non-blocking. Scans every item (cheap at this
    # catalogue's size) rather than just this one, since scan_and_create_requests
    # already does its own per-item dedup/threshold check.
    try:
        import vema_reorder_service
        vema_reorder_service.scan_and_create_requests(db)
    except Exception as e:
        print(f"[WARN] inventory_v2: VEMA auto-reorder scan failed ({e})")

    return {"item_id": item_id, "new_stock": req.current_stock, "status": new_status}


# ────────────────────────────────────────────────────────────────────────────
# POST /predict-inventory — read all DB items and run the prediction model
# ────────────────────────────────────────────────────────────────────────────

@router.post("/predict-inventory", dependencies=[_pm_read])
def batch_predict_inventory(db: Session = Depends(get_db)):
    """
    Reads all inventory items from the database and runs them through the 
    prediction model to output demand forecasts.
    """
    from api.routes.predict import predict_demand, PredictionRequest

    rows = db.execute(
        text("SELECT * FROM inventory_items")
    ).mappings().all()

    results = []
    current_date = datetime.utcnow().strftime("%Y-%m-%d")

    print(f"--- Starting Batch Prediction Pipeline for {len(rows)} items ---")

    for r in rows:
        item = dict(r)
        
        # Prepare the PredictionRequest payload using DB data and some dummy defaults
        req = PredictionRequest(
            Date=current_date,
            Store_ID="S001",
            Product_ID=item["item_id"],
            Category=item.get("category", "Operational"),
            Region="North",
            Inventory_Level=int(item["current_stock"]),
            Units_Sold=10,
            Units_Ordered=5,
            Price=100.0,
            Discount=0.0,
            Weather_Condition="Clear",
            Promotion=0,
            Competitor_Pricing=95.0,
            Seasonality="Winter",
            Epidemic=0
        )
        
        # Call the existing prediction function
        try:
            pred_res = predict_demand(req)
            result = {
                "item_id": item["item_id"],
                "name": item["name"],
                "category": item.get("category", "Operational"),
                "prediction": pred_res
            }
            results.append(result)
            print(f"[Prediction] {item['item_id']} ({item['name']}): Demand Forecast -> {pred_res['predicted_demand']} units. Status -> {pred_res['status']}")
        except Exception as e:
            print(f"[Error] Predicting for {item['item_id']}: {str(e)}")

    print(f"--- Finished Prediction Pipeline ---")

    return {
        "message": f"Successfully ran predictions for {len(results)} items.",
        "results": results
    }


# ────────────────────────────────────────────────────────────────────────────
# GET /demand-forecast — forecast per-item demand on a specific date
# ────────────────────────────────────────────────────────────────────────────

@router.get("/demand-forecast", dependencies=[_pm_read])
def get_demand_forecast(date: Optional[str] = None, db: Session = Depends(get_db)):
    """
    Runs each inventory item through the prediction model for a given date.
    Returns per-item demand predictions and flags whether reorders are needed.
    """
    target_date_str = date or datetime.utcnow().strftime("%Y-%m-%d")
    try:
        dt = datetime.strptime(target_date_str, "%Y-%m-%d")
    except Exception:
        dt = datetime.utcnow()
        target_date_str = dt.strftime("%Y-%m-%d")

    month = dt.month
    season = "Winter" if month in [12, 1, 2] else "Spring" if month in [3, 4, 5] else "Summer" if month in [6, 7, 8] else "Autumn"

    rows = db.execute(
        text("SELECT * FROM inventory_items ORDER BY item_id ASC")
    ).mappings().all()

    items_out = []
    total_predicted = 0

    for r in rows:
        item = dict(r)
        stock = float(item["current_stock"])
        min_t = int(item["min_threshold"])
        cat = item.get("category", "Operational")

        # Run prediction
        pred_demand = calculate_prediction(cat, stock, min_t)
        total_predicted += pred_demand

        # Compute anticipated status — reorder if the item is Low/Critical
        # now, or would drop to Critical after the predicted demand.
        post_stock = max(0, stock - pred_demand)
        st = _compute_status(stock, min_t)
        post_st = _compute_status(post_stock, min_t)
        reorder_needed = st != STATUS_OK or post_st == STATUS_CRITICAL
        trigger_type = "VEMA-Triggered" if (st == STATUS_CRITICAL or post_stock <= 0) else "Auto-Generated" if reorder_needed else "None"
        reorder_qty = int(item["reorder_quantity"]) if reorder_needed else 0

        items_out.append({
            "item_id": item["item_id"],
            "name": item["name"],
            "unit": item["unit"],
            "category": cat,
            "current_stock": stock,
            "predicted_demand": pred_demand,
            "status": st,
            "reorder_needed": reorder_needed,
            "reorder_quantity": reorder_qty,
            "trigger_type": trigger_type,
        })

    return {
        "date": target_date_str,
        "season": season,
        "model_loaded": MODEL_LOADED,
        "total_predicted_demand": total_predicted,
        "items": items_out,
        "generated_at": datetime.utcnow().isoformat() + "Z"
    }

