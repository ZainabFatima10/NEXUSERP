# CLAUDE.md

Context for Claude Code (or any AI assistant) working in this repository.

## What this is

NEXUS ERP — PowerGrid Optimizer. A FAST-NUCES Islamabad FYP (S26-043): a
single-portal ERP for Pakistani electricity distribution companies (DISCOs),
combining AI outage/demand forecasting, blockchain-simulated procurement, and
a voice/chat complaint pipeline (VEMA).

```
NEXUSERP/
├── README.md                      # setup, model performance, business rules, test checklist
├── RBAC_WIRING.md                 # roles, JWT, route guards
├── N8N_AUTOMATION_WIRING.md       # auto-reorder -> vendor email -> accept/reject workflow
├── VENDOR_ONBOARDING.md           # vendor registration -> vetting -> approved catalogue (Phase 1)
├── SHIPMENT_ESCROW.md             # order -> accept -> on-chain contract -> ship -> approve -> execute (Phase 2)
├── NOTIFICATIONS.md               # notification engine, event catalogue, SSE, outbox (Phase 3)
├── VEMA_BACKEND_WIRING.md         # voice/chat complaint pipeline, taxonomy, severity routing
├── CUSTOMER_PORTAL_WIRING.md      # customer-facing voice/chat intake UI
├── blockchain-module-main/
│   ├── ai-module/                 # FastAPI backend (despite the directory name, this is
│   │                               #   the whole backend now: forecasting + procurement + VEMA)
│   │   ├── main.py                # app entry, registers every router, runs migrations on startup
│   │   ├── database.py            # SQLAlchemy engine + run_schema() (applies 001..00N *.sql in order)
│   │   ├── 001_schema.sql .. 004_*.sql   # idempotent migrations, see "Migrations" below
│   │   ├── auth.py, rbac.py       # JWT auth + role-gating
│   │   ├── inventory_v2.py, procurement.py, contract_service.py, invoice_service.py,
│   │   │   email_service.py, notification_service.py, sales.py, n8n_service.py
│   │   ├── vendors.py, vendor_catalogue_parser.py   # vendor registration/vetting (Phase 1)
│   │   ├── vendor_orders.py, shipment_chain_service.py, payment_mock_service.py   # Phase 2
│   │   ├── taxonomy.py, stt_service.py, tts_service.py, llm_service.py,
│   │   │   vema_orchestrator.py, reminder_scheduler.py, complaints.py
│   │   ├── models/                # XGBoost training scripts + models/saved/*.pkl (gitignored)
│   │   └── api/routes/            # forecast.py, predict.py (Module 1, outage/demand ML)
│   ├── hardhat/                   # ShipmentEscrow.sol + Hardhat 2.x project (Phase 2) —
│   │                               #   separate Node/npm project, not part of ai-module
│   └── frontend/                  # React + TS + Vite + Tailwind
│       └── src/
│           ├── pages/marketing/   # public site (dark theme) — also the no-login vendor
│           │                       #   pages: BecomeVendor, VendorRespond, VendorShipmentUpdate
│           ├── pages/auth/        # Login (shared by all roles), Signup (customer-only)
│           ├── pages/vendors/     # VendorApplications, VendorCatalogue, PlaceVendorOrder,
│           │                       #   TrackingList, TrackingDetail — shared across Admin/PM layouts
│           ├── pages/, layouts/AdminLayout.tsx        # Admin (light theme, navy sidebar)
│           ├── pages/procurement/, layouts/ProcurementLayout.tsx   # Procurement Manager
│           ├── pages/cr/, layouts/CRLayout.tsx         # Customer Representative
│           └── pages/portal/CustomerPortal.tsx         # Customer Portal (voice + chat)
```

## Non-negotiable constraints (do not touch without being asked)

- **`models/train.py`, `models/train_inventory.py`, the XGBoost inference block
  in `inventory_v2.py`** (`calculate_prediction`, `MODEL_LOADED`, `pred_model`) —
  the outage/demand forecasting models. Orchestrate around them, never edit them.
- **`contract_service.py`** — the simulated Hyperledger Fabric smart-contract
  lifecycle (`create_smart_contract`, `sign_contract`, `execute_contract`,
  `reject_contract`). Call these functions; don't modify their logic. Note:
  they `json.dumps()` their payload internally, so always pass `float(...)`
  for any Decimal/NUMERIC value from Postgres before calling them (see
  "Known gotchas" below).
- **`invoice_service.py`** — ReportLab PDF generation + billing math
  (`generate_invoice_data`, `generate_invoice_pdf`). Call, don't edit.
  `generate_invoice_data` is hardcoded to one line item (matches
  `procurement_orders`); `vendor_orders.py` builds the same-shaped dict
  itself for multi-item orders and calls `generate_invoice_pdf` directly
  — see `SHIPMENT_ESCROW.md`'s "Invoice" section.
- **`hardhat/contracts/ShipmentEscrow.sol`** — the real on-chain contract
  (Phase 2). Call its functions via `shipment_chain_service.py`; don't
  edit the contract without also re-running `npx hardhat test` (31 tests)
  and re-deploying (a changed contract needs a fresh address).

## Roles & auth (see `RBAC_WIRING.md`)

Four roles, all in the same `users` table: `admin`, `customer_rep`,
`procurement_manager`, `customer`. JWT-based (`rbac.py`), issued by the one
shared `POST /api/auth/login`. `require_role(*roles)` always implicitly
includes `admin`. Public signup (`POST /api/auth/signup`) can only ever
create `customer` accounts — admin-side accounts are seeded via migration or
provisioned by an existing admin via `POST /api/auth/admin-create-user`.

Seeded dev accounts (password `nexus2026` for all three):
`admin@nexus.pk`, `cr@nexus.pk`, `procurement@nexus.pk`.

## Migrations (`ai-module/*.sql`)

`database.run_schema()` applies `001_schema.sql` first, then every
`NNN_*.sql` file in ascending order, **on every startup** — so every
migration must be idempotent and safe to re-run. Patterns already in use:
`CREATE TABLE IF NOT EXISTS`, `ADD COLUMN IF NOT EXISTS`, `ON CONFLICT`,
`DROP CONSTRAINT IF EXISTS` + re-`ADD`. The statement splitter is naive
(`sql.split(";")`) — **never put a literal `;` inside a SQL comment**, it
will be treated as a statement boundary and crash the next startup.

Next new migration should be `012_*.sql`.

## Known gotchas (found via live-testing against a real Postgres instance — worth re-checking if you touch nearby code)

1. **Decimal vs float**: `NUMERIC` columns come back from SQLAlchemy/pg8000
   as `decimal.Decimal`. `Decimal * float` raises `TypeError`. Always cast
   both sides to `float()` before arithmetic, and before passing into
   `contract_service.py` functions (which `json.dumps()` the result —
   `Decimal` isn't JSON-serializable either).
2. **Timezone**: never bind a Python `datetime.utcnow() + timedelta(...)` to
   a `TIMESTAMPTZ` column. A naive datetime gets reinterpreted in the
   Postgres session's local timezone (this environment defaults to
   `Asia/Karachi`, UTC+5), silently shifting the stored instant. Compute
   `NOW() + (:n * INTERVAL '1 minute')` server-side instead (see
   `vema_orchestrator._escalate()` / `reminder_scheduler.py`).
3. `inventory_v2.run_inventory_check()`'s trigger-priority ordering matters:
   the `<=20%` critical-stock check must come **before** the
   demand-vs-stock heuristic check, or the heuristic (which fires for
   almost every under-threshold item when no trained model is loaded)
   shadows the Procurement Manager approval path entirely.
4. Frontend: `starlette.testclient`/httpx quirks aside, `localhost` works
   more reliably than `127.0.0.1` for local dev server smoke tests in some
   shells here.
5. Migration 007 (RAG) needs the Postgres `vector` extension — if your
   local Postgres doesn't have it installed, `run_schema()` aborts there
   on every startup and every later migration (008+) silently never runs
   via the app. Apply those later migrations directly
   (`psql ... -f 00N_*.sql`) to test them in isolation on such a machine;
   this is a local-environment gap, not a bug in the migrations themselves.
6. `hardhat/` is a **separate Node/npm project** (`npm install` inside
   `hardhat/`, not the root or `ai-module/`) — pinned to Hardhat **2.x**
   (`npm install` with no version pin pulls Hardhat 3, a recent rewrite
   with a different config/test-runner shape than what's used here).
7. A `notify()` (`notification_engine.py`) `dedupe_key` suppresses *every*
   future notification with that same key for that user, not just repeats
   of one occurrence — a key built from only an event type + a stable id
   (e.g. an order id) will never fire again after the first time. Fine for
   "send this reminder once per order, ever" jobs; wrong for anything
   meant to recur (see `vendor_orders.check_chain_health`, which
   deliberately omits `dedupe_key` for exactly this reason).

## Local dev setup

```bash
# Postgres (or use docker-compose.yml)
createdb nexus_erp   # role/password per ai-module/env.example

cd blockchain-module-main/ai-module
cp env.example .env  # fill in DB_*, JWT_SECRET_KEY at minimum
pip install -r requirements.txt
uvicorn main:app --reload --port 8000   # applies all migrations on startup

cd ../frontend
npm install
npm run dev   # http://localhost:5173, proxies to :8000
```

Optional integrations gracefully no-op in dev mode when unset (see each
service file's dev-mode fallback): `MISTRAL_API_KEY` (VEMA classification —
falls back to a keyword classifier), `N8N_WEBHOOK_URL` and the other
`N8N_*_WEBHOOK_URL` vars (vendor emails — fall back to console logging
with the accept/reject/shipment-update URLs printed), SMTP vars (all
outbound email — falls back to console printing), `openai-whisper`/`kokoro`
packages (voice STT/TTS — falls back to text-only), `CHAIN_RPC_URL`
(ShipmentEscrow calls — falls back to console logging; see
`SHIPMENT_ESCROW.md`).

For the real on-chain path (optional):
```bash
cd blockchain-module-main/hardhat
npm install
npx hardhat node                                    # leave running in its own terminal
npx hardhat run scripts/deploy.js --network localhost
# set CHAIN_RPC_URL=http://127.0.0.1:8545, CHAIN_NETWORK=localhost, and
# CHAIN_SIGNER_PRIVATE_KEY to one of the dev keys `hardhat node` printed,
# in ai-module/.env, then restart uvicorn.
```

## Where to look for what

| Topic | Doc |
|---|---|
| Roles, JWT, route guards, who can call what | `RBAC_WIRING.md` |
| Auto-reorder trigger, PM approval, n8n vendor email, accept/reject | `N8N_AUTOMATION_WIRING.md` |
| Vendor registration, admin vetting, approved vendor catalogue | `VENDOR_ONBOARDING.md` |
| Order -> accept -> on-chain contract -> ship -> approve -> execute, payment lifecycle | `SHIPMENT_ESCROW.md` |
| Notification engine, event catalogue, SSE stream, outbox, preferences | `NOTIFICATIONS.md` |
| Complaint taxonomy, severity routing, reminder scheduler, STT/TTS/LLM | `VEMA_BACKEND_WIRING.md` |
| What works in the VEMA pipeline + per-portal flow diagrams (status doc) | `blockchain-module-main/VEMA_PIPELINE.md` |
| Customer-facing voice/chat portal | `CUSTOMER_PORTAL_WIRING.md` |
| Frontend routes, pages, design system tokens | `blockchain-module-main/frontend/FRONTEND.md` |
| Model performance, business rules, setup, test checklist | `README.md` |

## Testing changes

There's no automated test suite in this repo. Before calling a backend
change done: `python3 -m py_compile <file>`, then actually boot Postgres +
`uvicorn` and exercise the endpoint (a `TestClient` script or `curl`) — several
real bugs in this codebase (Decimal arithmetic, timezone handling, a wrong
seeded bcrypt hash) only surfaced when actually hitting a live database,
not from reading the code. For frontend changes: `npx tsc --noEmit`, then
`npm run dev` and click through the actual flow — don't assume a component
renders correctly from the JSX alone.
