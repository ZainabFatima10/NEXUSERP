# n8n Automation Wiring — Vendor Reorder Email

How the automated reorder flow (every auto trigger — Critical, Low, Demand > Stock) (Section 3) hands off to n8n for the
vendor-facing email with Accept/Reject buttons, how the buttons call back
into FastAPI, how that decision reflects back into the Vendor Communication
portal, and how the vendor gets a confirmation copy of the executed smart
contract once they accept. Doesn't touch `contract_service.py` (smart
contract lifecycle) or `invoice_service.py` (billing) — this only
orchestrates around them.

Both n8n workflows are checked into the repo as importable JSON under
[`n8n-workflows/`](n8n-workflows/) (see that folder's `README.md` for import
steps) — previously they existed only inside a running container's own
database.

## End-to-end flow

```
1. Inventory scan (POST /api/inventory/check, or any read that recomputes
   status) finds an item that needs reordering — any of the three auto
   triggers: Critical (stock below 21% of min_threshold, 0% included),
   Demand > Stock (predicted demand exceeds stock), or Low (21–35% of
   min_threshold) — thresholds in ai-module/stock_thresholds.py. Critical
   items are also reordered automatically on every backend startup
   (inventory_v2.reorder_critical_items_on_startup), skipping any item that
   already has an open order. Every trigger takes the approval path below —
   no auto-reorder emails a vendor without a human sign-off.
        │
        ▼
2. inventory_v2.run_inventory_check() calls
   procurement.create_pending_approval_order(db, item, trigger_type, reason):
     - procurement.select_lowest_price_vendor() picks the vendor (see
       "Lowest-unit-price vendor selection" below)
     - create_smart_contract(...) [contract_service.py, unmodified]
     - INSERT procurement_orders (stage='Pending PM Approval',
       pm_approval_status='Pending', below_20pct_trigger=TRUE only for
       the Critical trigger, vendor_selection=the vendors compared)
     - notify_role(...) for both "procurement_manager" and "admin" —
       in-app notification
        │
        ▼
3. A Procurement Manager (/procurement/approvals) or Admin
   (/admin/approvals) reviews it and calls
   POST /api/procurement/approve/{order_id} (or /reject/{order_id})
        │
        ▼
4. procurement.approve_reorder():
     - generates a per-order vendor_response_token
     - builds the invoice via generate_invoice_data() [invoice_service.py,
       unmodified]
     - POSTs to N8N_WEBHOOK_URL (n8n_service.trigger_vendor_reorder_email)
        │
        ▼
5. n8n workflow receives the webhook, renders + sends the vendor email
   (itemized bill + Accept/Reject buttons + invoice PDF link)
        │
        ▼
6. Vendor clicks Accept or Reject → GET lands on an HTML confirm page
   (main.py's vendor_response_landing) → its button POSTs to
   /api/procurement/vendor-response/{order_id}?decision=...&token=...
   (public, secured by the per-order token — same "GET landing page whose
   button fires the real POST" pattern /api/procurement/confirm/{token} uses,
   for the same reason: an <a href> is a GET, and a POST-only endpoint would
   405 a plain click; a bare GET-does-the-mutation endpoint would fire for
   any email/security scanner that pre-fetches the link)
        │
        ▼
7. procurement.vendor_response():
     - Accept: sign_contract(vendor) + execute_contract() [contract_service.py,
       unmodified] → stage='Order Placed' → notify_role(admin) +
       notify_role(procurement_manager): "The reorder has been placed — …"
       → POSTs to the *second* webhook (vendor-contract-confirmation) so the
       vendor gets an emailed copy of the now-executed contract / bill,
       logged to vendor_comm_log as channel='n8n-contract-confirmation'
     - Reject: reject_contract(...) → stage='Vendor Rejected' → notify both
       roles that manual follow-up is needed
        │
        ▼
8. The Vendor Communication page (frontend, `VendorCommunication.tsx`) polls
   `GET /api/procurement/orders` every 15s and re-reads
   `vendor_decision` / `vendor_responded_at` off each order, so the
   Accepted/Rejected badge and response timestamp update on their own —
   no manual refresh needed to see the vendor's decision land. The send
   history panel picks up the new `n8n-contract-confirmation` log entry the
   same way it already showed the original `n8n-email` entry.
```

## Lowest-unit-price vendor selection (`procurement.select_lowest_price_vendor`)

When an auto-reorder fires, the candidates are:

- the item's default vendor (`inventory_items.vendor_id` at
  `inventory_items.unit_price`), if that vendor is still active, and
- every active approved vendor whose catalogue (`vendor_items`, active
  rows only) carries the same item: linked via
  `vendor_items.inventory_item_id`, or — for unlinked rows — an exact
  case-insensitive name match. The unit must match too (prices in
  different units aren't comparable), and the vendor's MOQ must be
  `<=` the reorder quantity.

The cheapest unit price wins. A tie goes to the default vendor, then to
the shorter lead time. The order, smart contract and invoice all use the
winning vendor and its price. Every vendor compared (best offer per vendor)
is stored in `procurement_orders.vendor_selection` (JSONB), and the
approvals queue shows it ("Lowest price of N vendors" + the other quotes).
The vendor is picked when the order is created, not when it is approved —
the smart contract already names the vendor by then.

Migration `015_reorder_approval_lowest_price_vendor.sql` adds
`vendor_items.inventory_item_id` (backfilled by exact name + unit match on
every startup, for unlinked rows only) and `procurement_orders.vendor_selection`.

## Payload FastAPI sends to n8n (`POST {N8N_WEBHOOK_URL}`)

```json
{
  "order_id": "uuid",
  "order_code": "ORD-ABC123",
  "item_name": "Distribution Transformers (11kV)",
  "quantity": 500,
  "unit": "units",
  "vendor_name": "Siemens AG",
  "vendor_email": "orders@siemens.com",
  "expected_delivery": "2026-09-19",
  "invoice": { /* full generate_invoice_data() payload — line items, subtotal,
                 blockchain_fee, total, contract_hash, ... */ },
  "invoice_pdf_url": "https://.../api/procurement/vendor-invoice/{id}?token=...",
  "accept_url": "https://.../api/procurement/vendor-response/{id}?decision=accept&token=...",
  "reject_url": "https://.../api/procurement/vendor-response/{id}?decision=reject&token=...",
  "trigger_type": "VEMA-Triggered"
}
```

## Payload FastAPI sends to n8n (`POST {N8N_CONTRACT_CONFIRMATION_WEBHOOK_URL}`)

Fired once, from `procurement.vendor_response()`'s accept branch, right after
`execute_contract()` succeeds:

```json
{
  "order_id": "uuid",
  "order_code": "ORD-ABC123",
  "item_name": "Distribution Transformers (11kV)",
  "quantity": 500,
  "unit": "units",
  "vendor_name": "Siemens AG",
  "vendor_email": "orders@siemens.com",
  "invoice": { /* generate_invoice_data() payload, regenerated post-execution */ },
  "invoice_pdf_url": "https://.../api/procurement/vendor-invoice/{id}?token=...",
  "contract_hash": "0x...",
  "execution_hash": "0x...",
  "trigger_type": "VEMA-Triggered"
}
```

Header `X-Webhook-Secret: {N8N_WEBHOOK_SECRET}` is sent on both webhooks
whenever that env var is set, and **is now enforced on the n8n side** — both
workflows' Webhook node uses a Header Auth credential (`Nexus Webhook
Secret`) whose value must match `N8N_WEBHOOK_SECRET` exactly (previously
generated but unchecked; see `n8n-workflows/README.md`).

## The n8n workflows — self-hosted, imported from JSON in this repo

Verified working end-to-end 2026-09-15 (real email via Gmail SMTP, vendor
clicked Accept from their actual inbox, smart contract executed) and
extended with the contract-confirmation workflow afterward. Each workflow is
two nodes (the doc originally specified three for the first one — a Respond
to Webhook node — but the Webhook node's own "When Last Node Finishes"
response mode already returns the Send Email node's result, so the third
node was redundant):

1. **Webhook node** (`n8n-nodes-base.webhook`) — `httpMethod: POST`,
   `path: vendor-reorder-email` / `vendor-contract-confirmation`,
   `responseMode: lastNode`, `authentication: headerAuth`.
2. **Send Email node** (`n8n-nodes-base.emailSend`, v2.1) — `fromEmail`,
   `toEmail: ={{ $json.body.vendor_email }}` (an n8n Webhook node nests the
   POSTed JSON under `.body`), HTML built from `$json.body.*` fields, SMTP
   credential = the same Gmail account as `email_service.py`'s `SMTP_USER`/
   `SMTP_PASSWORD`.

n8n runs self-hosted via `docker-compose.yml` (service `n8n`, container
`nexus_n8n`, port `5678`, named volume `n8n_data`) — no n8n Cloud account,
no browser setup wizard. Both workflows and their two credentials live as
JSON in [`n8n-workflows/`](n8n-workflows/) and import straight from the CLI,
entirely without visiting the n8n UI — see that folder's `README.md` for the
full import commands.

The SMTP credential type name is `smtp` with fields `user`, `password`,
`host`, `port` (587), `secure` (`false` — STARTTLS, not implicit TLS),
`disableStartTls` (`false`). For Gmail: an
[App Password](https://myaccount.google.com/apppasswords), not the account
password (needs 2-Step Verification enabled first). The Header Auth
credential type name is `httpHeaderAuth` with fields `name`
(`X-Webhook-Secret`) and `value` (must match `N8N_WEBHOOK_SECRET`).

## Environment variables

```
N8N_WEBHOOK_URL=http://localhost:5678/webhook/vendor-reorder-email
N8N_CONTRACT_CONFIRMATION_WEBHOOK_URL=http://localhost:5678/webhook/vendor-contract-confirmation
N8N_WEBHOOK_SECRET=some-shared-secret   # generated AND enforced by n8n's Header Auth credential — see above
BASE_URL=https://<something>.trycloudflare.com   # see below
```

If either webhook URL is unset, `n8n_service.py` runs in dev mode for that
workflow — it prints the payload (including the accept/reject URLs, or the
contract/execution hashes) to the console instead of posting, so you can
copy-paste the accept/reject URLs into a browser to exercise the full
Accept/Reject/confirmation cycle locally without n8n running at all.

**`BASE_URL` must be a URL the vendor's mail client can actually reach** — the
Accept/Reject links in the email are built from it. `http://localhost:8000`
only resolves on this machine. For a one-off demo, a free Cloudflare quick
tunnel needs no account:
```bash
cloudflared tunnel --url http://localhost:8000
# → prints a https://<random-words>.trycloudflare.com URL; put that in BASE_URL
# and restart uvicorn. The URL changes every time you start a new tunnel.
```
For anything that needs to stay reachable without a laptop running a tunnel,
deploy the backend somewhere with a stable URL instead.

## Two bugs only a real send/click cycle could surface

Both were unreachable dead code until n8n was actually configured and a real
vendor actually clicked a real email — worth re-checking if you touch either path.

1. **`n8n_service.trigger_vendor_reorder_email`** built its payload with a raw
   `order["id"]` (`UUID`), plus `Decimal`/`date` values riding along inside
   `invoice` (`unit_price` is `NUMERIC`, `expected_delivery` is `DATE`).
   `httpx.post(json=payload)` calls stdlib `json.dumps` under the hood, which
   raises on all three types — unlike a FastAPI *response*, which gets
   `jsonable_encoder` for free. Fixed by wrapping the payload in
   `jsonable_encoder(...)` before posting.
2. **`main.py` had no `GET /api/procurement/vendor-response/{order_id}`.**
   An `<a href>` in an email is a GET request; the decision endpoint was
   POST-only, so clicking Accept/Reject 405'd. Added a `vendor_response_landing`
   GET handler mirroring the existing `confirm_landing` pattern — a small
   HTML page whose button fires the real POST — for the same two reasons
   `confirm_landing` already exists: the link *has* to be GET, and requiring
   an explicit click before the mutating POST fires stops an email/security
   scanner's link pre-fetch from silently accepting or rejecting the order.

## New endpoints this introduces (all in `procurement.py` unless noted)

| Method | Path | Auth |
|---|---|---|
| `GET` | `/api/procurement/pending-approvals` | Procurement Manager / Admin |
| `POST` | `/api/procurement/approve/{order_id}` | Procurement Manager / Admin |
| `POST` | `/api/procurement/reject/{order_id}` | Procurement Manager / Admin |
| `GET` | `/api/procurement/vendor-response/{order_id}?decision=accept\|reject&token=...` | public — HTML landing page (`main.py`) |
| `POST` | `/api/procurement/vendor-response/{order_id}?decision=accept\|reject&token=...` | public, token-secured — the actual decision |
| `GET` | `/api/procurement/vendor-invoice/{order_id}?token=...` | public, token-secured |
| `GET` | `/api/procurement/vendor-comm-log/{order_id}` | Procurement Manager |
| `POST` | `/api/procurement/vendor-comm-log/{order_id}/resend` | Procurement Manager |

## New table — `vendor_comm_log` (`003_add_procurement_approval_workflow.sql`)

One row per email attempt, independent of the order's current stage, so the
Vendor Communication panel can show full send history even after the vendor
has already responded. `channel` values in use: `direct-email` (manual
order path), `n8n-email` (reorder Accept/Reject email — initial send and
every resend), and `n8n-contract-confirmation` (the post-accept smart
contract / bill copy, one row, fired automatically — no resend button for
it yet).
