"""
NEXUS ERP — Vendor Catalogue Parser
Parses a vendor's uploaded .xlsx/.csv item catalogue (Become-a-Vendor Step 5)
into validated row dicts. Used by both the preview-only endpoint
(POST /public/vendors/items/parse) and the actual application submit — same
function, so what the vendor previewed is exactly what gets staged.

Never evaluates formulas (pandas/openpyxl read computed values, not formula
strings, so this is inherent — no extra work needed) and never writes to
the DB itself; callers decide what to do with the parsed rows.
"""
import io
from typing import Optional

import pandas as pd

MAX_ROWS = 2000
MAX_BYTES = 5 * 1024 * 1024

REQUIRED_COLUMNS = ["item name", "unit of measure", "unit price (pkr)"]
# Canonical column -> accepted header variants (lowercased, stripped).
COLUMN_ALIASES = {
    "name":            ["item name", "name", "item"],
    "sku":             ["item code/sku", "sku", "item code", "code"],
    "category":        ["category"],
    "description":     ["description"],
    "unit":            ["unit of measure", "unit", "uom"],
    "unit_price":      ["unit price (pkr)", "unit price", "price", "price (pkr)"],
    "moq":             ["minimum order quantity", "moq", "min order quantity"],
    "lead_time_days":  ["lead time (days, optional override)", "lead time (days)", "lead time days", "lead time"],
}

TEMPLATE_COLUMNS = [
    "Item Name", "Item Code/SKU", "Category", "Description",
    "Unit of Measure", "Unit Price (PKR)", "Minimum Order Quantity",
    "Lead Time (days, optional override)",
]
TEMPLATE_EXAMPLE_ROW = [
    "Distribution Transformer 11kV", "DT-11KV-001", "Infrastructure",
    "Oil-filled pole-mounted transformer", "units", "185000", "5", "21",
]


def _normalize_header(h) -> str:
    return str(h).strip().lower().replace("﻿", "")  # strip BOM if present on first header


def _build_column_map(columns) -> dict:
    """Map normalized actual column name -> canonical field name."""
    normalized = {_normalize_header(c): c for c in columns}
    result = {}
    for canonical, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            if alias in normalized:
                result[canonical] = normalized[alias]
                break
    return result


def parse_catalogue_file(content: bytes, filename: str, known_categories: list[str]) -> dict:
    """
    Parse an uploaded .xlsx/.csv catalogue.
    Returns {valid_rows: [...], invalid_rows: [...], row_count, truncated}.
    Each invalid row carries the original data plus a list of reasons.
    """
    if len(content) > MAX_BYTES:
        return {"error": f"File exceeds the {MAX_BYTES // (1024*1024)} MB limit."}

    lower_name = filename.lower()
    try:
        if lower_name.endswith(".csv"):
            # engine='python' + encoding fallback handles BOM / odd encodings
            # more forgivingly than the default C parser.
            try:
                df = pd.read_csv(io.BytesIO(content), dtype=str, encoding="utf-8-sig")
            except UnicodeDecodeError:
                df = pd.read_csv(io.BytesIO(content), dtype=str, encoding="latin-1")
        elif lower_name.endswith(".xlsx"):
            df = pd.read_excel(io.BytesIO(content), dtype=str, engine="openpyxl")
        else:
            return {"error": "Unsupported file type — upload .xlsx or .csv."}
    except Exception as e:
        return {"error": f"Could not read file: {e}"}

    if df.empty:
        return {"error": "File has no data rows."}

    df = df.dropna(how="all")  # drop fully-blank rows (trailing Excel rows etc.)
    truncated = False
    if len(df) > MAX_ROWS:
        df = df.iloc[:MAX_ROWS]
        truncated = True

    col_map = _build_column_map(df.columns)
    missing_required = [c for c in ("name", "unit", "unit_price") if c not in col_map]
    if missing_required:
        return {
            "error": (
                "Missing required column(s): "
                f"{', '.join(missing_required)}. Download the template for the exact headers."
            )
        }

    known_categories_lower = {c.lower(): c for c in known_categories}
    seen_skus: dict[str, int] = {}
    seen_names: dict[str, int] = {}
    valid_rows, invalid_rows = [], []

    for idx, row in df.iterrows():
        row_number = int(idx) + 2  # +1 for 0-index, +1 for header row
        reasons: list[str] = []

        def cell(field: str) -> Optional[str]:
            col = col_map.get(field)
            if col is None:
                return None
            val = row.get(col)
            if val is None or (isinstance(val, float) and pd.isna(val)):
                return None
            val = str(val).strip()
            return val or None

        name = cell("name")
        if not name:
            reasons.append("missing item name")

        unit = cell("unit")
        if not unit:
            reasons.append("missing unit of measure")

        raw_price = cell("unit_price")
        price_val = None
        if not raw_price:
            reasons.append("missing unit price")
        else:
            try:
                price_val = float(raw_price.replace(",", ""))
                if price_val < 0:
                    reasons.append("unit price is negative")
            except ValueError:
                reasons.append(f"unit price '{raw_price}' is not numeric")

        sku = cell("sku")
        if sku:
            key = sku.lower()
            if key in seen_skus:
                reasons.append(f"duplicate SKU (also row {seen_skus[key]})")
            else:
                seen_skus[key] = row_number

        if name:
            name_key = name.lower()
            if name_key in seen_names:
                reasons.append(f"duplicate item name (also row {seen_names[name_key]})")
            else:
                seen_names[name_key] = row_number

        category_raw = cell("category")
        category = None
        if category_raw:
            category = known_categories_lower.get(category_raw.lower())
            if category is None:
                # Unknown category isn't fatal — keep the row importable,
                # just flag it so the vendor/admin can fix it inline.
                reasons.append(f"unknown category '{category_raw}' (will be left blank)")

        moq_raw = cell("moq")
        moq_val = None
        if moq_raw:
            try:
                moq_val = float(moq_raw.replace(",", ""))
            except ValueError:
                reasons.append(f"MOQ '{moq_raw}' is not numeric")

        lead_time_raw = cell("lead_time_days")
        lead_time_val = None
        if lead_time_raw:
            try:
                lead_time_val = int(float(lead_time_raw))
            except ValueError:
                reasons.append(f"lead time '{lead_time_raw}' is not numeric")

        parsed = {
            "row_number":      row_number,
            "name":            name,
            "sku":             sku,
            "category":        category if not reasons or category else category_raw,
            "description":     cell("description"),
            "unit":            unit,
            "unit_price":      price_val,
            "moq":             moq_val,
            "lead_time_days":  lead_time_val,
        }

        if reasons:
            invalid_rows.append({**parsed, "errors": reasons})
        else:
            valid_rows.append(parsed)

    return {
        "valid_rows":   valid_rows,
        "invalid_rows": invalid_rows,
        "row_count":    len(df),
        "truncated":    truncated,
    }


def build_template_bytes() -> bytes:
    """Excel template with the exact expected columns + one example row."""
    buf = io.BytesIO()
    df = pd.DataFrame([TEMPLATE_EXAMPLE_ROW], columns=TEMPLATE_COLUMNS)
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Catalogue")
    return buf.getvalue()
