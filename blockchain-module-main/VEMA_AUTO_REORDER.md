# VEMA Auto-Reorders — Stock Scan → Proposal → Approval → Order

A deterministic stock-scan pipeline that proposes a reorder (quantity,
ranked vendor, plain-English rationale) *before* any order exists, and
waits for a Procurement Manager or Admin to approve or reject it. Additive
and parallel to the existing `<=20%`-of-`min_threshold` auto-trigger
(`inventory_v2.run_inventory_check()` → `procurement.create_pending_approval_order()`,
see `procurement.py`'s "AUTOMATED REORDERING" section and `/procurement/approvals`)
— that flow is untouched and keeps working exactly as before. This one is
richer: a Procurement Manager reviews the *proposal itself* — why VEMA
thinks this item needs reordering, how much, and from whom — not an
already-created order with no explanation.

## End-to-end flow

```
1. Stock scan (vema_reorder_service.scan_and_create_requests)
   Triggered from TWO places:
     (a) inventory_v2.run_inventory_check()  — after its own per-item loop
         inventory_v2.update_stock()         — after a manual stock edit
     (b) reminder_scheduler's scheduled job  — every 30 minutes
        │
        ▼
2. Per item: threshold check
   stock <= VEMA_REORDER_THRESHOLD_PCT% of par_level
   (par_level = inventory_items.max_stock_level, or min_threshold*2 if unset)
        │
        ▼
3. Dedup / cooldown — skip if this item already has:
     - a pending_approval VEMA request, OR
     - an open procurement_orders row (either THIS system's or the
       existing <=20% auto-trigger's or a plain manual order), OR
     - a request rejected within VEMA_REORDER_COOLDOWN_HOURS
        │
        ▼
4. Deterministic quantity
   qty = par_level - current_stock - inbound_qty + forecast_demand
   (inbound_qty: sum of open procurement_orders.quantity for this item;
    forecast_demand: inventory_v2.calculate_prediction(), read-only, 0 if
    unavailable) — floored at 1, raised to the chosen vendor's MOQ if set.
        │
        ▼
5. Vendor ranking (active vendors only — vendors.status='active')
   Candidates = vendor_items rows matching this item's category, UNION
   the item's own inventory_items.vendor_id if still active (the original
   seed-data linkage, which predates vendor_items and has no catalogue
   row of its own).
   score = 0.4*price_score + 0.3*lead_time_score + 0.3*accept_rate
   (price/lead-time: normalized low-is-better across candidates;
    accept_rate: this vendor's historical Accepted/Rejected ratio on
    procurement_orders, neutral 0.5 if no history yet)
   No eligible vendor -> vendor_id left null; the request is still created,
   flagged for the approver to pick one manually.
        │
        ▼
6. Rationale — Gemini (see llm_client.py) phrases the already-decided
   numbers into 2-3 sentences; a template fallback if the LLM is
   unavailable/fails. The LLM never changes a number, only describes it.
        │
        ▼
7. vema_reorder_requests row created, status='pending_approval'
   Procurement Managers + Admins notified (notification_service.notify_role)
        │
   ┌────┴─────────────────────┐
   │ APPROVE (qty/vendor       │ REJECT (reason required)
   │ editable)                 │
   ▼                           ▼
8a. procurement.create_pending_approval_order()  8b. status='rejected',
    + procurement.approve_reorder() — called          cooldown starts.
    back-to-back, reusing both exactly as they         No order, no email.
    are. Together: smart contract created,
    order flips straight to pm_approval_status=
    'Approved' / stage='Vendor Notified', vendor
    emailed an Accept/Reject link via the existing
    n8n workflow (trigger_vendor_reorder_email).
    resulting_order_id stored on the request.
        │
        ▼
9. Unchanged from here — vendor accepts -> contract executes -> shipment
   -> delivery check-in, exactly the existing procurement_orders lifecycle.
```

## Why `create_pending_approval_order()` + `approve_reorder()`, not `create_order()`

`procurement.py` has two different "create an order and tell the vendor"
paths:

- `create_order()` — the plain manual/"Confirm Reorder" path. Sends the
  vendor a **confirm-only** link via direct SMTP (`send_vendor_order_email`)
  — no reject option, no n8n involved.
- `create_pending_approval_order()` + `approve_reorder()` — the existing
  `<=20%` auto-trigger's path. Builds both an **Accept and a Reject** URL
  and sends them through the existing n8n webhook
  (`n8n_service.trigger_vendor_reorder_email`).

VEMA's approval step is explicitly an "accept/reject webhook" flow — so it
reuses the second pair, not `create_order()`. On approve, both functions
are called back-to-back with the *same* approving user, so the order never
sits in an intermediate "awaiting a second approval" state — VEMA's
approval already *is* the human decision; the order goes straight from
nonexistent to `Vendor Notified`.

One accepted side effect of this reuse: `create_pending_approval_order()`
itself fires its own "Reorder Approval Needed" notification to every
Procurement Manager (unmodified, as the "don't duplicate/edit existing
logic" rule requires) — so approving a VEMA request also produces one
extra, immediately-stale notification from the *other* system. Harmless,
not worth suppressing by touching code that's explicitly off-limits.

## Data model (migration `015_add_vema_reorder_requests.sql`)

- `inventory_items.max_stock_level` (new, nullable) — the "par"/target
  stock level to refill up to. No such column existed before (only
  `min_threshold`, the reorder *point*, and `critical_threshold`, 20% of
  it). Falls back to `min_threshold * 2` when unset — the same
  dummy-forecast multiplier `inventory_v2.calculate_prediction()` already
  uses when no trained model is loaded.
- `vema_reorder_requests` — one row per proposal: the trigger snapshot
  (`stock_at_trigger`, `par_level`, `threshold_pct`), the deterministic
  numbers (`suggested_qty`, `unit_price_est`, `total_est`), the chosen
  vendor + alternatives (`vendor_id`, `alt_vendor_ids`,
  `vendor_score_breakdown` — full scoring detail for every candidate
  considered, not just the winner), the LLM `rationale`, `status`, and the
  decision trail (`decided_by`, `decided_at`, `decision_note`,
  `edited_qty`/`edited_vendor_id` if the approver changed them,
  `resulting_order_id`).
- `vema_reorder_audit_log` — permanent record of created/approved/
  rejected/expired events, separate from the dismissible notifications
  inbox.

## Endpoints (`vema_reorder_router.py`, mounted under `/api/procurement`)

| Method | Path | Notes |
|---|---|---|
| `GET` | `/vema-requests` | filters: `status`, `item_id`, `vendor_id`, `search`, `date_from`, `date_to`, pagination |
| `GET` | `/vema-requests/stats` | pending/approved/rejected/expired counts + approval rate |
| `GET` | `/vema-requests/{id}` | full detail incl. vendor score breakdown |
| `POST` | `/vema-requests/{id}/approve` | body: optional `qty`, `vendor_id`, `note`. 409 if already decided, 422 if no vendor selected |
| `POST` | `/vema-requests/{id}/reject` | body: required `reason`. 409 if already decided, 422 if reason blank |

Approvers: Procurement Manager + Admin (`VEMA_REORDER_APPROVER_ROLES` in
`vema_reorder_router.py` — a single list to edit if that ever changes;
Admin is always implicitly included by `rbac.require_role()`). Customer
Representative gets a 403 — not in the allowed-roles set at all.

## Configuration (env vars, all in `vema_reorder_service.py`)

| Var | Default | |
|---|---|---|
| `VEMA_REORDER_THRESHOLD_PCT` | `20` | trigger when stock <= this % of par_level |
| `VEMA_REORDER_COOLDOWN_HOURS` | `24` | no re-trigger for this long after a rejection |
| `VEMA_REORDER_EXPIRY_HOURS` | `72` | a pending proposal auto-expires after this long |

The scheduled scan interval (30 minutes) is set where the job is
registered, in `reminder_scheduler.py`'s `start_scheduler()` — not an env
var, matching every other job in that file.

## Known limitations

- **Vendor ranking has no delivery-performance signal.** Price, lead time,
  and historical accept-rate are the only three signals that exist
  anywhere in this schema — no rating/on-time-delivery column exists on
  `vendors`, `vendor_items`, or `vendor_orders`. A fourth weighted signal
  would need new data collection, not just new code.
- **`vendor_items` has no FK to `inventory_items`.** Matching is by
  case-insensitive `category` string equality — fine for this catalogue's
  size, but two differently-spelled categories that mean the same thing
  won't match.
- **Most seed vendors (Siemens, ABB, ...) have no `vendor_items` catalogue
  row** — they predate Phase 1 vendor onboarding. Their price/lead-time
  come from the item's own `unit_price` and a flat 14-day default, not a
  real per-vendor catalogue entry, so ranking across them is necessarily
  coarser than for Phase-1-onboarded vendors.
- **Doc location**: this file lives in `blockchain-module-main/`, not
  `docs/VEMA_AUTO_REORDER.md` as originally specified — no `docs/`
  directory exists anywhere in this repo; every other feature doc
  (`VENDOR_ONBOARDING.md`, `SHIPMENT_ESCROW.md`, `NOTIFICATIONS.md`) lives
  here too, so this follows that established convention instead.

## Testing

```bash
cd blockchain-module-main/ai-module
python -m pytest tests/test_vema_reorder.py -v
```

Covers: threshold boundaries (21%/20%/0%), dedup (pending/cooldown/
post-cooldown), quantity (inbound stock, MOQ rounding, forecast
unavailable), vendor ranking (active-only, no-eligible-vendor → 422 on
approve), approve (order created, email workflow invoked exactly once,
double-approve → 409), reject (no order, no email), RBAC (Customer Rep
403, PM/Admin succeed), and one bad item never aborting the full scan
(verified via a targeted patch of one internal function — not a database
mock; this repo's test suite always runs against a real Postgres, see
`conftest.py` and every other test file).
