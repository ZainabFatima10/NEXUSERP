-- ============================================================
-- NEXUS ERP — Migration 010
-- Phase 2: order -> vendor accept (n8n) -> real on-chain smart contract
-- (ShipmentEscrow, see blockchain-module-main/hardhat/) -> shipment
-- tracking -> orderer approval/dispute -> execution.
--
-- Entirely new tables — does not touch procurement_orders (the existing
-- low-stock auto-reorder / manual internal-inventory flow keeps working
-- unchanged). vendor_orders is the new order entity for orders placed
-- against the Phase 1 approved vendor catalogue (vendor_items), with the
-- richer destination/orderer/shipment/contract lifecycle this phase adds.
--
-- Idempotent — safe to re-run on every startup.
-- ============================================================

-- ============================================================
-- VENDOR ORDERS — the new "Order" entity (orderer = sole Receiver)
-- ============================================================
CREATE TABLE IF NOT EXISTS vendor_orders (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_code                  VARCHAR(20) UNIQUE NOT NULL,      -- VO-XXXXXX

    vendor_id                   UUID NOT NULL REFERENCES vendors(id),
    orderer_user_id             UUID NOT NULL REFERENCES users(id),

    destination_name            VARCHAR(255) NOT NULL,
    destination_city            VARCHAR(100),
    destination_address         TEXT,

    requested_delivery_date     DATE,
    subtotal                    NUMERIC(14,2) NOT NULL,
    total_amount                NUMERIC(14,2) NOT NULL,
    currency                    VARCHAR(10) NOT NULL DEFAULT 'PKR',

    status                      VARCHAR(20) NOT NULL DEFAULT 'PENDING_VENDOR',
    -- PENDING_VENDOR | ACCEPTED | REJECTED | EXPIRED | CANCELLED
    vendor_rejection_reason      TEXT,
    vendor_responded_at         TIMESTAMPTZ,
    expires_at                  TIMESTAMPTZ NOT NULL,
    vendor_reminder_sent_at      TIMESTAMPTZ,    -- one nearing-expiry nudge to the vendor
    arrival_reminder_sent_at     TIMESTAMPTZ,    -- one "confirm arrival" nudge to the orderer
    approval_reminder_sent_at     TIMESTAMPTZ,   -- one "approve receipt" nudge to the orderer
    delay_notified_at              TIMESTAMPTZ,  -- one "this shipment is delayed" notice

    order_hash                  VARCHAR(66),   -- keccak256 of the accepted items/qty/prices
    destination_hash            VARCHAR(66),   -- keccak256 of the destination string
    chain_order_id               VARCHAR(66),  -- keccak256(order_code) -- the on-chain mapping key
    chain_network                VARCHAR(20),  -- hardhat | localhost | sepolia
    contract_status               VARCHAR(20) NOT NULL DEFAULT 'Not Created',
    -- Not Created | Preparing | Dispatched | InTransit | OutForDelivery |
    -- Arrived | Approved | Executed | Disputed | Cancelled

    payment_status                 VARCHAR(20) NOT NULL DEFAULT 'Not Required',
    -- Not Required | Payment Required | Authorized | Captured | Cancelled | Failed
    -- (Phase 4 placeholder -- mocked behind payment_mock_service.py for now)
    payment_ref                      VARCHAR(100),

    dispute_reason                     TEXT,
    dispute_opened_at                    TIMESTAMPTZ,
    dispute_resolved_at                     TIMESTAMPTZ,
    dispute_resolution                       VARCHAR(20),
    dispute_resolution_notes                   TEXT,

    cancelled_at                                 TIMESTAMPTZ,
    cancelled_by                                   UUID REFERENCES users(id),

    created_at                                       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                                          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vendor_orders_vendor    ON vendor_orders(vendor_id);
CREATE INDEX IF NOT EXISTS idx_vendor_orders_orderer   ON vendor_orders(orderer_user_id);
CREATE INDEX IF NOT EXISTS idx_vendor_orders_status    ON vendor_orders(status);
CREATE INDEX IF NOT EXISTS idx_vendor_orders_cstatus   ON vendor_orders(contract_status);

-- ============================================================
-- VENDOR ORDER ITEMS — snapshot of items/qty/price at order time (the
-- orderHash's source data) -- kept even if vendor_items later changes.
-- ============================================================
CREATE TABLE IF NOT EXISTS vendor_order_items (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES vendor_orders(id) ON DELETE CASCADE,
    vendor_item_id  UUID REFERENCES vendor_items(id) ON DELETE SET NULL,
    name            VARCHAR(255) NOT NULL,
    sku             VARCHAR(100),
    unit            VARCHAR(50) NOT NULL,
    quantity        NUMERIC(12,2) NOT NULL,
    unit_price      NUMERIC(14,2) NOT NULL,
    line_total      NUMERIC(14,2) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_vendor_order_items_order ON vendor_order_items(order_id);

-- ============================================================
-- VENDOR ORDER TOKENS — signed, no-login vendor action links.
-- 'respond' (accept/reject): single-use, short expiry (default 72h).
-- 'ship_update' (dispatch/checkpoint): multi-use, long expiry (30 days),
-- rate-limited at the application layer rather than here.
-- Only a hash of the token is stored -- the raw token exists only in the
-- emailed link, never persisted.
-- ============================================================
CREATE TABLE IF NOT EXISTS vendor_order_tokens (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id    UUID NOT NULL REFERENCES vendor_orders(id) ON DELETE CASCADE,
    purpose     VARCHAR(20) NOT NULL,
    token_hash  VARCHAR(128) NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    used_at     TIMESTAMPTZ,
    revoked_at  TIMESTAMPTZ,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vendor_order_tokens_order ON vendor_order_tokens(order_id);
CREATE INDEX IF NOT EXISTS idx_vendor_order_tokens_hash  ON vendor_order_tokens(token_hash);

-- ============================================================
-- SHIPMENTS — off-chain index of the on-chain shipment state (the chain
-- is the source of truth -- this table + shipment_events exist so the
-- Order Tracking UI can query fast without round-tripping to a node).
-- ============================================================
CREATE TABLE IF NOT EXISTS shipments (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id                    UUID UNIQUE NOT NULL REFERENCES vendor_orders(id) ON DELETE CASCADE,
    status                      VARCHAR(20) NOT NULL DEFAULT 'Preparing',
    carrier                     VARCHAR(100),
    tracking_no                 VARCHAR(100),
    dispatch_date                DATE,
    eta                           DATE,
    dispatch_document_filename     VARCHAR(255),
    created_at                       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                         TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- SHIPMENT EVENTS — full timeline, one row per checkpoint/status change,
-- carrying the on-chain tx hash once confirmed.
-- ============================================================
CREATE TABLE IF NOT EXISTS shipment_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id            UUID NOT NULL REFERENCES vendor_orders(id) ON DELETE CASCADE,
    status              VARCHAR(20) NOT NULL,
    location            VARCHAR(255),
    note                TEXT,
    actor_type          VARCHAR(20) NOT NULL,
    -- vendor_link | staff | receiver | system
    actor_user_id       UUID REFERENCES users(id),
    actor_label         VARCHAR(255),
    tx_hash             VARCHAR(80),
    block_number        BIGINT,
    chain_confirmed_at  TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_shipment_events_order ON shipment_events(order_id);

-- ============================================================
-- USER WALLETS — backend-custodied signing key per user, so the on-chain
-- Receiver role is a real per-user address (confirmArrival/approveReceipt/
-- dispute are signed with the actual orderer's key, not a shared backend
-- key) without requiring end users to run their own wallet software. The
-- private key is encrypted at rest (Fernet, WALLET_ENCRYPTION_KEY env var)
-- and is only ever decrypted in memory, momentarily, to sign a transaction.
-- ============================================================
CREATE TABLE IF NOT EXISTS user_wallets (
    user_id                UUID PRIMARY KEY REFERENCES users(id),
    address                VARCHAR(42) NOT NULL,
    encrypted_private_key  TEXT NOT NULL,
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================
-- CHAIN TX QUEUE — every on-chain call is written here BEFORE being
-- attempted (so a crash mid-call loses nothing), then attempted
-- immediately. On failure it stays 'pending' for the scheduler to retry
-- with backoff — the user-facing action it was part of already succeeded
-- off-chain ("pending on-chain confirmation" in the UI) -- a chain hiccup
-- never blocks the business action. On success it's marked 'confirmed'
-- and the matching shipment_events row gets its tx_hash/block_number.
-- ============================================================
CREATE TABLE IF NOT EXISTS chain_tx_queue (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id            UUID NOT NULL REFERENCES vendor_orders(id) ON DELETE CASCADE,
    action              VARCHAR(30) NOT NULL,
    -- create_contract | record_checkpoint | confirm_arrival | approve_receipt
    -- | dispute | resolve_dispute | cancel
    payload             JSONB NOT NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending | confirmed | failed
    attempts            INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    tx_hash             VARCHAR(80),
    block_number        BIGINT,
    shipment_event_id   UUID REFERENCES shipment_events(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chain_tx_queue_status ON chain_tx_queue(status);
CREATE INDEX IF NOT EXISTS idx_chain_tx_queue_order  ON chain_tx_queue(order_id);
