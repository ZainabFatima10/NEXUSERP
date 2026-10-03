-- ============================================================
-- NEXUS ERP — Migration 011
-- Phase 3: central notification engine (event catalogue, preferences,
-- outbox) on top of the existing notifications table/service. Additive —
-- `notifications.category/title/description/is_read/metadata` and every
-- existing caller of notification_service.create_notification()/notify_role()
-- (procurement.py, inventory_v2.py, complaints.py, vema_orchestrator.py,
-- reminder_scheduler.py) keep working completely unchanged. The new
-- notification_engine.py is a second, richer entry point used by the
-- Phase 2 vendor_orders.py / vendors.py call sites that map onto the
-- event catalogue — see NOTIFICATIONS.md.
--
-- Idempotent — safe to re-run on every startup.
-- ============================================================

-- ============================================================
-- NOTIFICATIONS — widen with the event-catalogue fields.
-- read_at is new and sits alongside the existing is_read boolean (old
-- callers keep setting/reading is_read only -- new code sets both together).
-- ============================================================
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS type             VARCHAR(50);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS severity         VARCHAR(20) NOT NULL DEFAULT 'info';
-- info | success | warning | critical
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS entity_type      VARCHAR(50);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS entity_id        UUID;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS action_url       VARCHAR(500);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS action_label     VARCHAR(100);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS requires_action  BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS dedupe_key       VARCHAR(255);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS read_at          TIMESTAMPTZ;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS resolved_at      TIMESTAMPTZ;
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS archived_at      TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_notifications_user_read_created ON notifications(user_id, read_at, created_at);
CREATE INDEX IF NOT EXISTS idx_notifications_requires_action ON notifications(user_id, requires_action) WHERE requires_action = TRUE AND resolved_at IS NULL;
-- NULL dedupe_key rows never collide (Postgres treats NULLs as distinct in
-- a unique index), so old callers that never pass a dedupe_key are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_dedupe ON notifications(user_id, dedupe_key) WHERE dedupe_key IS NOT NULL;

-- ============================================================
-- NOTIFICATION PREFERENCES — per user, per event type. Missing row for a
-- given (user, type) means "use the default" (in_app/email both on,
-- except critical/requires_action events which are always in_app
-- regardless — enforced in notification_engine.py, not just here).
-- ============================================================
CREATE TABLE IF NOT EXISTS notification_preferences (
    id       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id  UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type     VARCHAR(50) NOT NULL,
    in_app   BOOLEAN NOT NULL DEFAULT TRUE,
    email    BOOLEAN NOT NULL DEFAULT TRUE,
    UNIQUE(user_id, type)
);

-- ============================================================
-- NOTIFICATION OUTBOX — staff-facing emails queued here after the
-- triggering DB transaction commits, delivered by a scheduler job with
-- backoff retry. (Vendor-facing emails continue to go straight through
-- n8n at the point of action, as built in Phase 1/2 -- not re-routed
-- through this outbox -- see NOTIFICATIONS.md "Scope" section for why.)
-- ============================================================
CREATE TABLE IF NOT EXISTS notification_outbox (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    channel        VARCHAR(20) NOT NULL DEFAULT 'email',
    recipient      VARCHAR(255) NOT NULL,
    payload        JSONB NOT NULL,
    status         VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- pending | sent | failed
    attempts       INTEGER NOT NULL DEFAULT 0,
    next_retry_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_error     TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sent_at        TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_notification_outbox_pending ON notification_outbox(status, next_retry_at);
