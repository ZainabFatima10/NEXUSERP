# n8n Automation Wiring — Vendor Reorder Email

How the automated <20%-stock reorder flow (Section 3) hands off to n8n for the
vendor-facing email with Accept/Reject buttons, and how the buttons call back
into FastAPI. Doesn't touch `contract_service.py` (smart contract lifecycle)
or `invoice_service.py` (billing) — this only orchestrates around them.

## End-to-end flow

```
1. Inventory scan (POST /api/inventory/check, or any read that recomputes
   status) finds an item with current_stock <= critical_threshold
   (== 20% of min_threshold, per 001_schema.sql's existing comment).
        │
        ▼
2. inventory_v2.run_inventory_check() calls
   procurement.create_pending_approval_order():
     - create_smart_contract(...) [contract_service.py, unmodified]
     - INSERT procurement_orders (stage='Pending PM Approval',
       pm_approval_status='Pending', below_20pct_trigger=TRUE)
     - notify_role(db, "procurement_manager", ...) — in-app notification
        │
        ▼
3. Procurement Manager sees it in /procurement/approvals (frontend) and
   calls POST /api/procurement/approve/{order_id}
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
     - Reject: reject_contract(...) → stage='Vendor Rejected' → notify both
       roles that manual follow-up is needed
```

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

Header `X-Webhook-Secret: {N8N_WEBHOOK_SECRET}` is sent if that env var is set.
**Not yet checked on the n8n side** — the workflow below doesn't validate it.
Low severity (the webhook can only make this instance send an email; it can't
mutate any order state — that only happens via the token-secured FastAPI
endpoints), but add an IF node checking `$json.headers['x-webhook-secret']`
before the Send Email node if you want to close it off.

## The n8n workflow — self-hosted, provisioned entirely from the CLI

Verified working end-to-end 2026-09-15: real email via Gmail SMTP, vendor
clicked Accept from their actual inbox, smart contract executed. Two nodes
(the doc originally specified three — a Respond to Webhook node — but the
Webhook node's own "When Last Node Finishes" response mode already returns
the Send Email node's result, so the third node was redundant):

1. **Webhook node** (`n8n-nodes-base.webhook`) — `httpMethod: POST`,
   `path: vendor-reorder-email`, `responseMode: lastNode`.
2. **Send Email node** (`n8n-nodes-base.emailSend`, v2.1) — `fromEmail`,
   `toEmail: ={{ $json.body.vendor_email }}` (an n8n Webhook node nests the
   POSTed JSON under `.body`), HTML built from `$json.body.*` fields, SMTP
   credential = the same Gmail account as `email_service.py`'s `SMTP_USER`/
   `SMTP_PASSWORD`.

n8n runs self-hosted via `docker-compose.yml` (service `n8n`, container
`nexus_n8n`, port `5678`, named volume `n8n_data`) — no n8n Cloud account,
no browser setup wizard. The workflow and its SMTP credential were imported
straight from JSON via the CLI, entirely without visiting the n8n UI:

```bash
docker compose up -d n8n

# Credential and workflow JSON both need an explicit "id" field — n8n's
# import commands don't auto-generate one and the DB insert fails without it.
docker cp smtp-credential.json nexus_n8n:/tmp/cred.json
docker exec nexus_n8n n8n import:credentials --input=/tmp/cred.json

docker cp workflow.json nexus_n8n:/tmp/workflow.json
docker exec nexus_n8n n8n import:workflow --input=/tmp/workflow.json
docker exec nexus_n8n n8n publish:workflow --id=<workflow id>
docker restart nexus_n8n   # publish:workflow needs a restart to take effect
                            # in single-instance (non-queue) mode
```

The SMTP credential type name is `smtp` with fields `user`, `password`,
`host`, `port` (587), `secure` (`false` — STARTTLS, not implicit TLS),
`disableStartTls` (`false`). For Gmail: an
[App Password](https://myaccount.google.com/apppasswords), not the account
password (needs 2-Step Verification enabled first).

## Environment variables

```
N8N_WEBHOOK_URL=http://localhost:5678/webhook/vendor-reorder-email
N8N_WEBHOOK_SECRET=some-shared-secret   # generated, not yet enforced by n8n — see above
BASE_URL=https://<something>.trycloudflare.com   # see below
```

If `N8N_WEBHOOK_URL` is unset, `n8n_service.py` runs in dev mode — it prints
the payload (including the accept/reject URLs) to the console instead of
posting, so you can copy-paste them into a browser to exercise the full
Accept/Reject flow locally without n8n running at all.

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
| `GET` | `/api/procurement/pending-approvals` | Procurement Manager |
| `POST` | `/api/procurement/approve/{order_id}` | Procurement Manager |
| `POST` | `/api/procurement/reject/{order_id}` | Procurement Manager |
| `GET` | `/api/procurement/vendor-response/{order_id}?decision=accept\|reject&token=...` | public — HTML landing page (`main.py`) |
| `POST` | `/api/procurement/vendor-response/{order_id}?decision=accept\|reject&token=...` | public, token-secured — the actual decision |
| `GET` | `/api/procurement/vendor-invoice/{order_id}?token=...` | public, token-secured |
| `GET` | `/api/procurement/vendor-comm-log/{order_id}` | Procurement Manager |
| `POST` | `/api/procurement/vendor-comm-log/{order_id}/resend` | Procurement Manager |

## New table — `vendor_comm_log` (`003_add_procurement_approval_workflow.sql`)

One row per email attempt (initial send + every resend), independent of the
order's current stage, so the Vendor Communication panel can show full send
history even after the vendor has already responded.
