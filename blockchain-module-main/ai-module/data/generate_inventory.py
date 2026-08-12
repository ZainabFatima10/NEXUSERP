import pandas as pd
import numpy as np
import json, os
from datetime import datetime, timedelta

os.makedirs("data/inventory", exist_ok=True)

# Electrical inventory items for Pakistan DISCOs
items = [
    {"item_id": "INV-001", "name": "Distribution Transformers (11kV)", "unit": "units", "min_threshold": 50,  "current_stock": 142, "daily_consumption": 2.5, "vendor": "Siemens AG",      "vendor_email": "orders@siemens.com"},
    {"item_id": "INV-002", "name": "Circuit Breakers (33kV)",          "unit": "units", "min_threshold": 30,  "current_stock": 23,  "daily_consumption": 1.2, "vendor": "ABB Ltd",         "vendor_email": "orders@abb.com"},
    {"item_id": "INV-003", "name": "Power Cables (HT)",                "unit": "meters","min_threshold": 5000,"current_stock": 8500,"daily_consumption": 120, "vendor": "Nexans",          "vendor_email": "orders@nexans.com"},
    {"item_id": "INV-004", "name": "Smart Meters (AMI)",               "unit": "units", "min_threshold": 200, "current_stock": 4,   "daily_consumption": 8.0, "vendor": "Siemens AG",      "vendor_email": "orders@siemens.com"},
    {"item_id": "INV-005", "name": "Surge Arresters",                  "unit": "units", "min_threshold": 100, "current_stock": 67,  "daily_consumption": 3.0, "vendor": "ABB Ltd",         "vendor_email": "orders@abb.com"},
    {"item_id": "INV-006", "name": "Insulators (Porcelain)",           "unit": "units", "min_threshold": 500, "current_stock": 312, "daily_consumption": 15,  "vendor": "NGK Insulators",  "vendor_email": "orders@ngk.com"},
    {"item_id": "INV-007", "name": "Relay Protection Units",           "unit": "units", "min_threshold": 40,  "current_stock": 31,  "daily_consumption": 1.0, "vendor": "Schneider",       "vendor_email": "orders@schneider.com"},
    {"item_id": "INV-008", "name": "Copper Conductors",                "unit": "kg",    "min_threshold": 1000,"current_stock": 2,   "daily_consumption": 45,  "vendor": "Prysmian Group",  "vendor_email": "orders@prysmian.com"},
]

def get_status(current, minimum):
    critical_threshold = minimum * 0.20
    if current <= critical_threshold: return "Critical"
    elif current < minimum:           return "Low"
    else:                             return "OK"

def days_until_reorder(current, minimum, daily_consumption):
    if daily_consumption <= 0: return 999
    return max(0, round((current - minimum) / daily_consumption))

def days_until_critical(current, minimum, daily_consumption):
    if daily_consumption <= 0: return 999
    critical = minimum * 0.20
    return max(0, round((current - critical) / daily_consumption))

inventory = []
for item in items:
    status = get_status(item["current_stock"], item["min_threshold"])
    inventory.append({
        **item,
        "status":               status,
        "critical_threshold":   round(item["min_threshold"] * 0.20),
        "days_until_reorder":   days_until_reorder(
            item["current_stock"],
            item["min_threshold"],
            item["daily_consumption"]),
        "days_until_critical":  days_until_critical(
            item["current_stock"],
            item["min_threshold"],
            item["daily_consumption"]),
        "last_updated":         datetime.now().isoformat(),
        "reorder_quantity":     item["min_threshold"] * 2,
    })

df = pd.DataFrame(inventory)
df.to_csv("data/inventory/inventory_items.csv", index=False)

with open("data/inventory/inventory_items.json", "w") as f:
    json.dump(inventory, f, indent=2)

print(f"Created {len(inventory)} inventory items")
print("\nStock Status Summary:")
for item in inventory:
    print(f"  {item['status']:8} | {item['name']:35} | "
          f"Stock: {item['current_stock']:6} | "
          f"Min: {item['min_threshold']:5} | "
          f"Days to reorder: {item['days_until_reorder']}")
