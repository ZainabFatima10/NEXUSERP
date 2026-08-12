from fastapi import APIRouter
import joblib, numpy as np, sys, os
from datetime import datetime, timedelta

current_dir = os.path.dirname(os.path.abspath(__file__))
ai_module_dir = os.path.dirname(os.path.dirname(current_dir))
if ai_module_dir not in sys.path:
    sys.path.insert(0, ai_module_dir)

router = APIRouter()

BASE_DIR = ai_module_dir
try:
    demand_model = joblib.load(f"{BASE_DIR}/models/saved/demand_model.pkl")
    outage_model = joblib.load(f"{BASE_DIR}/models/saved/outage_model.pkl")
    MODEL_LOADED = True
except Exception:
    print(f"Warning: Could not load forecast models from {BASE_DIR}. Using dummy predictions.")
    demand_model = outage_model = None
    MODEL_LOADED = False

def get_risk_level(probability: float) -> str:
    if probability < 40:   return "Low"
    elif probability < 70: return "Medium"
    else:                  return "High"

def get_zones(risk: str):
    if risk == "High":     return ["G-9", "F-7", "I-8", "E-11"]
    elif risk == "Medium": return ["G-11", "F-6"]
    else:                  return []

def get_weather_factors(temp: float, wind: float,
                        rainfall: float, grid_load: float):
    factors = []
    if temp > 35:        factors.append("Heatwave alert")
    if temp < 5:         factors.append("Cold wave alert")
    if wind > 6:         factors.append("High wind speed")
    if rainfall > 10:    factors.append("Heavy rainfall")
    if grid_load > 90:   factors.append("Grid overload risk")
    if not factors:      factors.append("Normal conditions")
    return factors

def get_actions(risk: str):
    if risk == "High":
        return ["Load shedding preparation",
                "Deploy field engineers",
                "Activate demand response",
                "Public advisory"]
    elif risk == "Medium":
        return ["Pre-position repair crews",
                "Alert field engineers"]
    else:
        return ["Routine monitoring"]

@router.get("/forecast")
def get_forecast():
    forecast   = []
    today      = datetime.today()
    prev_outage = 0

    for i in range(7):
        date  = today + timedelta(days=i)
        month = date.month

        if month in [6, 7, 8]:
            temp, humidity, wind = 37.0, 62.0, 3.8
            rainfall, grid_load  = 8.0, 88.0
        elif month in [12, 1, 2]:
            temp, humidity, wind = 9.0, 72.0, 2.5
            rainfall, grid_load  = 1.0, 70.0
        else:
            temp, humidity, wind = 26.0, 55.0, 3.2
            rainfall, grid_load  = 3.0, 75.0

        season = (0 if month in [12,1,2] else
                  1 if month in [3,4,5] else
                  2 if month in [6,7,8] else 3)

        features = np.array([[
            temp, humidity, wind, rainfall,
            grid_load, 15000.0, prev_outage, 0,
            date.weekday(), month, season]])

        if MODEL_LOADED:
            demand      = float(demand_model.predict(features)[0])
            outage_prob = float(
                outage_model.predict_proba(features)[0][1] * 100)
        else:
            # Dummy prediction logic
            demand      = 15000.0 + (temp * 100)
            outage_prob = 25.0

        risk        = get_risk_level(outage_prob)
        prev_outage = 1 if outage_prob > 50 else 0

        forecast.append({
            "date":                date.strftime("%Y-%m-%d"),
            "day":                 date.strftime("%A"),
            "demand_kwh":          round(demand, 2),
            "outage_probability":  round(outage_prob, 1),
            "risk_level":          risk,
            "affected_zones":      get_zones(risk),
            "weather_factors":     get_weather_factors(
                temp, wind, rainfall, grid_load),
            "recommended_actions": get_actions(risk)
        })

    return {
        "generated_at": datetime.utcnow().isoformat(),
        "forecast":     forecast
    }

@router.get("/forecast/{date}")
def get_forecast_detail(date: str):
    forecasts = get_forecast()["forecast"]
    for day in forecasts:
        if day["date"] == date:
            return day
    return {"error": "Date not found in forecast range"}
