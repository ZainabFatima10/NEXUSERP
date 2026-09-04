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

from database import get_db
from notification_service import notify_stock_low
from rbac import require_role, ROLE_PROCUREMENT_MANAGER

router = APIRouter(prefix="/api/inventory", tags=["Inventory"])
_pm_read = Depends(require_role(ROLE_PROCUREMENT_MANAGER))
_admin_only = Depends(require_role())


# ────────────────────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────────────────────

def _compute_status(stock: float, min_t: int, crit_t: int) -> str:
    if stock <= 0:       return "Out of Stock"
    if stock <= crit_t:  return "Critical"
    if stock < min_t:    return "Low"
    return "OK"


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
        "out_of_stock": sum(1 for x in items if x["status"] == "Out of Stock"),
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
# POST /check — scan all items and auto-generate orders for Low/Critical
# ────────────────────────────────────────────────────────────────────────────

@router.post("/check", dependencies=[_pm_read])
def run_inventory_check(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Trigger inventory scan. For each Low/Critical item without an open order,
    create a procurement order automatically (calls procurement route logic directly).
    """
    from procurement import create_order, CreateOrderRequest, create_pending_approval_order

    rows = db.execute(
        text("""
            SELECT i.*, v.name AS vendor_name, v.email AS vendor_email
            FROM inventory_items i
            LEFT JOIN vendors v ON v.id = i.vendor_id
        """)
    ).mappings().all()

    # Items already having open (non-Delivered) orders
    open_orders = db.execute(
        text("""
            SELECT item_id FROM procurement_orders
            WHERE stage NOT IN ('Delivered', 'Cancelled')
        """)
    ).scalars().all()
    open_set = set(open_orders)

    created = []
    for r in rows:
        item = _enrich_item(dict(r))
        if item["item_id"] in open_set:
            continue
        trigger = None
        if item["status"] in ("Critical", "Out of Stock"):
            # <=20% of min_threshold always takes the PM-approval path
            # (Section 3a), even if the demand heuristic below would also fire.
            trigger = "VEMA-Triggered"
        elif item["current_stock"] < item.get("predicted_demand", 0):
            trigger = "Auto-Generated (Demand > Stock)"
        elif item["status"] == "Low":
            trigger = "Auto-Generated"

        if not trigger:
            continue

        # Fire notification
        if trigger == "Auto-Generated (Demand > Stock)":
            db.execute(text("""
                INSERT INTO notifications (user_id, category, title, description, created_at)
                VALUES (NULL, 'Updates', :title, :desc, NOW())
            """), {
                "title": f"Predicted Shortage: {item['name']}",
                "desc":  f"Predicted demand ({item['predicted_demand']} {item.get('unit', 'units')}) exceeds current stock ({item['current_stock']} {item.get('unit', 'units')}). Auto-generated order placed."
            })
            db.commit()
        elif item["status"] in ("Critical", "Out of Stock"):
            # <=20% of min_threshold (Section 3a) — smart contract is created
            # immediately, but the vendor is NOT emailed until a Procurement
            # Manager approves it. See RBAC_WIRING.md / N8N_AUTOMATION_WIRING.md.
            result = create_pending_approval_order(db, item)
            created.append(result)
            continue
        else:
            background_tasks.add_task(
                notify_stock_low, db,
                item["name"], item["current_stock"], item["item_id"]
            )

        result = create_order(
            CreateOrderRequest(
                item_id      = item["item_id"],
                quantity     = item["reorder_quantity"],
                trigger_type = trigger,
            ),
            db,
        )
        created.append(result)

    return {
        "message":    f"{len(created)} new orders generated",
        "new_orders": created,
        "timestamp":  datetime.utcnow().isoformat(),
    }


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
        crit_t = int(item["critical_threshold"])
        cat = item.get("category", "Operational")

        # Run prediction
        pred_demand = calculate_prediction(cat, stock, min_t)
        total_predicted += pred_demand

        # Compute anticipated status
        post_stock = max(0, stock - pred_demand)
        st = _compute_status(stock, min_t, crit_t)
        reorder_needed = (stock <= min_t) or (post_stock <= crit_t)
        trigger_type = "VEMA-Triggered" if (stock <= crit_t or post_stock <= 0) else "Auto-Generated" if reorder_needed else "None"
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

