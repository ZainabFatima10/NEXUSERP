-- ============================================================
-- NEXUS ERP — Migration 014
-- 1. Re-price the seeded inventory catalogue in Pakistani Rupees.
--    002 seeded these with USD-scale numbers (e.g. a 500kW generator at
--    5000). Each row is only updated if it still holds its original seed
--    value, so a price someone has since edited by hand is left alone,
--    and re-running is a no-op.
-- 2. Support the real bank-transfer payout process (PAYMENT_PROVIDER=manual,
--    see payments.py): a payout becomes 'Awaiting Transfer' until an admin
--    records the bank's transaction ID for the Raast/IBFT transfer.
--
-- Idempotent — safe to re-run on every startup.
-- ============================================================

-- Generation
UPDATE inventory_items SET unit_price = 9500000.00  WHERE item_id = 'INV-001' AND unit_price = 5000.00;   -- Generator 500kW
UPDATE inventory_items SET unit_price = 9000.00     WHERE item_id = 'INV-002' AND unit_price = 180.00;    -- Solar panel 250W
UPDATE inventory_items SET unit_price = 2500000.00  WHERE item_id = 'INV-003' AND unit_price = 12000.00;  -- Wind turbine blade
UPDATE inventory_items SET unit_price = 275.00      WHERE item_id = 'INV-004' AND unit_price = 1.20;      -- Diesel, per litre
UPDATE inventory_items SET unit_price = 25000000.00 WHERE item_id = 'INV-005' AND unit_price = 45000.00;  -- Steam turbine
-- Infrastructure
UPDATE inventory_items SET unit_price = 650000.00   WHERE item_id = 'INV-006' AND unit_price = 8500.00;   -- 11kV distribution transformer
UPDATE inventory_items SET unit_price = 2800.00     WHERE item_id = 'INV-007' AND unit_price = 15.00;     -- HT cable, per metre
UPDATE inventory_items SET unit_price = 32000.00    WHERE item_id = 'INV-008' AND unit_price = 220.00;    -- PCC pole 10m
UPDATE inventory_items SET unit_price = 1200.00     WHERE item_id = 'INV-009' AND unit_price = 35.00;     -- Porcelain insulator
UPDATE inventory_items SET unit_price = 3200.00     WHERE item_id = 'INV-010' AND unit_price = 9.50;      -- Copper conductor, per kg
-- Operational
UPDATE inventory_items SET unit_price = 18000.00    WHERE item_id = 'INV-011' AND unit_price = 120.00;    -- AMI smart meter
UPDATE inventory_items SET unit_price = 25000.00    WHERE item_id = 'INV-012' AND unit_price = 250.00;    -- Lineman safety kit
UPDATE inventory_items SET unit_price = 9000000.00  WHERE item_id = 'INV-013' AND unit_price = 38000.00;  -- Maintenance vehicle (pickup)
UPDATE inventory_items SET unit_price = 18000.00    WHERE item_id = 'INV-014' AND unit_price = 95.00;     -- Heavy-duty toolbox
UPDATE inventory_items SET unit_price = 55000.00    WHERE item_id = 'INV-015' AND unit_price = 310.00;    -- Handheld radio

-- Open (not yet finalized) procurement orders still carrying an old seed
-- price are re-priced to match. Delivered/cancelled orders keep their
-- historical numbers.
UPDATE procurement_orders o
   SET unit_price = i.unit_price, total_price = ROUND(o.quantity * i.unit_price, 2)
  FROM inventory_items i
 WHERE i.item_id = o.item_id
   AND o.stage NOT IN ('Delivered', 'Cancelled', 'Rejected', 'Completed')
   AND o.unit_price IS NOT NULL
   AND o.unit_price < i.unit_price / 20;

-- Who recorded a manual bank transfer
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS payout_confirmed_by UUID REFERENCES users(id);

CREATE INDEX IF NOT EXISTS idx_vendor_orders_payout_awaiting ON vendor_orders (payout_status)
    WHERE payout_status = 'Awaiting Transfer';
