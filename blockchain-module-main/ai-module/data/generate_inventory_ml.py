import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

os.makedirs("data/processed", exist_ok=True)

np.random.seed(42)
n = 2000
start = datetime(2023, 1, 1)

categories   = ["Generation", "Infrastructure", "Operational"]
regions      = ["Islamabad", "Lahore", "Karachi",
                "Peshawar", "Quetta"]
weathers     = ["Normal", "Heatwave", "Flood",
                "Storm", "Cold Wave"]
seasonalities= ["Summer", "Winter", "Spring", "Autumn"]

min_thresholds = {
    "Generation":      100,
    "Infrastructure":  500,
    "Operational":      50,
}

rows = []
for i in range(n):
    date        = start + timedelta(days=np.random.randint(0, 730))
    category    = np.random.choice(categories)
    region      = np.random.choice(regions)
    weather     = np.random.choice(weathers)
    seasonality = np.random.choice(seasonalities)
    promotion   = np.random.randint(0, 2)
    epidemic    = 1 if np.random.random() < 0.05 else 0

    min_thresh  = min_thresholds[category]
    inv_level   = np.random.randint(
        int(min_thresh * 0.1),
        int(min_thresh * 4))
    units_sold  = max(1, int(np.random.normal(
        min_thresh * 0.05, min_thresh * 0.02)))
    units_ordered = max(0, int(np.random.normal(
        min_thresh * 0.1, min_thresh * 0.03)))
    price       = round(np.random.uniform(100, 50000), 2)
    discount    = round(np.random.uniform(0, 0.3), 2)
    comp_price  = round(price * np.random.uniform(0.85, 1.15), 2)

    # Demand logic
    base_demand = units_sold * 1.2
    if weather in ["Heatwave", "Storm", "Flood"]:
        base_demand *= 1.4
    if seasonality == "Summer":
        base_demand *= 1.3
    if promotion == 1:
        base_demand *= 1.2
    if epidemic == 1:
        base_demand *= 1.5
    if inv_level < min_thresh:
        base_demand *= 1.3
    if comp_price < price:
        base_demand *= 0.9

    predicted_demand = max(1, round(
        base_demand + np.random.normal(0, base_demand * 0.1)))

    rows.append({
        "Date":                date.strftime("%Y-%m-%d"),
        "Category":            category,
        "Region":              region,
        "Inventory_Level":     inv_level,
        "Units_Sold":          units_sold,
        "Units_Ordered":       units_ordered,
        "Price":               price,
        "Discount":            discount,
        "Weather_Condition":   weather,
        "Promotion":           promotion,
        "Competitor_Pricing":  comp_price,
        "Seasonality":         seasonality,
        "Epidemic":            epidemic,
        "Min_Threshold":       min_thresh,
        "Predicted_Demand":    predicted_demand,
    })

df = pd.DataFrame(rows)
df.to_csv("data/processed/inventory_training_data.csv", index=False)
print(f"Generated {len(df)} rows")
print(f"Avg predicted demand: {df['Predicted_Demand'].mean():.1f}")
print(f"\nDemand by category:")
print(df.groupby("Category")["Predicted_Demand"].mean().round(1))
