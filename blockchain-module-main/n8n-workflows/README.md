# n8n Workflows — Vendor Email Automation

Importable n8n workflows backing the flows documented in
`../N8N_AUTOMATION_WIRING.md` (Phase 1, low-stock auto-reorder) and
`../VENDOR_ONBOARDING.md` / `../SHIPMENT_ESCROW.md` (Phase 2, orders placed
against the approved vendor catalogue). Checked in here so they can be
re-imported, diffed, and version-controlled instead of only living inside a
running `nexus_n8n` container's own database.

| File | Webhook path | Fired by | Sends |
|---|---|---|---|
| `vendor-reorder-email.workflow.json` | `/webhook/vendor-reorder-email` | `procurement.approve_reorder()` / `resend_vendor_email()` | Itemized bill + Accept/Reject buttons |
| `vendor-contract-confirmation.workflow.json` | `/webhook/vendor-contract-confirmation` | `procurement.vendor_response()` on **accept** | Copy of the now-executed smart contract / bill |
| `vendor-order-email.workflow.json` | `/webhook/vendor-order-email` | `vendor_orders.place_vendor_order()` / resend / reminder | Itemized order + Accept/Reject buttons |
| `vendor-order-shipment-link.workflow.json` | `/webhook/vendor-order-shipment-link` | `vendor_orders` on vendor **accept** | The no-login shipment-update link |
| `vendor-order-payment-released.workflow.json` | `/webhook/vendor-order-payment-released` | `vendor_orders.approve_receipt_endpoint()` | Payment-released confirmation |

Every workflow is just two nodes: a `Webhook` node secured with a
**Header Auth** credential (`X-Webhook-Secret`), and a `Send Email`
(`n8n-nodes-base.emailSend` v2.1) node built from the webhook's JSON body.

## Import

```bash
docker compose up -d n8n

# 1. Credentials — copy each template to a *-credential.json (gitignored),
#    fill in real values (real SMTP app password + a secret matching
#    ai-module's N8N_WEBHOOK_SECRET), then:
cp smtp-credential.template.json smtp-credential.json   # edit with real values
docker cp smtp-credential.json nexus_n8n:/tmp/smtp-cred.json
docker exec nexus_n8n n8n import:credentials --input=/tmp/smtp-cred.json

cp webhook-secret-credential.template.json webhook-secret-credential.json   # edit
docker cp webhook-secret-credential.json nexus_n8n:/tmp/secret-cred.json
docker exec nexus_n8n n8n import:credentials --input=/tmp/secret-cred.json

# 2. Workflows
docker cp vendor-reorder-email.workflow.json nexus_n8n:/tmp/wf1.json
docker exec nexus_n8n n8n import:workflow --input=/tmp/wf1.json
docker exec nexus_n8n n8n update:workflow --id=vendor-reorder-email-wf --active=true

docker cp vendor-contract-confirmation.workflow.json nexus_n8n:/tmp/wf2.json
docker exec nexus_n8n n8n import:workflow --input=/tmp/wf2.json
docker exec nexus_n8n n8n update:workflow --id=vendor-contract-confirmation-wf --active=true

# Phase 2 — same pattern, same two credentials
for wf in vendor-order-email vendor-order-shipment-link vendor-order-payment-released; do
  docker cp "$wf.workflow.json" nexus_n8n:/tmp/$wf.json
  docker exec nexus_n8n n8n import:workflow --input=/tmp/$wf.json
  docker exec nexus_n8n n8n update:workflow --id="$wf-wf" --active=true
done

docker restart nexus_n8n   # activation needs a restart in single-instance mode
```

(`n8n publish:workflow` from older n8n versions was renamed to
`n8n update:workflow --active=true` on current releases — use whichever your
image's `n8n --version` supports.)

## Credentials

**Never commit filled-in credential files** — `*.template.json` here hold
placeholder values only. Copy a template to `<name>-credential.json` (e.g.
`smtp-credential.json`), fill in real values, then import; the root
`.gitignore` already excludes `n8n-workflows/*-credential.json` while still
tracking the `*.template.json` files.

- **Nexus SMTP** (`smtp-credential.template.json`) — same Gmail account as
  `email_service.py`'s `SMTP_USER`/`SMTP_PASSWORD`. Needs a Gmail
  [App Password](https://myaccount.google.com/apppasswords) (2-Step
  Verification must be enabled first), not the account password.
- **Nexus Webhook Secret** (`webhook-secret-credential.template.json`) — the
  `value` field must exactly match `ai-module/.env`'s `N8N_WEBHOOK_SECRET`.
  FastAPI sends it as the `X-Webhook-Secret` header on every POST to either
  webhook; n8n's Header Auth credential now enforces it (previously
  generated but unchecked — closed off as part of hardening this into a
  "proper" automation).

## Dev mode without n8n running

Leave any of the `N8N_*_WEBHOOK_URL` vars unset in `ai-module/.env` —
`n8n_service.py` prints that workflow's payload (including accept/reject
URLs, contract hashes, and shipment-update links) to the console instead
of posting, so every flow in this repo can be exercised end to end without
n8n running at all.
