import json

# Load inventory
with open("data/inventory/inventory_items.json") as f:
    items = json.load(f)

print("=" * 65)
print("NEXUS ERP — Inventory Rule Validation Report")
print("=" * 65)

passed = 0
failed = 0
tests  = []

for item in items:
    current  = item["current_stock"]
    minimum  = item["min_threshold"]
    critical = minimum * 0.20
    status   = item["status"]

    # Rule 1: Critical threshold = 20% of minimum
    expected_critical = round(minimum * 0.20)
    r1 = item["critical_threshold"] == expected_critical
    tests.append(("Critical threshold = 20% of min",
                  item["name"], r1,
                  f"Expected {expected_critical}, "
                  f"got {item['critical_threshold']}"))

    # Rule 2: Status = Critical if stock <= 20% of minimum
    if current <= critical:
        expected_status = "Critical"
    elif current < minimum:
        expected_status = "Low"
    else:
        expected_status = "OK"

    r2 = status == expected_status
    tests.append(("Status classification correct",
                  item["name"], r2,
                  f"Expected {expected_status}, got {status}"))

    # Rule 3: days_until_reorder = 0 if already below minimum
    if current < minimum:
        r3 = item["days_until_reorder"] == 0
        tests.append(("Days to reorder = 0 when below min",
                      item["name"], r3,
                      f"Got {item['days_until_reorder']}"))

    # Rule 4: Reorder quantity = 2x minimum
    expected_reorder = minimum * 2
    r4 = item["reorder_quantity"] == expected_reorder
    tests.append(("Reorder qty = 2x minimum",
                  item["name"], r4,
                  f"Expected {expected_reorder}, "
                  f"got {item['reorder_quantity']}"))

# Load orders
with open("data/inventory/current_orders.json") as f:
    orders = json.load(f)

# Rule 5: Critical items must be VEMA-Triggered
critical_items = {i["item_id"] for i in items
                  if i["status"] == "Critical"}
for order in orders:
    if order["item_id"] in critical_items:
        r5 = order["trigger_type"] == "VEMA-Triggered"
        tests.append(("Critical orders = VEMA-Triggered",
                      order["item_name"], r5,
                      f"Got {order['trigger_type']}"))

# Rule 6: Low items must be Auto-Generated
low_items = {i["item_id"] for i in items
             if i["status"] == "Low"}
for order in orders:
    if order["item_id"] in low_items:
        r6 = order["trigger_type"] == "Auto-Generated"
        tests.append(("Low orders = Auto-Generated",
                      order["item_name"], r6,
                      f"Got {order['trigger_type']}"))

# Rule 7: All Low+Critical items have orders
items_needing_orders = {i["item_id"] for i in items
                        if i["status"] in ["Low", "Critical"]}
items_with_orders    = {o["item_id"] for o in orders}
all_covered = items_needing_orders == items_with_orders
tests.append(("All Low/Critical items have orders",
              "All items", all_covered,
              f"Need orders: {items_needing_orders}, "
              f"Have orders: {items_with_orders}"))

# Print results
print(f"\n{'Rule':<35} {'Item':<35} {'Result'}")
print("-" * 80)
for rule, item, result, detail in tests:
    icon = "PASS" if result else "FAIL"
    print(f"{icon}  {rule:<35} {item:<35}")
    if not result:
        print(f"      Detail: {detail}")
    if result: passed += 1
    else:      failed += 1

print("\n" + "=" * 65)
print(f"Total Tests : {len(tests)}")
print(f"Passed      : {passed}")
print(f"Failed      : {failed}")
accuracy = (passed / len(tests)) * 100
print(f"Rule Accuracy: {accuracy:.1f}%")
print("=" * 65)
