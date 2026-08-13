# NEXUS ERP — Frontend

Marketing site + Admin portal for the NEXUS ERP PowerGrid Optimizer, built with React, TypeScript, Tailwind CSS, and Vite.

## What's here

- **`/`** — public marketing site (hero, problem stats, module overview, procurement lifecycle, model performance, tech stack, CTA)
- **`/login`, `/signup`** — admin authentication, wired to `POST /api/auth/login` and `POST /api/auth/signup`
- **`/admin`** — protected dashboard shell (sidebar + topbar) with:
  - `/admin` — KPI overview, pulled live from the Inventory, Procurement, and Forecast endpoints
  - `/admin/inventory` — stock overview, current orders, order history, reorders (blockchain-verified procurement lifecycle)
  - `/admin/outage-prediction` — 7-day AI outage forecast with drill-down detail per day
  - `/admin/complaints` — User complaints (VEMA). **Running on local demo data** — the backend for this module isn't built yet (see note below).
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

The FYP report describes a VEMA (Voice & Email Management Agent) pipeline — Whisper for transcription, Rasa for intent handling, auto-ticketing — as a planned module. That backend doesn't exist in this repo yet (no `/api/complaints` routes). The `/admin/complaints` screen is fully built and interactive against seed data in `src/data/mockComplaints.ts` so the UI/UX is demoable end-to-end. Once the VEMA backend ships:

1. Add the matching functions to `src/services/api.ts` (list complaints, resolve, escalate — following the same pattern as the other modules there).
2. Swap the `SEED_COMPLAINTS` import in `src/pages/Complaints.tsx` for real API calls (the component's local state/handlers are already shaped to drop straight in).

## Design system

- Admin app: light theme, dark navy sidebar — matches the FYP report's Figma-style mockups (Figures 3.29–3.47).
- Marketing site: dark "power-grid" theme (deep navy, electric blue/cyan), circuit-grid backdrop, `Space Grotesk` headings + `Inter` body.
- All color/spacing tokens live in `tailwind.config.js` and `src/index.css` — extend those rather than hardcoding new colors.
