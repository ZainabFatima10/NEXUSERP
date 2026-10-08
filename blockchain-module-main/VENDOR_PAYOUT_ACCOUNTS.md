# Vendor Payout Accounts — the verified destination for step M

Fills a gap in the existing vendor registration + payment lifecycle: a
verified, encrypted-at-rest bank/wallet account that
`payments.release_payout()` (the post-delivery payment release — "step M"
of the existing escrow → capture → payout flow, see `SHIPMENT_ESCROW.md`
"Payments") pays out to. Additive only — doesn't touch the ML models, the
`ShipmentEscrow` smart contract, or `invoice_service.py`'s billing math.

**Not the same as `vendors.bank_name`/`bank_account_title`/`bank_iban`**
(migration `009_add_vendor_applications.sql`). Those are the vendor's
informal Commercial-Terms contact banking details — lightly validated,
stored in plaintext, shown in a handful of display/CSV spots — and are left
completely untouched by this feature. `vendor_payment_accounts` is the
separate, verified, encrypted table that real money actually moves against;
`release_payout()` resolves the payout destination through it exclusively.

## Why a separate table, not widened `vendors` columns

The repo's established convention for Phase-1 vendor data (migration 009)
is widening `vendors` with plain nullable columns. This feature needed
three things that convention doesn't give you cleanly: field-level
encryption at rest, a verification workflow independent of the vendor's own
`active`/`suspended` status, and cross-vendor duplicate detection on a
sensitive field. Bolting that onto `vendors` would mean partially
encrypting one existing, widely-read table. A dedicated table keeps the
blast radius to exactly the code that needs it.

## End-to-end flow

```
1. "Become a Vendor" wizard — new "Payout Details" step (after Catalogue,
   before Review), bank_account or mobile_wallet. Same submit as
   everything else: POST /api/public/vendors/apply, one multipart payload.
        │
        ▼
2. vendors.apply_vendor() — after the application + items + documents are
   staged (not yet committed), vendor_payment_accounts.
   create_payment_account_for_application() validates, checks cross-vendor
   duplicates, encrypts, and INSERTs. Any failure (422 invalid, 409
   duplicate) means NOTHING above it persists either — one transaction,
   one commit, at the very end of apply_vendor().
        │
        ▼
3. Admin/PM vets the application (Vendor Applications page) — a new
   "Payout Account" card: masked values, a Reveal button (audit-logged),
   Verify / Reject (with reason) actions.
        │
        ▼
4. vendors.approve_vendor_application() — HARD-BLOCKS approval (400) unless
   vendor_payment_accounts.verification_status = 'verified' for this
   application. On success, the account row is reassigned (not copied)
   from application_id to the new vendor_id in the same transaction.
        │
        ▼
5. payments.release_payout() (step M) — calls
   vendor_payment_accounts.get_vendor_payout_destination(vendor_id).
     - verified account exists -> decrypts, builds the destination, pays
       out exactly as before (zero changes to payment_providers.py /
       payment_mock_service.py).
     - missing/unverified -> VendorPayoutAccountMissing is caught, the
       order's payout_status is set to 'Failed' (the same shape the
       processors already use for "no bank IBAN on file"), a
       payment_transactions row is logged, and the existing
       payment.failed notification fires to the orderer + admin.
```

## Data model (`016_add_vendor_payment_accounts.sql`)

`vendor_payment_accounts` — one row per `vendor_applications` row
(`application_id` UNIQUE), reassigned to `vendor_id` at approval (never
duplicated):

| Column | Notes |
|---|---|
| `payout_method` | `bank_account` \| `mobile_wallet` |
| `account_title` | required, normalized (collapsed whitespace), 3-100 chars |
| `bank_name`, `branch_code` | `bank_account` only |
| `iban_encrypted` / `iban_last4` / `iban_hash` | `bank_account` only — see "Encryption & masking" |
| `account_number_encrypted` / `account_number_last4` | `bank_account` only, optional |
| `wallet_provider` | `mobile_wallet` only |
| `wallet_number_encrypted` / `wallet_last4` / `wallet_hash` | `mobile_wallet` only |
| `verification_status` | `pending` (default) \| `verified` \| `rejected` |
| `verified_by`, `verified_at`, `rejection_reason` | set by the admin actions |

`vendor_payment_account_audit_log` — permanent record of `reveal` /
`verify` / `reject` actions (who, when, note), same shape as
`vema_reorder_audit_log` (migration 015).

`pk_banks.py` — the maintained bank list (`bank_name` must be one of
these) plus each bank's SBP IBAN institution code, used only as an
informational cross-check against the entered IBAN (warns, never blocks —
the mapping isn't exhaustive).

## Validation (`vendor_payment_accounts.py` — the source of truth; the
frontend's `validation.ts` only mirrors it)

- **account_title**: required, 3-100 chars, letters/spaces/`.`/`-`/`'` only.
- **IBAN** (`bank_account`): required. Normalized (strip spaces, uppercase).
  Format `^PK\d{2}[A-Z]{4}[A-Z0-9]{16}$`, then the full ISO 13616 / mod-97
  checksum — not just the 24-char/`PK`-prefix shortcut `isPakistaniIBAN()`
  (used elsewhere in this repo) settles for.
- **account_number** (optional, `bank_account`): digits only, 8-20 chars.
- **bank_name** (`bank_account`): must be one of `pk_banks.PK_BANKS`.
- **wallet_number** (`mobile_wallet`): normalized (`+92`/`0092`/spaces/
  dashes → `03XXXXXXXXX`), then `^03\d{9}$`.
- **wallet_provider** (`mobile_wallet`): must be one of
  `pk_banks.WALLET_PROVIDERS`.
- Cross-field: a `bank_account` submission rejects any wallet field set,
  and vice versa.
- Duplicate IBAN/wallet number already attached to a *different* vendor →
  `409`, generic message (never reveals whose).
- Errors are a flat, semicolon-joined string in a `400`/`422`/`409`
  `HTTPException` — matching this endpoint's (and every other endpoint's)
  existing error shape in this backend; there's no structured field-keyed
  error JSON convention anywhere else in this codebase to match instead.

## Encryption & masking

- `iban_encrypted` / `account_number_encrypted` / `wallet_number_encrypted`
  — Fernet (`VENDOR_PAYOUT_ENCRYPTION_KEY`), mirroring
  `shipment_chain_service.py`'s existing per-user wallet-key pattern
  exactly (lazy-init, dev-mode in-memory key with a `[WARN]` if unset) —
  a separate key, a separate trust domain from `WALLET_ENCRYPTION_KEY`.
- `iban_last4` / `wallet_last4` / `account_number_last4` — plaintext, used
  for masked display (`••••1234`) without ever decrypting.
- `iban_hash` / `wallet_hash` — HMAC-SHA256 (`VENDOR_PAYOUT_HASH_KEY`), a
  non-reversible lookup key. A unique index on each lets the *database*
  reject a duplicate IBAN/wallet number across vendors — application code
  never compares decrypted values to detect duplicates.
- The only two code paths that ever decrypt: the admin "Reveal" action
  (audit-logged) and `get_vendor_payout_destination()` (step M).

## Endpoints (added onto `vendors.py`'s existing router — same resource,
same `require_role(ROLE_PROCUREMENT_MANAGER)` dependency as the rest of
vendor-application vetting)

| Method | Path | Auth |
|---|---|---|
| `GET` | `/api/public/vendors/banks` | public — wizard's bank select |
| `GET` | `/api/public/vendors/wallet-providers` | public — wizard's wallet select |
| `GET` | `/api/vendor-applications/{id}` | Admin + PM — now includes a masked `payment_account` |
| `POST` | `/api/vendor-applications/{id}/payment-account/reveal` | Admin + PM — full value, audit-logged |
| `POST` | `/api/vendor-applications/{id}/payment-account/verify` | Admin + PM |
| `POST` | `/api/vendor-applications/{id}/payment-account/reject` | Admin + PM — reason required |

## Step M integration point

```python
# payments.py — release_payout()
try:
    destination = get_vendor_payout_destination(db, order["vendor_id"])
except VendorPayoutAccountMissing as e:
    # mark payout_status='Failed', log it, notify — return, never call processor.payout()
    ...
vendor = {"name": order["vendor_name"], "bank_iban": destination["identifier"]}
result = processor.payout(order["order_code"], amount, order["currency"], vendor)
```

`payment_providers.py` and `payment_mock_service.py` are **unmodified** —
both already gate on "is this identifier non-empty" and already only ever
display its last 4 characters, so feeding them the real resolved
identifier (bank IBAN or wallet number) from the verified account, instead
of the old `vendors.bank_iban`, is the entire integration. Stripe doesn't
exist anywhere in this codebase; the task this feature was built from
described a Stripe-based payment workflow that doesn't match this repo —
see the Phase 0 findings in the corresponding session for detail.

## Environment variables (`env.example`)

```
VENDOR_PAYOUT_ENCRYPTION_KEY=   # Fernet key; blank = in-memory dev key (unreadable after restart)
VENDOR_PAYOUT_HASH_KEY=         # HMAC key for duplicate detection; blank = insecure dev fallback
```

## Known limitations

- `bank_name`→IBAN-bank-code consistency is a soft warning, not a block —
  the SBP code mapping in `pk_banks.py` isn't exhaustive.
- No post-approval "update my payout account" flow — once verified, a
  vendor's payout details are set; a change would need a new admin-facing
  endpoint, out of scope here (registration-time only, per the task).
- Rejecting an already-verified account (e.g. after a later dispute) sets
  `verification_status='rejected'`, which immediately blocks step M on the
  *next* payout attempt for that vendor — it does not retroactively touch
  any payout already paid.
- No GitHub Actions workflow exists anywhere in this repo (confirmed
  before building this), so "runnable in CI" is moot — `pytest
  tests/test_vendor_payment_accounts.py` against a local Postgres is the
  full test path, same as every other test file here.

## Testing

```bash
cd blockchain-module-main/ai-module
pytest tests/test_vendor_payment_accounts.py -v
```

Needs a live Postgres (this repo never mocks the database) for everything
except the pure IBAN-checksum/normalization tests, which are kept under
the same module skip for consistency. Covers: IBAN checksum valid/invalid,
wallet-number normalization, cross-field rejection, unknown-bank
rejection, masking output shape, duplicate-IBAN 409, the approval gate
(missing and pending-unverified), the full reveal/verify/reject cycle +
its audit trail, and step M's blocking behavior end-to-end against
`payments.release_payout()`.
