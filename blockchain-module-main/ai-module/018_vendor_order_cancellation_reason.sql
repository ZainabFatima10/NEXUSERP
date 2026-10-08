-- ============================================================
-- NEXUS ERP — Migration 018
-- Store why a vendor order was cancelled, both for the orderer's
-- "Cancel Order" (now requires a reason) and the admin "Cancel contract"
-- path. The same reason is emailed to the vendor (vendor_orders.py).
--
-- Idempotent — safe to re-run on every startup.
-- ============================================================

ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS cancellation_reason TEXT;
