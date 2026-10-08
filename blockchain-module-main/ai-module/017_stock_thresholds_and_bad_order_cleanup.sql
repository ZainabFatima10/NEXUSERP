-- ============================================================
-- NEXUS ERP — Migration 017
-- 1. New stock-label thresholds. Stock % = current_stock / min_threshold
--    x 100 (unchanged formula). Critical < 21% (0% / out of stock
--    included), Low 21% to 35%, OK >= 36%. Recompute every stored
--    inventory_items.status to match stock_thresholds.py.
--    An item with min_threshold <= 0 counts as 100% (OK), as in the app.
-- 2. Remove the invalid manual order ORD-6B5FD6 (quantity -110,
--    total PKR -352,000) and the rows that point at it: its
--    vendor_comm_log send record, any delivery check-ins, and its
--    notifications. One statement, so it is all-or-nothing. It deletes
--    nothing if the order has a smart-contract audit record (those are
--    left for a manual decision), and is a no-op once the order is gone
--    or on a fresh database.
--
-- Idempotent — safe to re-run on every startup.
-- ============================================================

UPDATE inventory_items
SET status = CASE
        WHEN min_threshold <= 0                                  THEN 'OK'
        WHEN current_stock * 100.0 / min_threshold < 21          THEN 'Critical'
        WHEN current_stock * 100.0 / min_threshold < 36          THEN 'Low'
        ELSE 'OK'
    END
WHERE status IS DISTINCT FROM CASE
        WHEN min_threshold <= 0                                  THEN 'OK'
        WHEN current_stock * 100.0 / min_threshold < 21          THEN 'Critical'
        WHEN current_stock * 100.0 / min_threshold < 36          THEN 'Low'
        ELSE 'OK'
    END;

WITH bad AS (
    SELECT o.id, o.order_code
    FROM procurement_orders o
    WHERE o.order_code = 'ORD-6B5FD6'
      AND o.quantity <= 0
      AND NOT EXISTS (SELECT 1 FROM contract_audit_log a WHERE a.order_id = o.id)
),
del_comm AS (
    DELETE FROM vendor_comm_log WHERE order_id IN (SELECT id FROM bad)
),
del_checkins AS (
    DELETE FROM delivery_checkins WHERE order_id IN (SELECT id FROM bad)
),
del_notifications AS (
    DELETE FROM notifications
    WHERE EXISTS (SELECT 1 FROM bad)
      AND (metadata->>'order_code' = 'ORD-6B5FD6'
           OR metadata->>'order_id' IN (SELECT id::text FROM bad)
           OR title LIKE '%ORD-6B5FD6%')
)
DELETE FROM procurement_orders WHERE id IN (SELECT id FROM bad);
