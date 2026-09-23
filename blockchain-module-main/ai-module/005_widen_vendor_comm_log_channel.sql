-- ============================================================
-- NEXUS ERP — Migration 005
-- Widen vendor_comm_log.channel from VARCHAR(20) to VARCHAR(40).
-- The original cap fit 'n8n-email' / 'direct-email' / 'dev-console', but the
-- new post-accept confirmation channel 'n8n-contract-confirmation' (see
-- N8N_AUTOMATION_WIRING.md) is 25 characters and would otherwise fail with
-- "value too long for type character varying(20)".
-- Idempotent — safe to re-run on every startup (widening the same column to
-- the same type twice is a no-op).
-- ============================================================

ALTER TABLE vendor_comm_log ALTER COLUMN channel TYPE VARCHAR(40);
