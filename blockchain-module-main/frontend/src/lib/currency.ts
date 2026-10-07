// src/lib/currency.ts
// All money in NEXUS ERP is Pakistani Rupees — enforced server-side too
// (CHECK constraints on vendor_orders / payment_methods / payment_transactions).
// Every amount the UI shows should go through formatPKR so the label and
// grouping (en-PK: 1,234,567.00) stay consistent everywhere.

export const CURRENCY = "PKR";

export const formatPKR = (v: number | null | undefined, opts?: { decimals?: boolean }): string => {
  if (v == null || Number.isNaN(v)) return "—";
  const decimals = opts?.decimals ?? true;
  return `PKR ${Number(v).toLocaleString("en-PK", {
    minimumFractionDigits: decimals ? 2 : 0,
    maximumFractionDigits: decimals ? 2 : 0,
  })}`;
};
