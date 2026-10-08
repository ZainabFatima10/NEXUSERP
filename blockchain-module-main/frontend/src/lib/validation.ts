// src/lib/validation.ts
// Inline field checks for order forms — return an error message to show
// under the field (and to disable submit), or null when the value is fine.
// The backend enforces the same rules (procurement.py / vendor_orders.py).

/** Quantity being ordered: must be a number greater than zero. */
export function orderQuantityError(value: number | string): string | null {
  if (value === "" || value === null || value === undefined) return "Quantity is required";
  const n = Number(value);
  if (!Number.isFinite(n)) return "Quantity must be a number";
  if (n < 0) return "Quantity cannot be negative";
  if (n === 0) return "Quantity must be greater than 0";
  return null;
}

/** Quantity counted on delivery: zero is allowed (nothing usable arrived), negative is not. */
export function receivedQuantityError(value: number | string): string | null {
  if (value === "" || value === null || value === undefined) return "Quantity is required";
  const n = Number(value);
  if (!Number.isFinite(n)) return "Quantity must be a number";
  if (n < 0) return "Quantity cannot be negative";
  return null;
}

/** Optional unit price: blank is allowed, negative is not. */
export function unitPriceError(value: number | string): string | null {
  if (value === "" || value === null || value === undefined) return null;
  const n = Number(value);
  if (!Number.isFinite(n)) return "Unit price must be a number";
  if (n < 0) return "Unit price cannot be negative";
  return null;
}
