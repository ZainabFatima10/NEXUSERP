-- ============================================================
-- NEXUS ERP — Migration 017
-- 1. Every auto-triggered reorder (Critical, Low, Demand > Stock) now
--    waits for Admin / Procurement Manager approval before the vendor is
--    emailed (previously only the Critical / <=20% path did).
-- 2. Lowest-unit-price vendor selection: when several approved vendors
--    carry the same item in their catalogue (vendor_items), the reorder
--    goes to the one with the lowest unit price.
--    vendor_items.inventory_item_id links a catalogue row to the DISCO's
--    internal stock item. Rows without a link still match by exact
--    (case-insensitive) item name + unit at query time, see
--    procurement.select_lowest_price_vendor().
--    procurement_orders.vendor_selection records which vendors were
--    compared and why the winner was picked, for the approvals queue.
--
-- Idempotent — safe to re-run on every startup.
-- ============================================================

ALTER TABLE vendor_items ADD COLUMN IF NOT EXISTS inventory_item_id VARCHAR(20)
    REFERENCES inventory_items(item_id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_vendor_items_inventory_item ON vendor_items(inventory_item_id);

-- Backfill links for catalogue rows whose name + unit match an internal
-- item exactly. Only touches unlinked rows, so manual links are kept.
UPDATE vendor_items vi
SET inventory_item_id = ii.item_id
FROM inventory_items ii
WHERE vi.inventory_item_id IS NULL
  AND LOWER(TRIM(vi.name)) = LOWER(TRIM(ii.name))
  AND LOWER(TRIM(vi.unit)) = LOWER(TRIM(ii.unit));

ALTER TABLE procurement_orders ADD COLUMN IF NOT EXISTS vendor_selection JSONB;
