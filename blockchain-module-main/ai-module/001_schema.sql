-- ============================================================
-- NEXUS ERP — Module 2 Database Schema
-- PostgreSQL 14+ / TimescaleDB compatible
-- Run: psql -U nexus_user -d nexus_erp -f 001_schema.sql
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- ============================================================
-- USERS & AUTH
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) UNIQUE NOT NULL,
    password_hash   VARCHAR(255) NOT NULL,
    role            VARCHAR(50) NOT NULL DEFAULT 'Operator',
    -- role: Admin | Manager | Operator | Vendor
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- VENDORS
-- ============================================================
CREATE TABLE IF NOT EXISTS vendors (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name            VARCHAR(255) NOT NULL,
    email           VARCHAR(255) NOT NULL,
    phone           VARCHAR(50),
    country         VARCHAR(100),
    is_active       BOOLEAN DEFAULT TRUE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- INVENTORY ITEMS (master table)
-- ============================================================
CREATE TABLE IF NOT EXISTS inventory_items (
    item_id             VARCHAR(20) PRIMARY KEY,   -- INV-001 etc.
    name                VARCHAR(255) NOT NULL,
    category            VARCHAR(50) NOT NULL,
    unit                VARCHAR(50) NOT NULL,
    min_threshold       INTEGER NOT NULL,
    critical_threshold  INTEGER NOT NULL,          -- 20% of min_threshold
    current_stock       NUMERIC(12,2) NOT NULL DEFAULT 0,
    daily_consumption   NUMERIC(10,2) NOT NULL DEFAULT 0,
    reorder_quantity    INTEGER NOT NULL,
    vendor_id           UUID REFERENCES vendors(id) ON DELETE SET NULL,
    status              VARCHAR(20) NOT NULL DEFAULT 'OK',
    -- status: OK | Low | Critical
    days_until_reorder  INTEGER,
    days_until_critical INTEGER,
    last_updated        TIMESTAMPTZ DEFAULT NOW(),
    created_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- PROCUREMENT ORDERS
-- ============================================================
CREATE TABLE IF NOT EXISTS procurement_orders (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_code          VARCHAR(20) UNIQUE NOT NULL,    -- ORD-XXXXXX
    item_id             VARCHAR(20) NOT NULL REFERENCES inventory_items(item_id),
    vendor_id           UUID NOT NULL REFERENCES vendors(id),
    quantity            NUMERIC(12,2) NOT NULL,
    unit                VARCHAR(50) NOT NULL,
    unit_price          NUMERIC(12,2),
    total_price         NUMERIC(14,2),

    -- Trigger info
    trigger_type        VARCHAR(30) NOT NULL,
    -- VEMA-Triggered | Auto-Generated | Manual
    triggered_by        UUID REFERENCES users(id),
    triggered_at        TIMESTAMPTZ DEFAULT NOW(),

    -- Lifecycle stage
    stage               VARCHAR(50) NOT NULL DEFAULT 'Pending Verification',
    -- Pending Verification | Vendor Notified | Email Confirmed |
    -- Contract Signed | Manufacturing | Shipping | Delivered | Cancelled

    -- Vendor email flow
    vendor_email_sent   BOOLEAN DEFAULT FALSE,
    vendor_email_sent_at TIMESTAMPTZ,
    vendor_confirmed    BOOLEAN DEFAULT FALSE,
    vendor_confirmed_at TIMESTAMPTZ,
    vendor_confirm_token VARCHAR(64) UNIQUE,  -- secure token in email link

    -- Smart contract (simulated Hyperledger Fabric)
    contract_status     VARCHAR(30) DEFAULT 'Pending',
    -- Pending | Signed | Executed | Rejected
    contract_hash       VARCHAR(128),        -- tx hash on ledger
    contract_signed_at  TIMESTAMPTZ,
    contract_executed_at TIMESTAMPTZ,
    smart_contract_data JSONB,               -- full contract payload

    -- Delivery
    expected_delivery   DATE,
    actual_delivery     DATE,
    delivery_confirmed  BOOLEAN DEFAULT FALSE,
    delivery_confirmed_at TIMESTAMPTZ,
    delivery_confirmed_by UUID REFERENCES users(id),
    delivery_notes      TEXT,
    delivery_condition  VARCHAR(30),         -- Good | Partial | Damaged

    -- Tracking
    tracking_number     VARCHAR(100),
    tracking_events     JSONB DEFAULT '[]',  -- array of {ts, status, location, notes}

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- NOTIFICATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS notifications (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    -- NULL = broadcast to all
    category    VARCHAR(50) NOT NULL,
    -- Confirmations | Updates | Resource Allocation | Outage Updates | User Complaints
    title       VARCHAR(255) NOT NULL,
    description TEXT NOT NULL,
    is_read     BOOLEAN DEFAULT FALSE,
    metadata    JSONB DEFAULT '{}',   -- e.g. {order_id, item_id, risk_level}
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- DELIVERY CHECK-IN LOG
-- Each scan / check-in event for an order
-- ============================================================
CREATE TABLE IF NOT EXISTS delivery_checkins (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES procurement_orders(id),
    checked_by      UUID REFERENCES users(id),
    checkin_at      TIMESTAMPTZ DEFAULT NOW(),
    location        VARCHAR(255),
    status          VARCHAR(50) NOT NULL,
    -- In Transit | Arrived at Warehouse | Inspected | Accepted | Rejected
    quantity_received NUMERIC(12,2),
    condition       VARCHAR(30),    -- Good | Partial | Damaged
    notes           TEXT,
    photo_url       VARCHAR(512),   -- optional attachment
    is_final        BOOLEAN DEFAULT FALSE  -- TRUE = closes delivery
);

-- ============================================================
-- SMART CONTRACT AUDIT LOG
-- Every state transition on a contract is logged immutably
-- ============================================================
CREATE TABLE IF NOT EXISTS contract_audit_log (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    order_id        UUID NOT NULL REFERENCES procurement_orders(id),
    action          VARCHAR(50) NOT NULL,
    -- Created | VendorSigned | OperatorSigned | Executed | Rejected
    performed_by    UUID REFERENCES users(id),
    tx_hash         VARCHAR(128),
    block_number    INTEGER,
    payload         JSONB,
    performed_at    TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- OUTAGE FORECAST (from Module 1 — referenced here for dashboard)
-- ============================================================
CREATE TABLE IF NOT EXISTS forecast_results (
    id                  SERIAL PRIMARY KEY,
    generated_at        TIMESTAMPTZ DEFAULT NOW(),
    forecast_date       DATE NOT NULL,
    demand_kwh          FLOAT,
    outage_probability  FLOAT,
    risk_level          VARCHAR(10),
    affected_zones      TEXT,
    weather_factors     TEXT,
    recommended_actions TEXT
);

-- ============================================================
-- INDEXES
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_orders_item      ON procurement_orders(item_id);
CREATE INDEX IF NOT EXISTS idx_orders_vendor    ON procurement_orders(vendor_id);
CREATE INDEX IF NOT EXISTS idx_orders_stage     ON procurement_orders(stage);
CREATE INDEX IF NOT EXISTS idx_orders_created   ON procurement_orders(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_notif_user       ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_notif_created    ON notifications(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_checkins_order   ON delivery_checkins(order_id);
CREATE INDEX IF NOT EXISTS idx_audit_order      ON contract_audit_log(order_id);
CREATE INDEX IF NOT EXISTS idx_inventory_status ON inventory_items(status);

-- ============================================================
-- SEED: Vendors
-- ============================================================
INSERT INTO vendors (id, name, email, country) VALUES
  ('11111111-0000-0000-0000-000000000001', 'Siemens AG',      'orders@siemens.com',  'Germany'),
  ('11111111-0000-0000-0000-000000000002', 'ABB Ltd',         'orders@abb.com',      'Switzerland'),
  ('11111111-0000-0000-0000-000000000003', 'Nexans',          'orders@nexans.com',   'France'),
  ('11111111-0000-0000-0000-000000000004', 'NGK Insulators',  'orders@ngk.com',      'Japan'),
  ('11111111-0000-0000-0000-000000000005', 'Schneider',       'orders@schneider.com','France'),
  ('11111111-0000-0000-0000-000000000006', 'Prysmian Group',  'orders@prysmian.com', 'Italy')
ON CONFLICT DO NOTHING;

-- ============================================================
-- SEED: Inventory Items
-- ============================================================
INSERT INTO inventory_items
  (item_id, name, category, unit, min_threshold, critical_threshold, current_stock,
   daily_consumption, reorder_quantity, vendor_id, status)
VALUES
  -- Generation
  ('INV-001','Generators (500kW)','Generation','units',100,20,150,2.5,100, '11111111-0000-0000-0000-000000000001','OK'),
  ('INV-002','Solar Panels (250W)','Generation','units',500,100,1200,15,500, '11111111-0000-0000-0000-000000000002','OK'),
  ('INV-003','Wind Turbine Blades','Generation','units',50,10,35,1.2,50, '11111111-0000-0000-0000-000000000003','Low'),
  ('INV-004','Diesel Fuel (Litres)','Generation','litres',10000,2000,25000,500,10000, '11111111-0000-0000-0000-000000000004','OK'),
  ('INV-005','Steam Turbines','Generation','units',20,4,15,0.5,20, '11111111-0000-0000-0000-000000000005','Low'),
  -- Infrastructure
  ('INV-006','Distribution Transformers (11kV)','Infrastructure','units',500,100,142,5,500, '11111111-0000-0000-0000-000000000001','Critical'),
  ('INV-007','Power Cables (HT)','Infrastructure','meters',5000,1000,8500,120,5000, '11111111-0000-0000-0000-000000000003','OK'),
  ('INV-008','Concrete Poles (10m)','Infrastructure','units',1000,200,1200,10,1000, '11111111-0000-0000-0000-000000000002','OK'),
  ('INV-009','Insulators (Porcelain)','Infrastructure','units',500,100,312,15,500, '11111111-0000-0000-0000-000000000004','Low'),
  ('INV-010','Copper Conductors','Infrastructure','kg',1000,200,2,45.0,2000, '11111111-0000-0000-0000-000000000006','Critical'),
  -- Operational
  ('INV-011','Smart Meters (AMI)','Operational','units',200,40,4,8.0,400, '11111111-0000-0000-0000-000000000001','Critical'),
  ('INV-012','Lineman Safety Kits','Operational','kits',50,10,45,2,50, '11111111-0000-0000-0000-000000000005','Low'),
  ('INV-013','Maintenance Vehicles','Operational','units',20,4,18,0.5,20, '11111111-0000-0000-0000-000000000006','Low'),
  ('INV-014','Toolboxes (Heavy Duty)','Operational','units',100,20,80,1,100, '11111111-0000-0000-0000-000000000002','Low'),
  ('INV-015','Radio Communicators','Operational','units',50,10,48,0.5,50, '11111111-0000-0000-0000-000000000004','OK')
ON CONFLICT DO NOTHING;

-- ============================================================
-- SEED: Admin user (password: nexus2026)
-- hash generated with: SELECT crypt('nexus2026', gen_salt('bf'))
-- ============================================================
INSERT INTO users (id, name, email, password_hash, role) VALUES
  ('aaaaaaaa-0000-0000-0000-000000000001',
   'Admin User',
   'admin@nexus.pk',
   '$2a$06$H.wMYmMUPv9e.Q8nE7YWaOWTrPYy5Dm3/3jxCuJzSmgmMvj5jfSHm',
   'Admin')
ON CONFLICT DO NOTHING;
