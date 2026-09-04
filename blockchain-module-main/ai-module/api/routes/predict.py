from fastapi import APIRouter
import joblib, numpy as np, sys, os
from datetime import datetime
from pydantic import BaseModel
from typing import Optional

current_dir = os.path.dirname(os.path.abspath(__file__))
ai_module_dir = os.path.dirname(os.path.dirname(current_dir))
if ai_module_dir not in sys.path:
    sys.path.insert(0, ai_module_dir)

from fastapi import Depends
from rbac import require_role

router = APIRouter()
_admin = Depends(require_role())

BASE = os.path.join(ai_module_dir, "models", "saved")
try:
    model          = joblib.load(f"{BASE}/inventory_model.pkl")
    le_category    = joblib.load(f"{BASE}/le_category.pkl")
    le_region      = joblib.load(f"{BASE}/le_region.pkl")
    le_weather     = joblib.load(f"{BASE}/le_weather.pkl")
    le_seasonality = joblib.load(f"{BASE}/le_seasonality.pkl")
    MODEL_LOADED = True
except Exception as e:
    print(f"Warning: Could not load prediction models from {BASE}. Using dummy predictions.")
    model = le_category = le_region = le_weather = le_seasonality = None
    MODEL_LOADED = False

MIN_THRESHOLDS = {
    "Generation": 100,
    "Infrastructure": 500,
    "Operational": 50,
}

class PredictionRequest(BaseModel):
    Date:                str
    Store_ID:            Optional[str] = "S001"
    Product_ID:          Optional[str] = "P001"
    Category:            str
    Region:              str
    Inventory_Level:     int
    Units_Sold:          int
    Units_Ordered:       int
    Price:               float
    Discount:            float
    Weather_Condition:   str
    Promotion:           int
    Competitor_Pricing:  float
    Seasonality:         str
    Epidemic:            int

def get_status(inventory: int, min_thresh: int) -> str:
    if inventory <= min_thresh * 0.20: return "Critical"
    elif inventory < min_thresh:       return "Low"
    else:                              return "OK"

def safe_encode(encoder, value, default=0):
    try:
        return int(encoder.transform([value])[0])
    except:
        return default

@router.post("/predict", dependencies=[_admin])
def predict_demand(req: PredictionRequest):
    date  = datetime.strptime(req.Date, "%Y-%m-%d")
    month = date.month
    dow   = date.weekday()

    min_thresh = MIN_THRESHOLDS.get(req.Category, 100)

    features = np.array([[
        safe_encode(le_category,    req.Category),
        safe_encode(le_region,      req.Region),
        safe_encode(le_weather,     req.Weather_Condition),
        safe_encode(le_seasonality, req.Seasonality),
        req.Inventory_Level,
        req.Units_Sold,
        req.Units_Ordered,
        req.Price,
        req.Discount,
        req.Promotion,
        req.Competitor_Pricing,
        req.Epidemic,
        min_thresh,
        month,
        dow
    ]])

    if MODEL_LOADED:
        predicted_demand = max(1, round(
            float(model.predict(features)[0])))
    else:
        # Dummy prediction logic
        predicted_demand = min_thresh * 2 if req.Inventory_Level < min_thresh else int(req.Inventory_Level * 0.9)
    
    status           = get_status(
        req.Inventory_Level, predicted_demand)
    reorder_needed   = status in ["Low", "Critical"]
    reorder_qty      = predicted_demand * 2 if reorder_needed else 0

    return {
        "predicted_demand": predicted_demand,
        "status":           status,
        "reorder_needed":   reorder_needed,
        "reorder_quantity": reorder_qty,
        "min_threshold":    min_thresh,
        "trigger_type":     "VEMA-Triggered"
                            if status == "Critical"
                            else "Auto-Generated"
                            if status == "Low"
                            else "None",
        "message": f"Demand forecast: {predicted_demand} units. "
                   f"Stock status: {status}."
    }
