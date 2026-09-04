-- ============================================================
-- NEXUS ERP — Migration 004
-- VEMA complaint ticketing: three-tier severity (small/medium/critical),
-- full conversation history, and the CR reminder-cadence scheduler.
-- Idempotent — safe to re-run on every startup.
-- ============================================================

CREATE TABLE IF NOT EXISTS complaints (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_code         VARCHAR(20) UNIQUE NOT NULL,     -- TKT-XXXXXX

    -- Who filed it
    customer_id         UUID REFERENCES users(id),       -- NULL for phone-in/manual entries with no portal account
    customer_name       VARCHAR(255),
    customer_email      VARCHAR(255),
    channel             VARCHAR(20) NOT NULL DEFAULT 'chat',
    -- voice | chat | manual

    -- NLU classification
    category            VARCHAR(100) NOT NULL,
    subtype             VARCHAR(150) NOT NULL,
    severity            VARCHAR(10) NOT NULL,
    -- small | medium | critical
    description         TEXT NOT NULL,
    area                VARCHAR(255),

    -- Lifecycle
    status              VARCHAR(20) NOT NULL DEFAULT 'open',
    -- open | auto_resolved | escalated | resolved
    vema_triggered       BOOLEAN NOT NULL DEFAULT TRUE,    -- FALSE for manually-created tickets
    assigned_cr         UUID REFERENCES users(id),
    escalated_at        TIMESTAMPTZ,
    escalated_by        UUID REFERENCES users(id),          -- NULL when system auto-escalated
    resolved_at         TIMESTAMPTZ,
    resolved_by         UUID REFERENCES users(id),           -- NULL when auto-resolved by the system
    resolution          TEXT,

    -- Reminder cadence (medium/critical, while status='escalated')
    next_reminder_due   TIMESTAMPTZ,
    reminder_count      INTEGER NOT NULL DEFAULT 0,
    last_reminded_at    TIMESTAMPTZ,

    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_complaints_status    ON complaints(status);
CREATE INDEX IF NOT EXISTS idx_complaints_severity  ON complaints(severity);
CREATE INDEX IF NOT EXISTS idx_complaints_category  ON complaints(category);
CREATE INDEX IF NOT EXISTS idx_complaints_customer  ON complaints(customer_id);
CREATE INDEX IF NOT EXISTS idx_complaints_reminder  ON complaints(status, next_reminder_due) WHERE status = 'escalated';
CREATE INDEX IF NOT EXISTS idx_complaints_created   ON complaints(created_at DESC);

-- ============================================================
-- Full conversation history: voice transcript turns, chat messages,
-- and system actions (classification, auto-resolution attempt,
-- escalation, reminder, resolution) -- one row per event, in order.
-- ============================================================
CREATE TABLE IF NOT EXISTS complaint_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    complaint_id    UUID NOT NULL REFERENCES complaints(id) ON DELETE CASCADE,
    event_type      VARCHAR(30) NOT NULL,
    -- voice_transcript | chat_message | system_action | escalation | reminder | resolution
    actor           VARCHAR(50) NOT NULL,
    -- customer | vema | cr:<name> | admin:<name>
    content         TEXT NOT NULL,
    metadata        JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_complaint_events_complaint ON complaint_events(complaint_id, created_at ASC);

-- ============================================================
-- Widen notifications.category (currently VARCHAR(50)) is already wide
-- enough for "User Complaints" -- no change needed there.
-- ============================================================
