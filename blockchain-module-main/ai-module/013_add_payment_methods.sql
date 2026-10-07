-- ============================================================
-- NEXUS ERP — Migration 013
-- Payments: organisation payment methods (PKR only), a per-order payment
-- ledger, and the vendor payout stage that follows contract execution.
--
-- Money flow for a vendor order (see SHIPMENT_ESCROW.md, "Payments"):
--   vendor accepts      -> authorize total_amount against the default
--                          payment method (funds held in escrow)
--   receipt approved    -> contract executes on-chain, hold is captured,
--                          vendor payout is scheduled (payout_due_at)
--   payout due          -> scheduler pays vendor_payout_amount to the
--                          vendor's IBAN on file, vendor is emailed
--
-- All money in this system is Pakistani Rupees. Enforced by CHECK
-- constraints here, not just by convention in the application code.
--
-- Idempotent — safe to re-run on every startup.
-- ============================================================

-- ============================================================
-- PAYMENT METHODS — where the organisation pays from.
-- method_type: bank_transfer | raast | jazzcash | easypaisa
-- account_identifier is an IBAN (bank_transfer), a Raast ID or IBAN
-- (raast), or a mobile wallet number (jazzcash/easypaisa). Only ever
-- returned masked by the API.
-- ============================================================
CREATE TABLE IF NOT EXISTS payment_methods (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    method_type         VARCHAR(20) NOT NULL,
    label               VARCHAR(100) NOT NULL,
    account_title       VARCHAR(255) NOT NULL,
    bank_name           VARCHAR(100),
    account_identifier  VARCHAR(34) NOT NULL,
    currency            VARCHAR(3) NOT NULL DEFAULT 'PKR' CHECK (currency = 'PKR'),
    is_default          BOOLEAN NOT NULL DEFAULT FALSE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_by          UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- At most one active default method at a time
CREATE UNIQUE INDEX IF NOT EXISTS uq_payment_methods_single_default
    ON payment_methods (is_default) WHERE is_default AND is_active;

-- ============================================================
-- VENDOR ORDERS — fee split, payment timestamps, payout stage
-- payout_status: Not Scheduled | Scheduled | Paid | Failed | Not Applicable
-- ============================================================
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS platform_fee          NUMERIC(14,2) NOT NULL DEFAULT 0;
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS vendor_payout_amount  NUMERIC(14,2);
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS payment_method_id     UUID REFERENCES payment_methods(id);
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS payment_authorized_at TIMESTAMPTZ;
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS payment_captured_at   TIMESTAMPTZ;
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS payout_status         VARCHAR(20) NOT NULL DEFAULT 'Not Scheduled';
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS payout_due_at         TIMESTAMPTZ;
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS payout_paid_at        TIMESTAMPTZ;
ALTER TABLE vendor_orders ADD COLUMN IF NOT EXISTS payout_ref            VARCHAR(100);

-- Orders placed before this migration had no fee (total = subtotal), so
-- the vendor is owed the full subtotal.
UPDATE vendor_orders SET vendor_payout_amount = subtotal WHERE vendor_payout_amount IS NULL;

-- Backfill payout state for orders that already executed/cancelled
UPDATE vendor_orders SET payout_status = 'Scheduled', payout_due_at = updated_at
    WHERE contract_status = 'Executed' AND payment_status = 'Captured' AND payout_status = 'Not Scheduled';
UPDATE vendor_orders SET payout_status = 'Not Applicable'
    WHERE (status IN ('REJECTED', 'EXPIRED', 'CANCELLED') OR contract_status = 'Cancelled')
      AND payout_status = 'Not Scheduled';

-- PKR only
UPDATE vendor_orders SET currency = 'PKR' WHERE currency IS DISTINCT FROM 'PKR';
ALTER TABLE vendor_orders DROP CONSTRAINT IF EXISTS chk_vendor_orders_currency_pkr;
ALTER TABLE vendor_orders ADD CONSTRAINT chk_vendor_orders_currency_pkr CHECK (currency = 'PKR');

CREATE INDEX IF NOT EXISTS idx_vendor_orders_payout_due ON vendor_orders (payout_due_at)
    WHERE payout_status = 'Scheduled';

-- ============================================================
-- PAYMENT TRANSACTIONS — append-only audit trail of every money movement
-- kind: authorize | capture | cancel | payout
-- status: Succeeded | Failed | Skipped
-- ============================================================
CREATE TABLE IF NOT EXISTS payment_transactions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id            UUID NOT NULL REFERENCES vendor_orders(id) ON DELETE CASCADE,
    kind                VARCHAR(20) NOT NULL,
    amount              NUMERIC(14,2) NOT NULL,
    currency            VARCHAR(3) NOT NULL DEFAULT 'PKR' CHECK (currency = 'PKR'),
    status              VARCHAR(20) NOT NULL,
    provider_ref        VARCHAR(100),
    payment_method_id   UUID REFERENCES payment_methods(id),
    note                TEXT,
    actor_user_id       UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_payment_transactions_order ON payment_transactions(order_id);
