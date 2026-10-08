// src/lib/stockThresholds.ts
// Inventory stock-label thresholds — mirrors ai-module/stock_thresholds.py
// (the backend computes `status`; this keeps badges, bars and copy in step).
// Stock % = current_stock / min_threshold x 100.
//   Critical < 21% (0% included) · Low 21–35% · OK >= 36%

export const CRITICAL_BELOW_PCT = 21;
export const LOW_BELOW_PCT = 36;

export type StockStatus = "OK" | "Low" | "Critical";

export function stockStatus(pct: number): StockStatus {
  if (pct < CRITICAL_BELOW_PCT) return "Critical";
  if (pct < LOW_BELOW_PCT) return "Low";
  return "OK";
}

/** Badge classes per label: green / amber / red. */
export const STOCK_STATUS_BADGE: Record<StockStatus, string> = {
  OK: "bg-success/10 text-success",
  Low: "bg-warning/10 text-warning",
  Critical: "bg-destructive/10 text-destructive",
};

/** Stock-bar fill per label. */
export const STOCK_STATUS_BAR: Record<StockStatus, string> = {
  OK: "bg-success",
  Low: "bg-warning",
  Critical: "bg-destructive",
};

/** Human-readable ranges, for banners and tooltips. */
export const STOCK_RANGES = {
  Critical: `below ${CRITICAL_BELOW_PCT}%`,
  Low: `${CRITICAL_BELOW_PCT}–${LOW_BELOW_PCT - 1}%`,
  OK: `${LOW_BELOW_PCT}% and above`,
} as const;
