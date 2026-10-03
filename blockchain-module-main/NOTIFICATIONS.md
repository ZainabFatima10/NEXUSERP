# Notification Engine (Phase 3)

A central, event-catalogue-driven notification system layered on top of
the existing `notifications` table and `notification_service.py` — which
keep working completely unchanged for every pre-Phase-3 caller
(`procurement.py`, `inventory_v2.py`, `complaints.py`,
`vema_orchestrator.py`, `reminder_scheduler.py`'s VEMA job). This doc
covers the new engine, the event catalogue, the outbox, SSE, and the
frontend pieces.

## Scope — why two entry points, not one

`notify_role()` / `create_notification()` (`notification_service.py`)
commit internally and have no concept of severity, dedupe, requires-action,
or preferences. Rewriting every existing caller across the codebase to a
richer shape was explicitly out of scope ("extend, don't replace" —
leave old callers working). `notification_engine.notify()` is the new,
richer entry point; it's wired into the call sites that actually map onto
the event catalogue below — `vendor_orders.py` (Phase 2) and the two
review-lifecycle events in `vendors.py` (Phase 1). Everything else
(inventory alerts, VEMA complaint reminders, the original auto-reorder
flow) still calls the original functions, untouched.

**Vendor-facing email is unaffected.** It was already direct, synchronous
n8n/email calls built in Phase 1/2 (see `N8N_AUTOMATION_WIRING.md` /
`SHIPMENT_ESCROW.md`) and stays that way — only *staff-facing* email
(admin/PM/orderer) is queued through the new `notification_outbox`.

## Data model (migration 011)

- `notifications` — widened, not replaced: `type`, `severity`,
  `entity_type`/`entity_id`, `action_url`/`action_label`,
  `requires_action`, `dedupe_key`, `read_at`, `resolved_at`, `archived_at`.
  The original `category`/`title`/`description`/`is_read`/`metadata`
  columns are untouched, so every old row and every old caller still reads
  and writes exactly as before.
- `notification_preferences` — `(user_id, type)` → `in_app`/`email`
  booleans. No row for a given type = default (both on).
- `notification_outbox` — queued staff emails, `status`
  (`pending`/`sent`/`failed`), `attempts`, `next_retry_at` (exponential
  backoff, capped at 60 min, gives up after 8 attempts).

## The event catalogue (`notification_engine.EVENT_META`)

Each entry: `category`, `severity`, `requires_action`, `action_label`,
`recipients` (role names, or `$orderer`/`$actor` resolved from the
caller's context dict), and `email: True` where staff also get a queued
email. Full list: `vendor_application.submitted/approved`,
`order.placed/resent/vendor_accepted/vendor_rejected/expired`,
`payment.required/captured/failed` (the first is defined for Phase 4 —
nothing triggers it yet, since `payment_mock_service.py` always
succeeds), `shipment.dispatched/in_transit/out_for_delivery/delayed/
arrival_reminder/arrived/approval_reminder`, `contract.executed`,
`dispute.opened/resolved`, `chain.unreachable`.

`notify()` resolves recipients, applies each recipient's preference
(critical/requires_action events are always in-app regardless — enforced
here and mirrored in the preferences UI as "locked"), writes the in-app
row(s) in the **caller's own transaction** (no commit inside `notify()` —
the caller commits once, so a committed business change never loses its
notification), and queues an outbox email where applicable. Deduped via
the `(user_id, dedupe_key)` unique index — a repeated `dedupe_key` for the
same user silently no-ops, no second row, no second email.

`action_path` (e.g. `/tracking/{id}`) is prefixed **per recipient** with
their own role's base route (`/admin`, `/procurement`, `/cr`, `/portal`)
since the same event often fans out to an orderer and an admin/PM who
reach the same page via different routes.

`auto_resolve(db, entity_type, entity_id, user_id=None)` closes out any
open `requires_action` notification for that entity — called right after
the underlying action succeeds (confirming arrival resolves both the
"out for delivery" and any "confirm arrival" reminder for that order;
approving or disputing both resolve "arrived, awaiting your decision").

## Scheduled jobs (wired into `reminder_scheduler.py`'s existing APScheduler)

- `vendor_orders.check_chain_health` (every 5 min, alongside the other
  vendor-order checks) — edge-triggered: notifies admins once when the
  chain becomes unreachable, resets so a second outage notifies again.
  Deliberately **has no `dedupe_key`** — giving it one would permanently
  block every future outage notification for that admin, not just repeats
  of the same one (a real bug caught and fixed during this pass).
- `notification_engine.process_notification_outbox` (every 1 min) — sends
  pending outbox rows, backoff on failure.

## API (`notifications.py`)

Existing endpoints (`GET /api/notifications`, `PATCH /{id}/read`,
`PATCH /mark-all-read`) keep their paths and response shapes, but now
derive the user from the JWT instead of a client-supplied `user_id` query
parameter — closing a real gap where any signed-in staff user could read
or mark-read *anyone's* notifications by guessing their UUID (the existing
frontend already only ever passed its own id, so nothing legitimate
changes). New: `GET /unread-count`, `POST /{id}/archive`,
`GET`/`PUT /preferences`, `GET /stream`.

**`/stream` (SSE)**: implemented as a polling-the-DB generator under the
SSE wire protocol — there's no message bus in this single-process
APScheduler-based app (the same reasoning that chose APScheduler over
Celery/Redis elsewhere). Each poll opens and closes its own short-lived DB
session so a long-held connection doesn't pin a pool connection for its
whole lifetime. Functionally equivalent to a push for this app's scale,
not a true one. Auth is a `token` query param, not the usual bearer
header — browsers' `EventSource` can't set custom headers. Supports
`Last-Event-ID` resume on reconnect.

**Frontend fallback**: `subscribeToNotifications()` (`services/api.ts`)
tries SSE first; on any connection error it falls back to 15s polling
automatically, transparently to every caller (Topbar, Order Tracking's
live-refresh).

## Frontend

- **Topbar bell** — dropdown (latest 10, grouped Today/Earlier), severity
  icons, relative timestamps, mark-all-read, "View all", unread badge
  (99+ capped), and the browser tab title shows `(N) ...` while unread.
- **Live toasts** — every incoming stream event fires a toast;
  `requires_action` ones persist until dismissed and carry the
  deep-link action button (`use-toast.tsx` extended with `persist`/
  `action`, both optional — no existing `toast({...})` call site changed).
- **`/notifications`** — tabs (All/Unread/Action Needed), severity filter,
  search, archive, "Load more" pagination, link to Preferences.
- **`/notifications/preferences`** — per-event in-app/email toggles,
  grouped by category, locked rows shown with a lock icon and disabled
  in-app toggle.
- **Sidebar badges** — Order Tracking (action-needed count) and Vendor
  Applications (pending count), via `useSidebarBadges()` (60s poll),
  shared by `AdminLayout`/`ProcurementLayout`.
- **Order Tracking detail** — subscribes to the same stream; any
  notification whose `entity_type`/`entity_id` matches the open order
  triggers a silent background refresh (no spinner, no toast) plus a
  "Last updated" timestamp — this is the "progress bar updates live"
  requirement, achieved by refetching the whole detail payload rather
  than patching the bar in place.

## Known limitations

- SSE is DB-polling under the SSE protocol, not a real message bus — fine
  at this app's scale, would need a pub/sub layer (Redis, Postgres
  `LISTEN`/`NOTIFY`) to scale past a handful of concurrent connections.
- `payment.required`/`payment.failed` are defined in the catalogue but
  nothing triggers them yet — `payment_mock_service.py` always succeeds
  until Phase 4's real Stripe integration lands.
- Only `vendor_orders.py` and two `vendors.py` call sites were migrated to
  the new engine — see "Scope" above for why the rest intentionally
  weren't.
