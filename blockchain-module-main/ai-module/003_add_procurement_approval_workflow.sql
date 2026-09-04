-- ============================================================
-- NEXUS ERP — Migration 003
-- Adds the Procurement Manager approval workflow on top of the existing
-- procurement_orders lifecycle (does NOT alter contract_service.py's
-- smart-contract logic or invoice_service.py's billing logic — this only
-- adds bookkeeping columns the new orchestration in procurement.py reads
-- and writes).
-- Idempotent — safe to re-run on every startup.
-- ============================================================

-- Pre-existing trigger_type VARCHAR(30) is too narrow for the existing
-- "Auto-Generated (Demand > Stock)" literal (32 chars) used in
-- inventory_v2.run_inventory_check() -- never caught before because
-- unit_price was NULL (see migration 002), so that code path never
-- actually reached the INSERT until unit_price started being populated.
ALTER TABLE procurement_orders ALTER COLUMN trigger_type TYPE VARCHAR(50);

ALTER TABLE procurement_orders ADD COLUMN IF NOT EXISTS below_20pct_trigger BOOLEAN DEFAULT FALSE;
-- TRUE = this order was auto-created because current_stock <= critical_threshold
-- (the "<20% of min_threshold" trigger in Section 3a). These orders sit in
-- 'Pending PM Approval' instead of emailing the vendor immediately.

ALTER TABLE procurement_orders ADD COLUMN IF NOT EXISTS pm_approval_status VARCHAR(20) NOT NULL DEFAULT 'Not Required';
-- Not Required | Pending | Approved | Rejected

ALTER TABLE procurement_orders ADD COLUMN IF NOT EXISTS pm_approved_by UUID REFERENCES users(id);
ALTER TABLE procurement_orders ADD COLUMN IF NOT EXISTS pm_approved_at TIMESTAMPTZ;
ALTER TABLE procurement_orders ADD COLUMN IF NOT EXISTS pm_decision_notes TEXT;

ALTER TABLE procurement_orders ADD COLUMN IF NOT EXISTS vendor_response_token VARCHAR(128);
ALTER TABLE procurement_orders ADD COLUMN IF NOT EXISTS vendor_decision VARCHAR(20);
-- Accepted | Rejected
ALTER TABLE procurement_orders ADD COLUMN IF NOT EXISTS vendor_responded_at TIMESTAMPTZ;
ALTER TABLE procurement_orders ADD COLUMN IF NOT EXISTS vendor_email_message_id VARCHAR(255);
-- n8n's execution/email id for the "resend" action in the vendor comms panel

ALTER TABLE procurement_orders DROP CONSTRAINT IF EXISTS procurement_orders_vendor_response_token_key;
ALTER TABLE procurement_orders ADD CONSTRAINT procurement_orders_vendor_response_token_key UNIQUE (vendor_response_token);

CREATE INDEX IF NOT EXISTS idx_orders_pm_approval ON procurement_orders(pm_approval_status);

-- ============================================================
-- Vendor communication log — one row per email attempt (send + resend),
-- so the Procurement Manager's "vendor communication panel" can show
-- send history independent of the order's current stage.
-- ============================================================
CREATE TABLE IF NOT EXISTS vendor_comm_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES procurement_orders(id),
    channel         VARCHAR(20) NOT NULL DEFAULT 'n8n-email',
    -- n8n-email | dev-console (n8n not configured)
    status          VARCHAR(20) NOT NULL,
    -- Sent | Failed | Simulated
    triggered_by    UUID REFERENCES users(id),
    response_body   TEXT,
    sent_at         TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_vendor_comm_order ON vendor_comm_log(order_id);
