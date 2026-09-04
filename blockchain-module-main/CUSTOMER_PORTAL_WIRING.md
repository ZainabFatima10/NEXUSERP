# Customer Portal Wiring

Built from scratch (Section 5) — the customer-facing entry point for logging
complaints by voice or text, layered on the RBAC/JWT auth from
`RBAC_WIRING.md` and the VEMA pipeline from `VEMA_BACKEND_WIRING.md`.

## Access & auth (5a)

- Marketing site nav (`Navbar.tsx`) and both hero/closing CTAs on the Landing
  page now link to `/signup` (labeled "Customer Portal") alongside a
  separate "Login"/"Staff Login" link to `/login`.
- `POST /api/auth/signup` (unchanged from Phase 1's RBAC pass) always creates
  a `role=customer` account — it's the same endpoint whether a customer signs
  up from the marketing site or anywhere else; there's no separate
  customer-specific signup endpoint.
- Login is the same shared `POST /api/auth/login` used by staff — the JWT
  carries `role`, and `ProtectedRoute`/`Login.tsx`'s `ROLE_HOME` map sends a
  customer straight to `/portal` after signing in, no separate customer login
  page needed.

## Main portal page (5b) — `src/pages/portal/CustomerPortal.tsx`

Single interface combining:

- **Chat** — text input, `Enter` or the send button calls
  `POST /api/complaints/chat`. The reply (`llm_service.generate_chat_reply`)
  renders as a VEMA bubble with the new ticket's code/severity/status.
- **Voice** — the mic button uses `MediaRecorder` (browser-native, no extra
  dependency) to record a webm clip; on stop, it's uploaded to
  `POST /api/complaints/voice` (multipart). The response includes the
  Whisper transcript (shown as the customer's own bubble, since VEMA logs it
  as their message), the classification, and — if Kokoro produced audio — a
  "Play reply" button that plays the base64 WAV inline.
- Both paths reuse the exact same `vema_orchestrator.create_ticket()` →
  severity routing → auto-resolve/escalate pipeline from
  `VEMA_BACKEND_WIRING.md`; the portal doesn't duplicate any of that logic.
- A right-hand "Your Tickets" panel (`GET /api/complaints/mine`) refreshes
  after every submission, so a returning customer sees their history
  immediately without leaving the page.
- If `navigator.mediaDevices.getUserMedia` isn't available (no mic / insecure
  context), the mic button is hidden and chat still works — voice is an
  enhancement, not a hard requirement to use the portal.

The CR-side "entire conversation history" view and the reminder-cadence
display shipped in the CR Dashboard pass (`src/pages/cr/CRDashboard.tsx`,
`TicketLog.tsx`, `src/components/TicketDetailModal.tsx`).

## Manual verification performed

Ran the full stack locally (Postgres + `uvicorn` + `vite dev`) and drove it
in a real browser:

1. Signed up a new customer at `/signup` → auto-logged-in → landed on
   `/portal`.
2. Sent a critical-severity chat message ("no electricity... complete
   outage") → got a VEMA reply with a ticket code, `critical` badge, and
   "With a Customer Representative" status; the ticket appeared in the
   sidebar immediately.
3. Sent a small-severity message ("never received my bill") → got
   "Resolved automatically" with a `small` badge.
4. Logged out, logged in as `admin@nexus.pk`, opened `/admin/complaints` —
   both tickets were there with a "VEMA-Triggered" badge, correct
   category/subtype, and the submitting customer's name.
5. Clicked Resolve on the critical ticket, entered a resolution note,
   confirmed — the ticket moved from Open to Resolved and the tab counts
   updated live.
