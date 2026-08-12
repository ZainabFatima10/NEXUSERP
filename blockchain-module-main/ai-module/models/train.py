import pandas as pd
import numpy as np
from xgboost import XGBClassifier, XGBRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import (accuracy_score, classification_report,
                             roc_auc_score, mean_absolute_error)
import joblib, os

os.makedirs("models/saved", exist_ok=True)

df = pd.read_csv("data/processed/nexus_training_data.csv")
print(f"Loaded {len(df)} rows")
print(f"Outage rate: {df['outage_label'].mean()*100:.1f}%")

FEATURES = ["temperature", "humidity", "wind_speed",
            "rainfall", "grid_load", "demand_kwh",
            "prev_outage", "maintenance",
            "day_of_week", "month", "season"]
X = df[FEATURES]

# Demand model
print("\nTraining demand model...")
y_demand = df["demand_kwh"]
X_tr, X_te, y_tr, y_te = train_test_split(
    X, y_demand, test_size=0.2, random_state=42)
demand_model = XGBRegressor(
    n_estimators=300, max_depth=6,
    learning_rate=0.05, random_state=42)
demand_model.fit(X_tr, y_tr)
print(f"Demand MAE: {mean_absolute_error(y_te, demand_model.predict(X_te)):.0f} KWh")
joblib.dump(demand_model, "models/saved/demand_model.pkl")

# Outage model
print("\nTraining outage model...")
y_outage = df["outage_label"]

# Calculate class weight automatically
n_neg = (y_outage == 0).sum()
n_pos = (y_outage == 1).sum()
scale = n_neg / n_pos
print(f"Class weight scale: {scale:.1f}")

X_tr, X_te, y_tr, y_te = train_test_split(
    X, y_outage, test_size=0.2, random_state=42)

outage_model = XGBClassifier(
    n_estimators=500,
    max_depth=7,
    learning_rate=0.03,
    scale_pos_weight=scale,
    subsample=0.8,
    colsample_bytree=0.8,
    min_child_weight=3,
    gamma=0.1,
    random_state=42)

outage_model.fit(X_tr, y_tr,
    eval_set=[(X_te, y_te)],
    verbose=100)

acc = accuracy_score(y_te, outage_model.predict(X_te))
auc = roc_auc_score(y_te,
      outage_model.predict_proba(X_te)[:,1])

print(f"\nOutage Model Accuracy : {acc*100:.1f}%")
print(f"ROC-AUC Score         : {auc:.4f}")
print("\nClassification Report:")
print(classification_report(y_te, outage_model.predict(X_te)))

joblib.dump(outage_model, "models/saved/outage_model.pkl")
print("Both models saved!")
