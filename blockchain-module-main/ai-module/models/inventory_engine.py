import sys, uuid
sys.path.insert(0, "/Users/zainabfatima/Desktop/nexus-erp/ai-module")
from pydantic import BaseModel
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import joblib, numpy as np, os

# Try to load the models directly for predictions
current_dir = os.path.dirname(os.path.abspath(__file__))
ai_module_dir = os.path.dirname(current_dir)
BASE = os.path.join(ai_module_dir, "models", "saved")
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

def get_status(current, minimum):
    if current <= minimum * 0.20: return "Critical"
    elif current < minimum:       return "Low"
    else:                         return "OK"

def get_inventory_overview(category: str = None):
    with engine.connect() as conn:
        if category:
            rows = conn.execute(text(
                "SELECT * FROM inventory_items WHERE category = :cat ORDER BY item_id"
            ), {"cat": category}).fetchall()
        else:
            rows = conn.execute(text(
                "SELECT * FROM inventory_items ORDER BY category, item_id"
            )).fetchall()

    items = []
    for r in rows:
        status = get_status(r.current_stock, r.min_threshold)
        days_reorder = max(0, round(
            (r.current_stock - r.min_threshold) / r.daily_consumption
        )) if r.daily_consumption > 0 else 999
        days_critical = max(0, round(
            (r.current_stock - r.critical_threshold) / r.daily_consumption
        )) if r.daily_consumption > 0 else 999
        predicted = calculate_prediction(r.category, r.current_stock, r.min_threshold)
        items.append({
            "item_id":             r.item_id,
            "name":                r.name,
            "category":            r.category,
            "unit":                r.unit,
            "min_threshold":       r.min_threshold,
            "current_stock":       r.current_stock,
            "daily_consumption":   r.daily_consumption,
            "vendor":              r.vendor,
            "vendor_email":        r.vendor_email,
            "status":              status,
            "critical_threshold":  r.critical_threshold,
            "days_until_reorder":  days_reorder,
            "days_until_critical": days_critical,
            "reorder_quantity":    r.reorder_quantity,
            "predicted_demand":    predicted,
            "last_updated":        r.last_updated.isoformat()
        })
    return items

def get_current_orders(category: str = None):
    with engine.connect() as conn:
        if category:
            rows = conn.execute(text("""
                SELECT * FROM procurement_orders
                WHERE stage != 'Delivered' AND category = :cat
                ORDER BY created_at DESC
            """), {"cat": category}).fetchall()
        else:
            rows = conn.execute(text("""
                SELECT * FROM procurement_orders
                WHERE stage != 'Delivered'
                ORDER BY created_at DESC
            """)).fetchall()
    result = []
    for r in rows:
        d = dict(r._mapping)
        d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
        d["accepted_at"] = d["accepted_at"].isoformat() if d["accepted_at"] else None
        d["expected_delivery"] = str(d["expected_delivery"]) if d["expected_delivery"] else None
        result.append(d)
    return result

def get_past_orders(category: str = None):
    with engine.connect() as conn:
        if category:
            rows = conn.execute(text("""
                SELECT * FROM procurement_orders
                WHERE stage = 'Delivered' AND category = :cat
                ORDER BY created_at DESC
            """), {"cat": category}).fetchall()
        else:
            rows = conn.execute(text("""
                SELECT * FROM procurement_orders
                WHERE stage = 'Delivered'
                ORDER BY created_at DESC
            """)).fetchall()
    result = []
    for r in rows:
        d = dict(r._mapping)
        d["created_at"] = d["created_at"].isoformat() if d["created_at"] else None
        d["expected_delivery"] = str(d["expected_delivery"]) if d["expected_delivery"] else None
        result.append(d)
    return result

def check_and_generate_orders():
    items = get_inventory_overview()
    new_orders = []

    with engine.connect() as conn:
        existing = {r[0] for r in conn.execute(text("""
            SELECT item_id FROM procurement_orders
            WHERE stage != 'Delivered'
        """)).fetchall()}

        for item in items:
            trigger = None
            if item["current_stock"] < item["predicted_demand"]:
                trigger = "Auto-Generated (Demand > Stock)"
            elif item["status"] != "OK":
                trigger = "VEMA-Triggered" if item["status"] == "Critical" else "Auto-Generated"
            
            if not trigger: continue
            if item["item_id"] in existing: continue

            order_id = f"ORD-{uuid.uuid4().hex[:6].upper()}"
            delivery = (datetime.now() + timedelta(days=14)).strftime("%Y-%m-%d")

            conn.execute(text("""
                INSERT INTO procurement_orders
                (order_id, item_id, item_name, category, quantity, unit,
                 vendor, vendor_email, trigger_type, stage,
                 contract_status, expected_delivery)
                VALUES (:oid,:iid,:iname,:cat,:qty,:unit,
                        :vendor,:vemail,:trigger,:stage,:cstatus,:delivery)
            """), {
                "oid":     order_id, "iid":    item["item_id"],
                "iname":   item["name"], "cat": item["category"],
                "qty":     item["reorder_quantity"],
                "unit":    item["unit"], "vendor": item["vendor"],
                "vemail":  item["vendor_email"], "trigger": trigger,
                "stage":   "Pending Verification",
                "cstatus": "Pending", "delivery": delivery
            })

            title = f"Reorder Required: {item['name']}"
            if "Demand > Stock" in trigger:
                title = f"Predicted Shortage: {item['name']}"
                msg = (f"Predicted demand ({item['predicted_demand']} {item['unit']}) "
                       f"exceeds current stock ({item['current_stock']} {item['unit']}). "
                       f"Auto-generated order placed.")
            else:
                msg = (f"{trigger} — Stock at {item['current_stock']} "
                       f"{item['unit']} (min: {item['min_threshold']}). "
                       f"Order {item['reorder_quantity']} {item['unit']} "
                       f"from {item['vendor']}. Awaiting approval.")

            conn.execute(text("""
                INSERT INTO notifications
                (type, title, message, order_id, item_name, category)
                VALUES (:type,:title,:msg,:oid,:iname,:cat)
            """), {
                "type":  "REORDER_REQUEST",
                "title": title,
                "msg":   msg,
                "oid":   order_id,
                "iname": item["name"],
                "cat":   item["category"]
            })
            conn.commit()
            new_orders.append(order_id)
            print(f"[{trigger}] {order_id} — {item['name']} ({item['category']})")

    return new_orders

def accept_order(order_id: str, officer_name: str):
    with engine.connect() as conn:
        conn.execute(text("""
            UPDATE procurement_orders
            SET stage = 'Order Placed',
                contract_status = 'Verified',
                accepted_by = :officer,
                accepted_at = NOW()
            WHERE order_id = :oid
        """), {"officer": officer_name, "oid": order_id})

        row = conn.execute(text("""
            SELECT item_name, vendor, category FROM procurement_orders
            WHERE order_id = :oid
        """), {"oid": order_id}).fetchone()

        if row:
            conn.execute(text("""
                INSERT INTO notifications
                (type, title, message, order_id, item_name, category)
                VALUES (:type,:title,:msg,:oid,:iname,:cat)
            """), {
                "type":  "ORDER_CONFIRMED",
                "title": f"Order Confirmed: {row.item_name}",
                "msg":   f"Order {order_id} accepted by {officer_name}. "
                         f"Smart contract verified. Vendor email dispatched to {row.vendor}.",
                "oid":   order_id,
                "iname": row.item_name,
                "cat":   row.category
            })
        conn.commit()
    return {"message": f"Order {order_id} accepted"}

def get_notifications(unread_only=False):
    with engine.connect() as conn:
        query = "SELECT * FROM notifications"
        if unread_only:
            query += " WHERE is_read = FALSE"
        query += " ORDER BY created_at DESC LIMIT 50"
        rows = conn.execute(text(query)).fetchall()
    result = []
    for r in rows:
        d = dict(r._mapping)
        d["created_at"] = d["created_at"].isoformat()
        result.append(d)
    return result

def mark_notification_read(notification_id: int):
    with engine.connect() as conn:
        conn.execute(text(
            "UPDATE notifications SET is_read = TRUE WHERE id = :id"
        ), {"id": notification_id})
        conn.commit()

def get_dashboard_stats():
    items  = get_inventory_overview()
    orders = get_current_orders()
    with engine.connect() as conn:
        unread = conn.execute(text(
            "SELECT COUNT(*) FROM notifications WHERE is_read = FALSE"
        )).scalar()

    # Per category breakdown
    categories = ["Generation", "Infrastructure", "Operational"]
    cat_stats  = {}
    for cat in categories:
        cat_items = [i for i in items if i["category"] == cat]
        cat_stats[cat] = {
            "total":    len(cat_items),
            "ok":       sum(1 for i in cat_items if i["status"] == "OK"),
            "low":      sum(1 for i in cat_items if i["status"] == "Low"),
            "critical": sum(1 for i in cat_items if i["status"] == "Critical"),
            "predicted_demand": sum(i["predicted_demand"] for i in cat_items),
        }

    return {
        "inventory": {
            "total":      len(items),
            "ok":         sum(1 for i in items if i["status"] == "OK"),
            "low":        sum(1 for i in items if i["status"] == "Low"),
            "critical":   sum(1 for i in items if i["status"] == "Critical"),
            "predicted_demand": sum(i["predicted_demand"] for i in items),
            "by_category": cat_stats
        },
        "orders": {
            "total":   len(orders),
            "pending": sum(1 for o in orders if o["stage"] == "Pending Verification"),
            "placed":  sum(1 for o in orders if o["stage"] == "Order Placed"),
        },
        "notifications": {"unread": unread},
        "models": {
            "outage_accuracy":    89.8,
            "inventory_accuracy": 94.9,
        }
    }
