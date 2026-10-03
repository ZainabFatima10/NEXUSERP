# NEXUS ERP — Frontend

Marketing site + Admin portal for the NEXUS ERP PowerGrid Optimizer, built with React, TypeScript, Tailwind CSS, and Vite.

## What's here

- **`/`** — public marketing site (hero, problem stats, module overview, procurement lifecycle, model performance, tech stack, CTA)
- **`/login`, `/signup`** — admin authentication, wired to `POST /api/auth/login` and `POST /api/auth/signup`
- **`/admin`** — protected dashboard shell (sidebar + topbar) with:
  - `/admin` — KPI overview, pulled live from the Inventory, Procurement, and Forecast endpoints
  - `/admin/inventory` — stock overview, order history/"reorders" view, and status alerts. Placing an order (manual or flagged-for-reorder) redirects to **Procurement**.
  - `/admin/demand-prediction` — pick a date, forecast per-item demand with the trained model (`GET /api/inventory/demand-forecast`), jump straight into Procurement to reorder any flagged item
  - `/admin/procurement` — place blockchain-verified purchase orders (smart contracts), track active/delivered orders, and pull up **billing/invoices** (see below) for any order
  - `/admin/outage-prediction` — 7-day AI outage forecast with drill-down detail per day
  - `/admin/complaints` — User complaints (VEMA) — live data from `/api/complaints`, with a "VEMA-Triggered" badge on voice/chat-originated tickets. See `VEMA_BACKEND_WIRING.md`.
  - `/admin/notifications` — consolidated notification feed

## Running locally

```bash
npm install
cp .env.example .env   # point VITE_API_URL at your backend if not on 127.0.0.1:8000
npm run dev
```

Make sure the FastAPI backend (`../ai-module`) is running first — see the top-level `README.md` / `docker-compose.yml` for that. CORS on the backend is already open to all origins, so no extra config is needed there.

```bash
npm run build     # production build to dist/
npm run preview   # preview the production build locally
```

## A note on the Complaints module

The VEMA (Voice & Email Management Agent) pipeline — local Whisper STT, local
Kokoro TTS, Mistral LLM for classification/conversation — is implemented in
`ai-module/` (`stt_service.py`, `tts_service.py`, `llm_service.py`,
`vema_orchestrator.py`, `complaints.py`, `reminder_scheduler.py`). The
`/admin/complaints` screen (and the Customer Portal / CR Dashboard screens)
run on live data from `/api/complaints`. `src/data/mockComplaints.ts` has been
removed. See `VEMA_BACKEND_WIRING.md` for the full pipeline, taxonomy, and
severity/reminder routing.

**RAG (Q&A + complaint grounding)** — `/admin/categories` (`CategoryReference.tsx`,
also at `/cr/categories`) reads `GET /api/complaints/categories`, the one
source-of-truth taxonomy reference with live ticket counts; nothing here
duplicates the category list. `/admin/knowledge-base` (`RagAdmin.tsx`,
admin-only) is the Feature C/D admin surface: document counts per source, a
dataset-file upload, a reindex button, and a test-query box hitting
`POST /api/rag/query`. The Customer Portal's live voice/chat conversation
(`CustomerPortal.tsx`) now also calls `POST /api/rag/query` itself, before
either path decides what to do with a message: a genuine question or
smalltalk is answered directly (no ticket filed); only `complaint_intake`
still opens the existing review-before-submit draft panel / confirm-and-file
voice loop. Routing fails open to the complaint flow if the RAG call errors,
so a customer's message is never silently dropped. `data/qa/seed_qa.jsonl`
and `data/qa/sample_import.xlsx` (backend) are sample Q&A content for the
team to review/replace, not real historical data — see `VEMA_RAG.md`.

## Billing / procurement invoices

Placing a blockchain procurement order — from the **Procurement** tab (manual/smart-contract order), or an auto-triggered one from Inventory Check / VEMA-style triggers — generates a real bill:

- Every `inventory_items` row has a `unit_price` (USD) — seeded in `ai-module/001_schema.sql` / `ai-module/002_add_unit_price.sql`, and returned by the inventory overview endpoint. The order form in `Procurement.tsx` auto-fills this price when you pick an item, but it stays editable.
- `POST /api/procurement/manual-reorder` and `POST /api/procurement/orders` now default `unit_price` to the item's catalog price when the caller doesn't send one, so `total_price` is always computed.
- `GET /api/procurement/orders/{id}/invoice` returns a structured, itemized bill (subtotal, 0.5% blockchain verification fee, total, blockchain tx hash/status). Built by `ai-module/invoice_service.py`.
- `GET /api/procurement/orders/{id}/invoice/pdf` renders the same data as a downloadable PDF (ReportLab — added to `requirements.txt`).
- On the frontend, `src/components/InvoiceModal.tsx` shows the bill and a **"Download Invoice (PDF)"** button:
  - Opens automatically right after an order is placed on the Procurement tab.
  - Also reachable any time via the **Billing** tab in `OrderDetailModal.tsx`, or the "Invoice" link next to any order in the Procurement tables.
- `src/services/api.ts` exposes `getInvoice(orderId)` and `downloadInvoicePdf(orderId)` (the latter does a raw `fetch` + blob download, since the response isn't JSON).

## Demand Prediction

`/admin/demand-prediction` calls `GET /api/inventory/demand-forecast?date=YYYY-MM-DD`, which runs every catalog item through the trained XGBoost model (`ai-module/models/saved/inventory_model.pkl` + label encoders) for the chosen date, deriving season/month/day-of-week features automatically. If the trained model artifacts aren't present, it falls back to the same deterministic heuristic used elsewhere in the backend (`MODEL_LOADED` is returned so the UI can show which mode it's in). Items flagged `reorder_needed` link straight into Procurement with the item and suggested quantity pre-filled.

## Known backend fixes in this pass

`ai-module/notification_service.py`'s `create_notification()` was calling `db.execute(...)` with a **raw SQL string** instead of `text(...)` — the only spot in the codebase that skipped the wrapper. Under SQLAlchemy 2.0 this raises instead of executing, which is what caused **"Run Inventory Check"** and **"Confirm/Place Reorder"** to fail against a real backend (both flows create notifications as part of creating an order). Fixed by wrapping the query in `text()`. Also hardened `POST /api/inventory/check` to catch and report per-item failures instead of aborting the whole scan, and made the order-creation notification call non-fatal.

## Design system

- Admin app: light theme, dark navy sidebar — matches the FYP report's Figma-style mockups (Figures 3.29–3.47).
- Marketing site: dark "power-grid" theme (deep navy, electric blue/cyan), circuit-grid backdrop, `Chakra Petch` headings + `Manrope` body (`JetBrains Mono` for order codes/hashes/data).
- Brand mark: `src/components/Logo.tsx` (`LogoMark` for the icon alone, `Logo` for icon + wordmark) — a hex "grid node" with a current bolt, echoing the marketing site's grid-bg/current-line/node-dot motifs. Used everywhere the old lucide `Zap`-in-a-box placeholder used to be (sidebar, navbar, footer, auth pages, 404, invoice modal), plus the favicon in `index.html`.
- All color/spacing tokens live in `tailwind.config.js` and `src/index.css` — extend those rather than hardcoding new colors.
