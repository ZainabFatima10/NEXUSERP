import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import os

os.makedirs("data/raw", exist_ok=True)
os.makedirs("data/processed", exist_ok=True)

# Generate 2 years of daily data
np.random.seed(42)
days = 730
start_date = datetime(2024, 1, 1)

data = []
for i in range(days):
    date = start_date + timedelta(days=i)
    month = date.month
    dow = date.weekday()

    # Realistic Pakistan weather patterns
    if month in [6, 7, 8]:      # Summer — hot
        temp = np.random.normal(38, 3)
        humidity = np.random.normal(60, 10)
    elif month in [12, 1, 2]:   # Winter — cold
        temp = np.random.normal(10, 4)
        humidity = np.random.normal(70, 8)
    else:                        # Spring/Autumn
        temp = np.random.normal(25, 5)
        humidity = np.random.normal(55, 10)

    wind_speed = np.random.normal(3.5, 1.2)

    # Demand increases with heat (AC usage)
    base_demand = 15000
    temp_effect = (temp - 20) * 200
    weekend_effect = -800 if dow >= 5 else 0
    demand_kwh = base_demand + temp_effect + weekend_effect + \
                 np.random.normal(0, 500)

    # Outage more likely when demand is high + hot
    outage_prob = 0.05
    if temp > 35:
        outage_prob += 0.25
    if demand_kwh > 20000:
        outage_prob += 0.20
    if wind_speed > 5:
        outage_prob += 0.10
    outage_label = 1 if np.random.random() < outage_prob else 0

    data.append({
        "date":          date.strftime("%Y-%m-%d"),
        "city":          "Islamabad",
        "temperature":   round(temp, 1),
        "humidity":      round(humidity, 1),
        "wind_speed":    round(wind_speed, 2),
        "demand_kwh":    round(demand_kwh, 2),
        "outage_label":  outage_label,
        "day_of_week":   dow,
        "month":         month,
        "season":        0 if month in [12,1,2] else
                         1 if month in [3,4,5] else
                         2 if month in [6,7,8] else 3
    })

df = pd.DataFrame(data)
df.to_csv("data/processed/nexus_training_data.csv", index=False)
print(f"Generated {len(df)} rows of training data")
print(f"Outage rate: {df['outage_label'].mean()*100:.1f}%")
print(f"Avg temperature: {df['temperature'].mean():.1f}°C")
print(f"Avg demand: {df['demand_kwh'].mean():.0f} KWh")
print("\nSample rows:")
print(df.head())