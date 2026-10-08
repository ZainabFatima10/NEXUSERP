-- ============================================================
-- NEXUS ERP — Migration 015
-- VEMA-triggered automatic reorders with an approval gate.
--
-- Additive, parallel to the existing <=20%-of-min_threshold auto-trigger
-- (inventory_v2.run_inventory_check -> procurement.create_pending_approval_order,
-- see procurement.py's "AUTOMATED REORDERING" section) -- that flow is
-- untouched and keeps working exactly as before. This one is richer: a
-- deterministic quantity + ranked-vendor proposal with a plain-English
-- rationale sits in 'pending_approval' BEFORE any procurement_orders row
-- exists, so a Procurement Manager/Admin reviews the proposal itself, not
-- an already-created order. On approval, the real order is created via the
-- EXISTING create_pending_approval_order() + approve_reorder() functions
-- in procurement.py -- reused as-is, never duplicated. See
-- vema_reorder_service.py and docs/VEMA_AUTO_REORDER.md.
--
-- Idempotent -- safe to re-run on every startup.
-- ============================================================

-- "par"/target stock level to refill up to -- no such column existed
-- before (only min_threshold, the reorder POINT, and critical_threshold,
-- 20% of it). Nullable: falls back to min_threshold * 2 at scan time
-- (matching inventory_v2.calculate_prediction's own dummy-forecast
-- heuristic) when unset — see VEMA_AUTO_REORDER.md "Configuration".
ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS max_stock_level INTEGER;

CREATE TABLE IF NOT EXISTS vema_reorder_requests (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_code            VARCHAR(20) UNIQUE NOT NULL,   -- VRO-2026-0001
    item_id                 VARCHAR(20) NOT NULL REFERENCES inventory_items(item_id),
    stock_at_trigger        NUMERIC(12,2) NOT NULL,
    par_level               INTEGER NOT NULL,
    threshold_pct           NUMERIC(5,2) NOT NULL,
    suggested_qty           INTEGER NOT NULL,
    unit_price_est          NUMERIC(14,2),
    total_est               NUMERIC(14,2),
    vendor_id               UUID REFERENCES vendors(id),
    alt_vendor_ids          JSONB NOT NULL DEFAULT '[]'::jsonb,
    vendor_score_breakdown  JSONB NOT NULL DEFAULT '{}'::jsonb,
    rationale               TEXT,
    status                  VARCHAR(20) NOT NULL DEFAULT 'pending_approval',
    -- pending_approval | approved | rejected | expired
    decided_by              UUID REFERENCES users(id),
    decided_at              TIMESTAMPTZ,
    decision_note           TEXT,
    edited_qty              INTEGER,
    edited_vendor_id        UUID REFERENCES vendors(id),
    resulting_order_id      UUID REFERENCES procurement_orders(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vema_reorder_requests_status ON vema_reorder_requests(status);
CREATE INDEX IF NOT EXISTS idx_vema_reorder_requests_item   ON vema_reorder_requests(item_id);
-- Cooldown/dedup queries filter by item_id + status + a recent time window —
-- this composite index covers both without a second lookup.
CREATE INDEX IF NOT EXISTS idx_vema_reorder_requests_item_status_time
    ON vema_reorder_requests(item_id, status, created_at);

-- Permanent audit trail (who did what, when) -- separate from notifications,
-- which are dismissible inbox items, not a record of truth.
CREATE TABLE IF NOT EXISTS vema_reorder_audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id  UUID NOT NULL REFERENCES vema_reorder_requests(id) ON DELETE CASCADE,
    action      VARCHAR(30) NOT NULL,   -- created | approved | rejected | expired
    actor_id    UUID REFERENCES users(id),
    note        TEXT,
    metadata    JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vema_reorder_audit_log_request ON vema_reorder_audit_log(request_id);
