# Vendor Onboarding — Registration, Vetting, Approved Catalogue

Phase 1 of the vendor/procurement/shipment/payment expansion. Covers how a
company becomes a NEXUS ERP vendor, how an Admin/Procurement Manager vets
them, and how they show up as an orderable catalogue. Doesn't touch
`contract_service.py` (smart contracts), `invoice_service.py` (billing), or
any ML/forecasting code — purely additive new tables/routes/pages, plus the
smallest possible hook into the existing Procurement order form.

Vendors never get a login or account page. Everything a vendor does is
either the public registration form, or (in a later phase) a click on a
signed, expiring link in an email. This phase only covers registration —
the vendor accept/reject-by-email flow for *orders* already exists
separately (see `N8N_AUTOMATION_WIRING.md`) and is reused, not duplicated.

## End-to-end flow

```
1. Public "Become a Vendor" form (marketing site, /become-a-vendor)
   Step 1: Company details          Step 4: Documents (NTN cert, etc.)
   Step 2: Contact & location       Step 5: Items & unit prices (catalogue)
   Step 3: Commercial terms         Step 6: Declaration & submit
        │
        ▼
2. POST /api/public/vendors/apply (multipart: JSON payload + document files)
     - validates business rules (IBAN format, PK mobile format, >=1 item,
       honeypot, per-IP rate limit)
     - INSERT vendor_applications (status='pending') + vendor_application_items
       + vendor_application_documents (stored outside the web root, randomized
       filenames, magic-byte + extension validated, 5MB cap)
     - emails the vendor: application-received ack + an order-email
       verification link (non-fatal — logged, never aborts the submission)
     - notify_role(admin / procurement_manager) — in-app
        │
        ▼
3. Vendor clicks the verification link → GET /api/public/vendors/verify-email/{token}
   (one-time, no login) → email_verified=TRUE on the application
        │
        ▼
4. Admin / Procurement Manager reviews in /admin or /procurement
   "Vendor Applications" (tabs: Pending / Needs Info / Approved / Rejected):
     - ticks off a vetting checklist (NTN verified, registration verified,
       documents reviewed, prices reasonable, order email verified)
     - views documents, full catalogue, bank details (verification-only —
       never in any public/catalogue listing)
  ┌──────────┬───────────────┬──────────────────┐
  │ Approve  │ Reject(reason)│ Request Info(note)│
  ▼          ▼               ▼
5a. Approve — POST /api/vendor-applications/{id}/approve
     - ONE transaction: INSERT vendors (status='active', copies every
       vetted field) + INSERT vendor_items for every staged catalogue row
     - application.status='approved', approved_vendor_id set
     - on any failure: rollback, application stays pending — never a
       half-created vendor
     - emails vendor: approved (no login — orders come by email instead)
5b. Reject — POST /api/vendor-applications/{id}/reject {reason}
     - reason required; emails vendor with it; no vendor/catalogue rows created
5c. Request Info — POST /api/vendor-applications/{id}/request-info {note}
     - status='needs_info'; emails vendor; can still be approved/rejected later
        │
        ▼
6. Approved vendor appears immediately in:
     - GET /api/vendors (Vendor Catalogue page, Procurement's vendor picks)
     - the Procurement order form's item dropdown, filtered to that vendor's
       inventory_items (see "Procurement hook" below)
   Pending/rejected/needs_info vendors never appear in either — enforced in
   the query (`WHERE status = 'active'`), not just hidden in the UI.
```

## New tables (`009_add_vendor_applications.sql`)

| Table | Purpose |
|---|---|
| `vendor_applications` | One row per submission — every field from Steps 1–3, plus status/review workflow columns and a `vetting_checklist` JSONB |
| `vendor_application_documents` | Uploaded files — `stored_filename` is a random token; only that lives in `ai-module/data/vendor_documents/` (gitignored) |
| `vendor_application_items` | Staged catalogue rows (manual + parsed-upload rows merged client-side before submit) |
| `vendor_items` | Live catalogue for *approved* vendors — what they sell, distinct from `inventory_items` (the DISCO's own internal stock master) |

`vendors` is **widened**, not replaced — ~25 new nullable columns (vetting
fields) plus `status` (`active`/`suspended`, default `'active'`) and
`order_email`. The migration backfills every pre-existing vendor to
`status='active'`, `order_email=email` — so `procurement.py` / `inventory_v2.py`
(which only ever read `id`/`name`/`email`) keep working unchanged, and no
legacy vendor silently disappears from the system.

## Catalogue upload — parsing & validation (`vendor_catalogue_parser.py`)

Accepts `.xlsx` (via `openpyxl`) or `.csv` (via `pandas`, BOM/encoding
tolerant), up to 2,000 rows / 5 MB. Required columns: Item Name, Unit of
Measure, Unit Price (PKR) — matched against a small alias table so header
casing/whitespace variations ("unit price", "Unit Price (PKR)", "price")
all resolve. Per row: missing name/unit/price, non-numeric or negative
price, duplicate SKU or name (against earlier rows in the same file), and
unknown category (kept importable, just flagged) are all caught and
reported with the row number and reason — never silently dropped, and
never evaluates spreadsheet formulas (pandas/openpyxl read computed values
only). `POST /api/public/vendors/items/parse` previews this with **no DB
writes**; the same function is trusted for what actually gets staged once
the vendor merges valid rows into their grid and submits.

## Endpoints

| Method | Path | Auth |
|---|---|---|
| `POST` | `/api/public/vendors/apply` | public, rate-limited, honeypot-guarded |
| `POST` | `/api/public/vendors/items/parse` | public — preview only |
| `GET` | `/api/public/vendors/template` | public — downloadable `.xlsx` |
| `GET` | `/api/public/vendors/categories` | public — reads `inventory_items.category`, not a hand-maintained list |
| `GET` | `/api/public/vendors/verify-email/{token}` | public, one-time token |
| `GET` | `/api/vendor-applications` / `/{id}` | Admin + Procurement Manager |
| `GET` | `/api/vendor-applications/{id}/documents/{doc_id}` | Admin + Procurement Manager |
| `POST` | `/api/vendor-applications/{id}/checklist` | Admin + Procurement Manager |
| `POST` | `/api/vendor-applications/{id}/approve` \| `/reject` \| `/request-info` | Admin + Procurement Manager |
| `GET` | `/api/vendors` / `/{id}` / `/{id}/items` | Admin + Procurement Manager — `status='active'` only |

## Procurement hook (smallest possible, per the additive-only guardrail)

`Procurement.tsx`'s order form is untouched in its default (item-first) path.
The Vendor Catalogue's "Create Order" button reuses the same
`navigate(path, { state })` prefill pattern Inventory → Procurement already
used for reorders — it now also carries `prefillVendorId`, which filters the
item dropdown to that vendor's `inventory_items` rows (via the `vendor_id`
column `inventory_items` already had — just newly exposed on the
`InventoryItem` API type) and shows a "Filtered to {vendor}" chip. If that
vendor has no linked `inventory_items` row yet, the UI says so rather than
silently showing an empty list. Ordering directly from a vendor's
`vendor_items` catalogue (including brand-new items with no internal
inventory counterpart) is a natural fit for the order/shipment state-machine
rework, which rebuilds order placement anyway — deferred there rather than
reshaping `procurement_orders`' `item_id NOT NULL REFERENCES inventory_items`
constraint in this pass.

## Environment variables

None required — `vendor_catalogue_parser.py` and the apply/vetting endpoints
use only `openpyxl`/`pandas` (already dependencies) and the existing
`email_service.py` SMTP config (dev-mode console fallback when unset, same
as every other email in this repo).

## Known limitations

- Per-IP rate limiting (5 applications/hour) is an in-process dict — resets
  on restart, not shared across multiple workers. Fine for this single-
  instance FYP deployment; a real multi-worker deployment would need a
  shared store (Redis) instead.
- `bank_iban` validation is the literal rule the spec asked for (24 chars,
  starts `PK`) — not a full IBAN checksum (mod-97) validation.
- No `vendor_price_history` table yet (left as a documented future addition,
  not required for this phase).
