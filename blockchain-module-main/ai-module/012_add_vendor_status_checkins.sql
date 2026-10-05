-- ============================================================
-- NEXUS ERP — Migration 012
-- Vendor delivery-status check-in emails: once a vendor accepts an order,
-- nudge them ~3x/day (every 8h by default) for a status update until the
-- shipment leaves the "in flight" states (Preparing/Dispatched/InTransit/
-- OutForDelivery). Each reply (via the existing no-login shipment-update
-- link) already notifies the receiver through the normal shipment.*
-- events in vendor_orders.py — this migration only adds the scheduling
-- state for the outbound nudge itself.
--
-- Idempotent — safe to re-run on every startup.
-- ============================================================

ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS next_status_checkin_due TIMESTAMPTZ;
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS status_checkin_count INTEGER NOT NULL DEFAULT 0;
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS last_status_checkin_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_vendor_orders_status_checkin_due ON vendor_orders (next_status_checkin_due)
  WHERE next_status_checkin_due IS NOT NULL;
