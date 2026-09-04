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
6. Vendor clicks Accept or Reject → hits
   POST /api/procurement/vendor-response/{order_id}?decision=...&token=...
   (public, secured by the per-order token — same "signed link, no login"
   pattern the existing /api/procurement/confirm/{token} uses)
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

Header `X-Webhook-Secret: {N8N_WEBHOOK_SECRET}` is sent if that env var is set
— add a matching check in the n8n workflow's Webhook node (or an IF node
right after it) if you want to reject spoofed calls.

## Importable n8n workflow (paste as a workflow JSON, or build these 3 nodes manually)

1. **Webhook node** (trigger)
   - Method: `POST`
   - Path: `/vendor-reorder-email` (full URL becomes your `N8N_WEBHOOK_URL`)
   - Response mode: "When last node finishes" — return `{"message_id": ...}` so
     `n8n_service.py` can log it against the order.

2. **Send Email node** (e.g. n8n's Gmail/SMTP/SendGrid node — reuse whatever
   credential you already use for `email_service.py`'s `SMTP_USER`)
   - To: `{{ $json.vendor_email }}`
   - Subject: `Purchase Order {{ $json.order_code }} — Reorder Confirmation Needed`
   - HTML body — itemized bill from `{{ $json.invoice.line_items }}`, total
     from `{{ $json.invoice.total }}`, and two buttons:
     ```html
     <a href="{{ $json.accept_url }}"
        style="background:#2e7d5e;color:#fff;padding:14px 36px;border-radius:24px;text-decoration:none;font-weight:700;">
       ✅ Accept Order
     </a>
     <a href="{{ $json.reject_url }}"
        style="background:#c62828;color:#fff;padding:14px 36px;border-radius:24px;text-decoration:none;font-weight:700;margin-left:12px;">
       ❌ Reject Order
     </a>
     <a href="{{ $json.invoice_pdf_url }}">Download Invoice (PDF)</a>
     ```

3. **Respond to Webhook node**
   - Body: `{"message_id": "{{ $itemIndex }}-{{ $now }}"}` (or your email
     provider node's real message id field, e.g. `{{ $json.messageId }}` for
     the Gmail node)

The **Accept/Reject links themselves point straight back at FastAPI**
(`accept_url`/`reject_url` from the payload) — n8n does not need webhook
nodes for the button clicks, only for the initial "send email" trigger. This
keeps the token verification in one place (`procurement.vendor_response`)
instead of duplicating it in n8n.

## Environment variables

Added to `ai-module/env.example`:

```
N8N_WEBHOOK_URL=https://your-n8n-instance.app.n8n.cloud/webhook/vendor-reorder-email
N8N_WEBHOOK_SECRET=some-shared-secret   # optional, checked by n8n's IF node
```

If `N8N_WEBHOOK_URL` is unset, `n8n_service.py` runs in dev mode — it prints
the payload (including the accept/reject URLs) to the console instead of
posting, so you can copy-paste them into a browser to exercise the full
Accept/Reject flow locally without a live n8n instance. See the test
checklist in the top-level `README.md` update for the exact steps.

## New endpoints this introduces (all in `procurement.py`)

| Method | Path | Auth |
|---|---|---|
| `GET` | `/api/procurement/pending-approvals` | Procurement Manager |
| `POST` | `/api/procurement/approve/{order_id}` | Procurement Manager |
| `POST` | `/api/procurement/reject/{order_id}` | Procurement Manager |
| `POST` | `/api/procurement/vendor-response/{order_id}?decision=accept\|reject&token=...` | public, token-secured |
| `GET` | `/api/procurement/vendor-invoice/{order_id}?token=...` | public, token-secured |
| `GET` | `/api/procurement/vendor-comm-log/{order_id}` | Procurement Manager |
| `POST` | `/api/procurement/vendor-comm-log/{order_id}/resend` | Procurement Manager |

## New table — `vendor_comm_log` (`003_add_procurement_approval_workflow.sql`)

One row per email attempt (initial send + every resend), independent of the
order's current stage, so the Vendor Communication panel can show full send
history even after the vendor has already responded.
