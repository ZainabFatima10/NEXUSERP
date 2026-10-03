-- ============================================================
-- NEXUS ERP — Migration 009
-- Vendor registration -> admin vetting -> approved vendor catalogue
-- (Phase 1 of the vendor/procurement/shipment/payment expansion — see
-- VENDOR_ONBOARDING.md). Additive only: existing `vendors` and
-- `inventory_items`/`procurement_orders` FKs into it are untouched — this
-- only widens `vendors` with vetting fields and adds four new tables.
-- Idempotent — safe to re-run on every startup.
-- ============================================================

-- Sequential application reference codes: VND-APP-000123
CREATE SEQUENCE IF NOT EXISTS vendor_application_seq START 1;

-- ============================================================
-- VENDOR APPLICATIONS — public "Become a Vendor" submissions
-- ============================================================
CREATE TABLE IF NOT EXISTS vendor_applications (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reference_code          VARCHAR(20) UNIQUE NOT NULL
                            DEFAULT ('VND-APP-' || LPAD(nextval('vendor_application_seq')::text, 6, '0')),

    -- Step 1 — Company details
    legal_company_name     VARCHAR(255) NOT NULL,
    trade_name              VARCHAR(255),
    business_type           VARCHAR(50) NOT NULL,
    -- Manufacturer | Distributor | Authorized Dealer | Service Provider | Other
    ntn                      VARCHAR(50) NOT NULL,
    strn                     VARCHAR(50),
    secp_number              VARCHAR(50),
    year_established         INTEGER,
    employee_range           VARCHAR(50),
    website                  VARCHAR(255),
    categories               JSONB NOT NULL DEFAULT '[]',   -- subset of inventory_items.category

    -- Step 2 — Contact & location
    contact_name             VARCHAR(255) NOT NULL,
    contact_designation      VARCHAR(100),
    order_email              VARCHAR(255) NOT NULL,
    email_verified           BOOLEAN NOT NULL DEFAULT FALSE,
    email_verify_token       VARCHAR(128),
    email_verify_sent_at     TIMESTAMPTZ,
    email_verified_at        TIMESTAMPTZ,
    mobile                   VARCHAR(30) NOT NULL,
    alternate_phone          VARCHAR(30),
    address                   TEXT NOT NULL,
    city                      VARCHAR(100) NOT NULL,
    province                  VARCHAR(100) NOT NULL,
    postal_code                VARCHAR(20),
    coverage_provinces        JSONB NOT NULL DEFAULT '[]',
    coverage_cities            JSONB NOT NULL DEFAULT '[]',

    -- Step 3 — Commercial terms
    lead_time_days            INTEGER,
    payment_terms             VARCHAR(100),
    min_order_value           NUMERIC(14,2),
    warranty                   VARCHAR(255),
    bank_name                  VARCHAR(100),      -- "for verification only" — never in public listings
    bank_account_title         VARCHAR(255),
    bank_iban                  VARCHAR(34),
    certifications              JSONB NOT NULL DEFAULT '[]',

    -- Step 6 — review / workflow state
    status                      VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending | approved | rejected | needs_info
    submitted_at                TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reviewed_by                 UUID REFERENCES users(id),
    reviewed_at                 TIMESTAMPTZ,
    rejection_reason             TEXT,
    admin_notes                  TEXT,
    vetting_checklist            JSONB NOT NULL DEFAULT '{}',
    -- {ntn_verified, registration_verified, documents_reviewed, prices_reasonable, order_email_verified}
    approved_vendor_id            UUID REFERENCES vendors(id),
    applicant_ip                   VARCHAR(64),
    honeypot_triggered             BOOLEAN NOT NULL DEFAULT FALSE,

    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vendor_applications_status ON vendor_applications(status);
CREATE INDEX IF NOT EXISTS idx_vendor_applications_email  ON vendor_applications(order_email);

-- ============================================================
-- VENDOR APPLICATION DOCUMENTS — NTN/registration certs, brochures
-- Stored outside the web root — only a randomized filename lives on disk.
-- ============================================================
CREATE TABLE IF NOT EXISTS vendor_application_documents (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id      UUID NOT NULL REFERENCES vendor_applications(id) ON DELETE CASCADE,
    doc_type            VARCHAR(50) NOT NULL,
    -- ntn_certificate | registration_certificate | brochure | authorization_letter | other
    original_filename   VARCHAR(255),
    stored_filename      VARCHAR(255) NOT NULL,   -- random token — actual path is data/vendor_documents/<stored_filename>
    content_type          VARCHAR(100),
    size_bytes             INTEGER,
    uploaded_at             TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vendor_app_docs_application ON vendor_application_documents(application_id);

-- ============================================================
-- VENDOR APPLICATION ITEMS — staged catalogue (manual rows + parsed
-- upload rows merged together), copied into vendor_items on approval.
-- ============================================================
CREATE TABLE IF NOT EXISTS vendor_application_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    application_id      UUID NOT NULL REFERENCES vendor_applications(id) ON DELETE CASCADE,
    name                 VARCHAR(255) NOT NULL,
    sku                   VARCHAR(100),
    category               VARCHAR(50),
    description             TEXT,
    unit                     VARCHAR(50) NOT NULL,
    unit_price                NUMERIC(14,2) NOT NULL,
    moq                         NUMERIC(12,2),
    lead_time_days               INTEGER,
    row_source                    VARCHAR(20) NOT NULL DEFAULT 'manual',  -- manual | upload
    created_at                      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vendor_app_items_application ON vendor_application_items(application_id);

-- ============================================================
-- VENDOR ITEMS — live catalogue for approved vendors (what they sell).
-- Distinct from inventory_items (the DISCO's own internal stock master).
-- ============================================================
CREATE TABLE IF NOT EXISTS vendor_items (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vendor_id            UUID NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
    name                  VARCHAR(255) NOT NULL,
    sku                    VARCHAR(100),
    category                VARCHAR(50),
    description               TEXT,
    unit                       VARCHAR(50) NOT NULL,
    unit_price                  NUMERIC(14,2) NOT NULL,
    moq                           NUMERIC(12,2),
    lead_time_days                 INTEGER,
    is_active                        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at                         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                           TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_vendor_items_vendor ON vendor_items(vendor_id);
CREATE INDEX IF NOT EXISTS idx_vendor_items_category ON vendor_items(category);

-- ============================================================
-- VENDORS — widen the existing minimal table with vetting fields.
-- Backfill: every pre-existing vendor becomes status='active' (the
-- column DEFAULT applies to existing rows too) and order_email=email —
-- i.e. legacy vendors are treated as already-approved, so nothing in
-- procurement.py / inventory_v2.py (which only ever read id/name/email)
-- breaks.
-- ============================================================
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS status                VARCHAR(20) NOT NULL DEFAULT 'active';
-- active | suspended
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS order_email            VARCHAR(255);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS trade_name              VARCHAR(255);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS business_type            VARCHAR(50);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS ntn                        VARCHAR(50);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS strn                         VARCHAR(50);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS secp_number                   VARCHAR(50);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS year_established                INTEGER;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS employee_range                    VARCHAR(50);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS website                             VARCHAR(255);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS categories                           JSONB NOT NULL DEFAULT '[]';
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS contact_name                           VARCHAR(255);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS contact_designation                     VARCHAR(100);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS mobile                                     VARCHAR(30);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS alternate_phone                             VARCHAR(30);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS address                                       TEXT;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS city                                             VARCHAR(100);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS province                                          VARCHAR(100);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS postal_code                                         VARCHAR(20);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS coverage_provinces                                    JSONB NOT NULL DEFAULT '[]';
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS coverage_cities                                         JSONB NOT NULL DEFAULT '[]';
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS lead_time_days                                            INTEGER;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS payment_terms                                              VARCHAR(100);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS min_order_value                                             NUMERIC(14,2);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS warranty                                                      VARCHAR(255);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS bank_name                                                      VARCHAR(100);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS bank_account_title                                              VARCHAR(255);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS bank_iban                                                         VARCHAR(34);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS certifications                                                     JSONB NOT NULL DEFAULT '[]';
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS email_verified                                                      BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS application_id                                                       UUID REFERENCES vendor_applications(id);
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS approved_at                                                            TIMESTAMPTZ NOT NULL DEFAULT NOW();
ALTER TABLE vendors ADD COLUMN IF NOT EXISTS approved_by                                                             UUID REFERENCES users(id);

-- Backfill order_email for pre-existing vendors (new column has no DEFAULT,
-- so unlike `status` above this needs an explicit UPDATE — safe to re-run,
-- only touches rows that still have it NULL).
UPDATE vendors SET order_email = email WHERE order_email IS NULL;

CREATE INDEX IF NOT EXISTS idx_vendors_status ON vendors(status);
