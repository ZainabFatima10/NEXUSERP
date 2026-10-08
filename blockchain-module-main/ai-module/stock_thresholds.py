"""
NEXUS ERP — Inventory stock-label thresholds (single source of truth).

Stock percentage = current_stock / min_threshold x 100 (the formula
inventory_v2._enrich_item has always used for `stock_pct`).

    Label      Range           Boundary used (pct can be fractional)
    Critical   0% - 20%        pct < 21      (0% / out of stock is Critical too)
    Low        21% - 35%       21 <= pct < 36
    OK         36% and above   pct >= 36

Mirrored for the frontend in frontend/src/lib/stockThresholds.ts, and in
SQL by migration 019 (which recomputes the stored inventory_items.status).
Change all three together.
"""

CRITICAL_BELOW_PCT = 21.0
LOW_BELOW_PCT      = 36.0

STATUS_CRITICAL = "Critical"
STATUS_LOW      = "Low"
STATUS_OK       = "OK"


def stock_pct(current_stock, min_threshold) -> float:
    """Unrounded stock percentage. An item with no minimum set counts as 100%."""
    mn = float(min_threshold or 0)
    if mn <= 0:
        return 100.0
    return float(current_stock or 0) / mn * 100.0


def stock_status(current_stock, min_threshold) -> str:
    pct = stock_pct(current_stock, min_threshold)
    if pct < CRITICAL_BELOW_PCT:
        return STATUS_CRITICAL
    if pct < LOW_BELOW_PCT:
        return STATUS_LOW
    return STATUS_OK
