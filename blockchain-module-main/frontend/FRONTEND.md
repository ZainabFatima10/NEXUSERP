# NEXUS ERP — Frontend

Marketing site + Admin portal for the NEXUS ERP PowerGrid Optimizer, built with React, TypeScript, Tailwind CSS, and Vite.

## What's here

- **`/`** — public marketing site (hero, problem stats, module overview, procurement lifecycle, model performance, tech stack, CTA)
- **`/become-a-vendor`** — public, no login: multi-step "Become a Vendor" application (see **Vendor registration & vetting** below)
- **`/vendor/respond`** — public, no login: Accept/Reject a Phase 2 vendor order (see **Vendor orders & shipment escrow** below)
- **`/vendor/shipment`** — public, no login, multi-use link: vendor reports Dispatched / In Transit / Out for Delivery
- **`/login`, `/signup`** — admin authentication, wired to `POST /api/auth/login` and `POST /api/auth/signup`
- **`/admin`** — protected dashboard shell (sidebar + topbar) with:
  - `/admin` — KPI overview, pulled live from the Inventory, Procurement, and Forecast endpoints
  - `/admin/inventory` — stock overview, order history/"reorders" view, and status alerts. Placing an order (manual or flagged-for-reorder) redirects to **Procurement**.
  - `/admin/demand-prediction` — pick a date, forecast per-item demand with the trained model (`GET /api/inventory/demand-forecast`), jump straight into Procurement to reorder any flagged item
  - `/admin/procurement` — place blockchain-*simulated* purchase orders (the original Hyperledger-Fabric-style auto-reorder flow), track active/delivered orders, and pull up **billing/invoices** (see below) for any order
  - `/admin/vendor-applications` — vet "Become a Vendor" submissions: approve/reject/request-info, document review, vetting checklist (also at `/procurement/vendor-applications`)
  - `/admin/vendor-catalogue` — browse approved vendors and what they sell; "Create Order" jumps into **Place Vendor Order** with the vendor preselected (also at `/procurement/vendor-catalogue`)
  - `/admin/place-order` — place a *real* on-chain escrow order against a vendor's own catalogue (also at `/procurement/place-order`) — see **Vendor orders & shipment escrow** below
  - `/admin/tracking`, `/admin/tracking/:orderId` — Order Tracking: every order an orderer placed, from placement to payment, with the live progress bar and shipment timeline (also at `/procurement/tracking`)
  - `/admin/outage-prediction` — 7-day AI outage forecast with drill-down detail per day
  - `/admin/complaints` — User complaints (VEMA) — live data from `/api/complaints`, with a "VEMA-Triggered" badge on voice/chat-originated tickets. See `VEMA_BACKEND_WIRING.md`.
  - `/admin/notifications` — consolidated notification feed (tabs, severity filter, search, archive) — see **Notifications** below
  - `/admin/notifications/preferences` — per-event in-app/email toggles

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

## Vendor registration & vetting

Vendors never get a login — see `VENDOR_ONBOARDING.md` for the full flow and
field list. Frontend pieces, all wired to real endpoints (no mock data):

- `src/pages/marketing/BecomeVendor.tsx` (`/become-a-vendor`, public) — a
  6-step form (company → contact/location → commercial terms → documents →
  catalogue → review). Catalogue rows come from a manual grid, an
  `.xlsx`/`.csv` upload previewed via `POST /api/public/vendors/items/parse`
  (bad rows shown with reasons, never silently dropped), or both merged
  together. Submits via `POST /api/public/vendors/apply` (multipart:
  JSON payload + document files). A honeypot field and a per-IP rate limit
  guard the public endpoint server-side.
- `src/pages/vendors/VendorApplications.tsx` — shared by
  `/admin/vendor-applications` and `/procurement/vendor-applications`
  (same component, same `GET /api/vendor-applications` endpoint, gated by
  RBAC either way — this mirrors how `CategoryReference.tsx` / `Notifications.tsx`
  are already reused across layouts). Tabs by status, a vetting checklist,
  and Approve / Reject (reason required) / Request Info actions.
- `src/pages/vendors/VendorCatalogue.tsx` — same shared-component pattern,
  mounted at `/admin/vendor-catalogue` and `/procurement/vendor-catalogue`.
  Lists only `status='active'` vendors (enforced server-side, not just
  hidden in the UI) with their catalogue and prices. "Create Order" calls
  `navigate(placeOrderBase, { state: { prefillVendorId } })` into **Place
  Vendor Order** (Phase 2, below) — superseding the Phase 1 version of this
  note, which pointed into `Procurement.tsx`'s internal-inventory flow and
  could only order items already linked in `inventory_items`. `Procurement.tsx`
  itself still has its own, separate vendor-filter hook (`prefillVendorId`
  filtering its item dropdown by `vendor_id`) from that earlier pass — inert
  now that nothing navigates there with that state, but harmless, so it
  was left in place rather than ripped out.

## Vendor orders & shipment escrow (Phase 2)

Order → vendor accept (email, no login) → real on-chain smart contract →
shipment tracking → orderer approval/dispute → execution → (mocked, Phase
4-real-later) payment capture. See `SHIPMENT_ESCROW.md` for the full
backend flow and the contract itself. All frontend pieces are wired to
real endpoints — the one "mock" is payments (Phase 4), stated plainly in
the UI's payment line ("Funds authorized — held...") rather than hidden.

- `src/pages/vendors/PlaceVendorOrder.tsx` (`/admin/place-order`,
  `/procurement/place-order`) — vendor-first order placement directly
  against that vendor's `vendor_items` catalogue (no `inventory_items`
  link required — this is what actually closes the Phase 1 limitation
  above). Destination fields, a multi-row item picker with live subtotal,
  submits via `POST /api/vendor-orders`.
- `src/pages/marketing/VendorRespond.tsx` (`/vendor/respond`, public) —
  the Accept/Reject landing page from the order email. Fetches the order
  via a token-secured `GET`, requires an explicit button click before the
  mutating `POST` (protects against an email/security scanner silently
  pre-fetching the link).
- `src/pages/marketing/VendorShipmentUpdate.tsx` (`/vendor/shipment`,
  public, multi-use link) — the vendor marks Dispatched (carrier/tracking/ETA)
  and posts In Transit / Out for Delivery checkpoints. Cannot mark Arrived
  or approve anything — the UI doesn't even render those controls, and the
  backend would reject the call regardless.
- `src/pages/vendors/TrackingList.tsx` / `TrackingDetail.tsx`
  (`/admin/tracking[/:orderId]`, `/procurement/tracking[/:orderId]`) — the
  orderer's dedicated view. List: summary-card filters, a mini progress
  bar per row, a "Confirm arrival" / "Approve or dispute" action chip when
  something needs the signed-in user's attention. Detail: full progress
  bar (distinct banners for Rejected/Expired/Cancelled/Disputed rather
  than a half-filled bar), shipment + contract panels (with a "Verified
  on-chain" badge once a chain tx confirms), the full event timeline with
  tx hashes, and the orderer-only action panel (confirm arrival / approve
  with a required inspection checkbox + confirmation modal / dispute with
  a reason). Admins/PMs viewing someone else's order see all of this but
  the action panel simply isn't rendered for them — `tracking_detail`'s
  `is_orderer` flag drives it, and the backend independently rejects the
  underlying calls either way.

## Notifications (Phase 3)

See `NOTIFICATIONS.md` for the backend engine/event catalogue. Frontend pieces:

- `src/components/Topbar.tsx` — bell with a dropdown (latest 10, grouped
  Today/Earlier), unread badge, mark-all-read, browser tab title shows
  `(N) ...` while unread. Subscribes to the live stream
  (`subscribeToNotifications()` in `services/api.ts` — tries SSE, falls
  back to 15s polling transparently on any connection error) and fires a
  toast for every incoming event; `requires_action` ones persist until
  dismissed and carry a deep-link action button.
- `src/hooks/use-toast.tsx` — extended with optional `persist` and
  `action` fields (no existing `toast({...})` call site needed to change).
- `src/pages/Notifications.tsx` — tabs (All/Unread/Action Needed),
  severity filter, search, archive, "Load more" pagination.
- `src/pages/NotificationPreferences.tsx` — per-event in-app/email
  toggles grouped by category; locked (critical/requires-action) rows
  show a lock icon and a disabled in-app toggle.
- `src/hooks/use-sidebar-badges.ts` — Order Tracking's action-needed
  count and Vendor Applications' pending count, polled every 60s, shared
  by `AdminLayout`/`ProcurementLayout` via `Sidebar`'s new `badges` prop.
- `src/pages/vendors/TrackingDetail.tsx` — also subscribes to the stream;
  any notification whose `entity_type`/`entity_id` matches the open order
  triggers a silent background refetch (no spinner/toast) plus a
  "Last updated" timestamp, so the progress bar/timeline update live
  without a manual reload.

## Demand Prediction

`/admin/demand-prediction` calls `GET /api/inventory/demand-forecast?date=YYYY-MM-DD`, which runs every catalog item through the trained XGBoost model (`ai-module/models/saved/inventory_model.pkl` + label encoders) for the chosen date, deriving season/month/day-of-week features automatically. If the trained model artifacts aren't present, it falls back to the same deterministic heuristic used elsewhere in the backend (`MODEL_LOADED` is returned so the UI can show which mode it's in). Items flagged `reorder_needed` link straight into Procurement with the item and suggested quantity pre-filled.

## Known backend fixes in this pass

`ai-module/notification_service.py`'s `create_notification()` was calling `db.execute(...)` with a **raw SQL string** instead of `text(...)` — the only spot in the codebase that skipped the wrapper. Under SQLAlchemy 2.0 this raises instead of executing, which is what caused **"Run Inventory Check"** and **"Confirm/Place Reorder"** to fail against a real backend (both flows create notifications as part of creating an order). Fixed by wrapping the query in `text()`. Also hardened `POST /api/inventory/check` to catch and report per-item failures instead of aborting the whole scan, and made the order-creation notification call non-fatal.

## Design system

- Admin app: light theme, dark navy sidebar — matches the FYP report's Figma-style mockups (Figures 3.29–3.47).
- Marketing site: dark "power-grid" theme (deep navy, electric blue/cyan), circuit-grid backdrop, `Chakra Petch` headings + `Manrope` body (`JetBrains Mono` for order codes/hashes/data).
- Brand mark: `src/components/Logo.tsx` (`LogoMark` for the icon alone, `Logo` for icon + wordmark) — a hex "grid node" with a current bolt, echoing the marketing site's grid-bg/current-line/node-dot motifs. Used everywhere the old lucide `Zap`-in-a-box placeholder used to be (sidebar, navbar, footer, auth pages, 404, invoice modal), plus the favicon in `index.html`.
- All color/spacing tokens live in `tailwind.config.js` and `src/index.css` — extend those rather than hardcoding new colors.
