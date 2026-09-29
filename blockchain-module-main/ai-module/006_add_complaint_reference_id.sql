-- ============================================================
-- NEXUS ERP — Migration 006
-- Feature B: a human-readable ticket reference, separate from ticket_code.
--
-- ticket_code ("TKT-4DBD56") stays exactly as-is — it's already used
-- everywhere (frontend chips, emails, notifications, VEMA_PIPELINE.md).
-- reference_id is an ADDITIVE second identifier in the
-- VEMA-<CATEGORY CODE>-<YYYYMMDD>-<seq> shape the spec asks for, generated
-- server-side in vema_orchestrator.create_ticket() / _generate_reference_id().
--
-- Idempotent — safe to re-run on every startup.
-- ============================================================

ALTER TABLE complaints ADD COLUMN IF NOT EXISTS reference_id VARCHAR(40);

DROP INDEX IF EXISTS idx_complaints_reference_id;
CREATE UNIQUE INDEX idx_complaints_reference_id ON complaints(reference_id)
    WHERE reference_id IS NOT NULL;

-- Backfill existing rows that predate this column. Uses each row's own
-- category code + creation date, numbered in creation order per
-- category+day — matches the same scheme new tickets get, just computed
-- once in bulk instead of per-insert.
WITH ranked AS (
    SELECT
        id,
        'VEMA-' ||
        CASE category
            WHEN 'Billing Issues'                    THEN 'BILL'
            WHEN 'Meter Issues'                       THEN 'METER'
            WHEN 'Power Supply Issues'                THEN 'POWER'
            WHEN 'New Connection / Disconnection'     THEN 'CONN'
            WHEN 'Infrastructure Complaints'          THEN 'INFRA'
            WHEN 'Customer Service'                   THEN 'CSERV'
            WHEN 'Fraud/Theft'                        THEN 'FRAUD'
            WHEN 'Payment & Refund'                   THEN 'PAYMT'
            ELSE 'MISC'
        END || '-' ||
        TO_CHAR(created_at, 'YYYYMMDD') || '-' ||
        LPAD(
            ROW_NUMBER() OVER (
                PARTITION BY category, created_at::date
                ORDER BY created_at
            )::text,
            3, '0'
        ) AS new_reference_id
    FROM complaints
    WHERE reference_id IS NULL
)
UPDATE complaints c
SET reference_id = ranked.new_reference_id
FROM ranked
WHERE c.id = ranked.id;
