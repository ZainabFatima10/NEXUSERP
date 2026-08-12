import pandas as pd
import numpy as np
from xgboost import XGBRegressor
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, r2_score
from sklearn.preprocessing import LabelEncoder
import joblib, os

os.makedirs("models/saved", exist_ok=True)

df = pd.read_csv("data/processed/inventory_training_data.csv")
print(f"Loaded {len(df)} rows")

# Encode categoricals
le_category    = LabelEncoder()
le_region      = LabelEncoder()
le_weather     = LabelEncoder()
le_seasonality = LabelEncoder()

df["Category_enc"]          = le_category.fit_transform(df["Category"])
df["Region_enc"]            = le_region.fit_transform(df["Region"])
df["Weather_enc"]           = le_weather.fit_transform(df["Weather_Condition"])
df["Seasonality_enc"]       = le_seasonality.fit_transform(df["Seasonality"])

# Date features
df["Date"]  = pd.to_datetime(df["Date"])
df["month"] = df["Date"].dt.month
df["dow"]   = df["Date"].dt.dayofweek

FEATURES = [
    "Category_enc", "Region_enc", "Weather_enc",
    "Seasonality_enc", "Inventory_Level", "Units_Sold",
    "Units_Ordered", "Price", "Discount", "Promotion",
    "Competitor_Pricing", "Epidemic", "Min_Threshold",
    "month", "dow"
]

X = df[FEATURES]
y = df["Predicted_Demand"]

X_train, X_test, y_train, y_test = train_test_split(
    X, y, test_size=0.2, random_state=42)

model = XGBRegressor(
    n_estimators=300,
    max_depth=6,
    learning_rate=0.05,
    subsample=0.8,
    colsample_bytree=0.8,
    random_state=42)

model.fit(X_train, y_train,
          eval_set=[(X_test, y_test)],
          verbose=50)

preds = model.predict(X_test)
mae   = mean_absolute_error(y_test, preds)
r2    = r2_score(y_test, preds)
acc   = max(0, r2 * 100)

print(f"\nModel Performance:")
print(f"  MAE : {mae:.2f} units")
print(f"  R²  : {r2:.4f}")
print(f"  Accuracy (R²): {acc:.1f}%")

# Save model + encoders
joblib.dump(model,          "models/saved/inventory_model.pkl")
joblib.dump(le_category,    "models/saved/le_category.pkl")
joblib.dump(le_region,      "models/saved/le_region.pkl")
joblib.dump(le_weather,     "models/saved/le_weather.pkl")
joblib.dump(le_seasonality, "models/saved/le_seasonality.pkl")

print("\nAll files saved successfully!")
print("\nFeature importances:")
fi = pd.Series(model.feature_importances_, index=FEATURES)
print(fi.sort_values(ascending=False).head(8))
