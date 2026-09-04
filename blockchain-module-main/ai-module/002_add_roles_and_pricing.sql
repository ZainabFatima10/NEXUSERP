-- ============================================================
-- NEXUS ERP — Migration 002
-- Adds: RBAC role values (admin | customer_rep | procurement_manager | customer)
--       + backfills inventory_items.unit_price (referenced throughout the
--       app/docs since the procurement/invoice work, but missing from
--       001_schema.sql).
-- Idempotent — safe to run on every startup.
-- ============================================================

-- ------------------------------------------------------------
-- unit_price column (procurement.py / invoice_service.py / frontend
-- all assume this exists on inventory_items)
-- ------------------------------------------------------------
ALTER TABLE inventory_items ADD COLUMN IF NOT EXISTS unit_price NUMERIC(12,2);

UPDATE inventory_items SET unit_price = 5000.00  WHERE item_id = 'INV-001' AND unit_price IS NULL; -- Generators
UPDATE inventory_items SET unit_price = 180.00    WHERE item_id = 'INV-002' AND unit_price IS NULL; -- Solar Panels
UPDATE inventory_items SET unit_price = 12000.00  WHERE item_id = 'INV-003' AND unit_price IS NULL; -- Wind Turbine Blades
UPDATE inventory_items SET unit_price = 1.20      WHERE item_id = 'INV-004' AND unit_price IS NULL; -- Diesel Fuel
UPDATE inventory_items SET unit_price = 45000.00  WHERE item_id = 'INV-005' AND unit_price IS NULL; -- Steam Turbines
UPDATE inventory_items SET unit_price = 8500.00   WHERE item_id = 'INV-006' AND unit_price IS NULL; -- Distribution Transformers
UPDATE inventory_items SET unit_price = 15.00     WHERE item_id = 'INV-007' AND unit_price IS NULL; -- Power Cables
UPDATE inventory_items SET unit_price = 220.00    WHERE item_id = 'INV-008' AND unit_price IS NULL; -- Concrete Poles
UPDATE inventory_items SET unit_price = 35.00     WHERE item_id = 'INV-009' AND unit_price IS NULL; -- Insulators
UPDATE inventory_items SET unit_price = 9.50      WHERE item_id = 'INV-010' AND unit_price IS NULL; -- Copper Conductors
UPDATE inventory_items SET unit_price = 120.00    WHERE item_id = 'INV-011' AND unit_price IS NULL; -- Smart Meters
UPDATE inventory_items SET unit_price = 250.00    WHERE item_id = 'INV-012' AND unit_price IS NULL; -- Lineman Safety Kits
UPDATE inventory_items SET unit_price = 38000.00  WHERE item_id = 'INV-013' AND unit_price IS NULL; -- Maintenance Vehicles
UPDATE inventory_items SET unit_price = 95.00     WHERE item_id = 'INV-014' AND unit_price IS NULL; -- Toolboxes
UPDATE inventory_items SET unit_price = 310.00    WHERE item_id = 'INV-015' AND unit_price IS NULL; -- Radio Communicators

-- ------------------------------------------------------------
-- Roles: normalize existing free-text values, widen the column,
-- and constrain to the known set going forward.
-- ------------------------------------------------------------
UPDATE users SET role = 'admin' WHERE role IN ('Admin', 'ADMIN');

ALTER TABLE users ALTER COLUMN role TYPE VARCHAR(50);
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'customer';

ALTER TABLE users DROP CONSTRAINT IF EXISTS users_role_check;
ALTER TABLE users ADD CONSTRAINT users_role_check
  CHECK (role IN ('admin', 'customer_rep', 'procurement_manager', 'customer',
                   'Manager', 'Operator', 'Vendor'));

-- ------------------------------------------------------------
-- Seed: Customer Representative + Procurement Manager test accounts
-- Passwords documented in RBAC_WIRING.md (dev/test credentials only).
-- Hash generated with Python's bcrypt (see 001_schema.sql's note on why
-- pgcrypto's crypt()/gen_salt('bf') output doesn't verify against auth.py):
--   python3 -c "import bcrypt" then bcrypt.hashpw(b'nexus2026', bcrypt.gensalt())
-- ------------------------------------------------------------
INSERT INTO users (id, name, email, password_hash, role) VALUES
  ('aaaaaaaa-0000-0000-0000-000000000002',
   'Sara Malik',
   'cr@nexus.pk',
   '$2b$10$5P1gyb4zxlWBsj9UizAczeZwN55HSbZoVYRur1h9emmcumQvstI8u', -- nexus2026
   'customer_rep')
ON CONFLICT (email) DO UPDATE SET role = 'customer_rep', password_hash = EXCLUDED.password_hash;

INSERT INTO users (id, name, email, password_hash, role) VALUES
  ('aaaaaaaa-0000-0000-0000-000000000003',
   'Ahmed Raza',
   'procurement@nexus.pk',
   '$2b$10$5P1gyb4zxlWBsj9UizAczeZwN55HSbZoVYRur1h9emmcumQvstI8u', -- nexus2026
   'procurement_manager')
ON CONFLICT (email) DO UPDATE SET role = 'procurement_manager', password_hash = EXCLUDED.password_hash;

-- Correct the admin seed's password hash for any database created before
-- this fix (001_schema.sql's ON CONFLICT DO NOTHING means it never
-- retroactively fixes an existing row).
UPDATE users SET password_hash = '$2b$10$5P1gyb4zxlWBsj9UizAczeZwN55HSbZoVYRur1h9emmcumQvstI8u'
  WHERE email = 'admin@nexus.pk'
    AND password_hash = '$2a$06$H.wMYmMUPv9e.Q8nE7YWaOWTrPYy5Dm3/3jxCuJzSmgmMvj5jfSHm';

-- ------------------------------------------------------------
-- Notification category used by role-scoped procurement alerts
-- (documented for reference -- category column is free-text already)
-- ------------------------------------------------------------
-- category values now in use: Confirmations | Updates | Resource Allocation
--   | Outage Updates | User Complaints | Procurement Approvals
