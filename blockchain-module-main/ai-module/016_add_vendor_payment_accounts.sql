-- ============================================================
-- NEXUS ERP — Migration 016
-- Vendor payout accounts for the post-delivery payment release
-- ("step M" of the existing payments.py escrow -> capture -> payout
-- lifecycle, see SHIPMENT_ESCROW.md "Payments"). Additive only.
--
-- Distinct from vendors.bank_name/bank_account_title/bank_iban (added in
-- migration 009) -- those are the vendor's informal Commercial-Terms
-- contact banking details, entered with light validation, never encrypted,
-- and are left completely untouched by this migration. This new table is
-- the verified, encrypted-at-rest payout destination: payments.py's
-- release_payout() (step M) resolves where the money goes exclusively
-- through vendor_payment_accounts.get_vendor_payout_destination() going
-- forward, and only once an admin has marked the account 'verified'. See
-- VENDOR_PAYOUT_ACCOUNTS.md.
--
-- One row per application, reassigned (not duplicated) from
-- application_id to vendor_id at approval time -- same 1:1 relationship
-- the application itself has with its eventual vendor row.
--
-- Sensitive identifiers (IBAN / account number / wallet number) are never
-- stored in plaintext: each has an `_encrypted` column (Fernet, see
-- VENDOR_PAYOUT_ENCRYPTION_KEY in env.example), a `_last4` column for
-- display-safe masking without decrypting, and (for the two fields used in
-- cross-vendor duplicate detection -- IBAN and wallet number) a `_hash`
-- column (HMAC-SHA256, VENDOR_PAYOUT_HASH_KEY) that is unique-indexed so a
-- duplicate is rejected by the database itself, never by comparing
-- decrypted values in application code.
--
-- Idempotent -- safe to re-run on every startup.
-- ============================================================

CREATE TABLE IF NOT EXISTS vendor_payment_accounts (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id              UUID NOT NULL UNIQUE REFERENCES vendor_applications(id) ON DELETE CASCADE,
    vendor_id                   UUID REFERENCES vendors(id) ON DELETE CASCADE,
    -- NULL until the application is approved, then set once (see vendors.approve_vendor_application).

    payout_method                VARCHAR(20) NOT NULL,
    -- bank_account | mobile_wallet
    account_title                 VARCHAR(100) NOT NULL,

    -- bank_account fields
    bank_name                      VARCHAR(100),
    branch_code                     VARCHAR(20),
    iban_encrypted                   TEXT,
    iban_last4                        VARCHAR(4),
    iban_hash                          VARCHAR(64),
    account_number_encrypted            TEXT,
    account_number_last4                 VARCHAR(4),

    -- mobile_wallet fields
    wallet_provider                       VARCHAR(30),
    wallet_number_encrypted                 TEXT,
    wallet_last4                             VARCHAR(4),
    wallet_hash                               VARCHAR(64),

    verification_status                        VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending | verified | rejected
    verified_by                                 UUID REFERENCES users(id),
    verified_at                                  TIMESTAMPTZ,
    rejection_reason                              TEXT,

    created_at                                     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vendor_payment_accounts_vendor ON vendor_payment_accounts(vendor_id);
CREATE INDEX IF NOT EXISTS idx_vendor_payment_accounts_status ON vendor_payment_accounts(verification_status);

-- Cross-vendor duplicate detection -- a NULL hash (the field this payout
-- method doesn't use) never collides, since Postgres treats every NULL as
-- distinct in a unique index.
CREATE UNIQUE INDEX IF NOT EXISTS idx_vendor_payment_accounts_iban_hash
    ON vendor_payment_accounts(iban_hash) WHERE iban_hash IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_vendor_payment_accounts_wallet_hash
    ON vendor_payment_accounts(wallet_hash) WHERE wallet_hash IS NOT NULL;

-- Audit trail for reveal/verify/reject actions -- same shape/convention as
-- vema_reorder_audit_log (migration 015): a permanent record of truth,
-- separate from the dismissible notification inbox.
CREATE TABLE IF NOT EXISTS vendor_payment_account_audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    account_id  UUID NOT NULL REFERENCES vendor_payment_accounts(id) ON DELETE CASCADE,
    action      VARCHAR(20) NOT NULL,   -- reveal | verify | reject
    actor_id    UUID REFERENCES users(id),
    note        TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vendor_payment_account_audit_log_account ON vendor_payment_account_audit_log(account_id);
