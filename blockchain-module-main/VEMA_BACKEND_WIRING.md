# VEMA Backend Wiring

**Important context this doc corrects:** the brief that produced this pass
described VEMA as an existing scaffold to "tailor" (STT/TTS/LLM/email/
orchestration services already in place, plus a `003_add_vema_complaints.sql`
migration). That scaffold did not actually exist in this repo — `FRONTEND.md`
already said so explicitly ("that backend doesn't exist in this repo yet"),
and the one file named `models/vema_service.py` was dead code: wrong DB
schema, a hardcoded path to a different machine, and never imported by
`main.py`. Everything below is a from-scratch build using the tech choices
the brief specified (local Whisper + Kokoro, Mistral API, push-to-talk over
REST, three-tier severity) — not a refactor of prior work.

## Pipeline overview

```
Customer Portal (voice or chat)
        │
        ▼
POST /api/complaints/voice  (audio upload)      POST /api/complaints/chat (text)
        │                                                  │
        ▼ stt_service.transcribe() [local Whisper]         │
        └──────────────────────────┬───────────────────────┘
                                    ▼
                    vema_orchestrator.create_ticket()
                                    │
                        llm_service.classify_complaint()
                        [Mistral API, or keyword fallback]
                       -> category, subtype, severity
                                    │
                    INSERT complaints + complaint_events
                        ("voice_transcript"/"chat_message",
                         then "system_action" logging the classification)
                                    │
                    ┌───────────────┼───────────────────┐
                    ▼               ▼                    ▼
                small            medium               critical
           auto-resolve      auto-resolve attempt   escalate immediately
           always              │         │           (no auto-resolve attempt)
                          resolved   inconclusive
                                          │
                                    escalate, remind
                                    every 30 min
                                                      escalate, remind
                                                      every 15 min
                    │                                      │
                    ▼                                      ▼
        email_service.send_customer_resolution_email   notification_service.notify_role("customer_rep", ...)
        ("Your ticket has been resolved")               reminder_scheduler checks every 1 min,
                                                          re-notifies + reschedules until CR resolves
```

Text replies (voice or chat) come from `llm_service.generate_chat_reply()`;
for voice, `tts_service.synthesize()` turns that reply into audio if Kokoro is
available, otherwise the Customer Portal just shows the text (push-to-talk
over REST stays the interaction model either way — no WebSocket streaming).

## Tech choices (matching what the brief specified, not the generic doc defaults)

| Layer | Choice | Why |
|---|---|---|
| STT | Local Whisper (`stt_service.py`, lazy-loaded `whisper.load_model()`) | Brief specifies local Whisper, not a paid cloud STT API |
| TTS | Local Kokoro (`tts_service.py`, lazy-loaded `KPipeline`) | Brief specifies local Kokoro, not gTTS/Edge-TTS/Google Cloud TTS |
| NLU / conversation | Mistral API (`llm_service.py`, `httpx` to `api.mistral.ai`) | Brief resolves the doc's "Rasa vs LLM API" question in favor of an LLM API — no Rasa dependency added |
| Audio mode | Push-to-talk over REST (`POST /api/complaints/voice` takes a full audio file, not a stream) | Matches the brief's existing-design description; no WebSocket streaming added |
| Reminder scheduler | APScheduler `BackgroundScheduler`, 1-minute poll (`reminder_scheduler.py`) | Lightest option that needs no extra infra (Redis/broker) beyond the existing Postgres — Celery beat would require standing up a broker for a single periodic job, not worth it at this scale |

### Dev-mode fallbacks (no crash, no external dependency required to run the app)

- **STT**: if `openai-whisper` isn't installed, `POST /api/complaints/voice` still
  works — it returns a placeholder transcript string instead of raising, so
  the rest of the pipeline (classification → ticket → routing) stays fully
  testable. Install `openai-whisper` + ffmpeg and set nothing else to enable
  real transcription — it's picked up automatically.
- **TTS**: if `kokoro` isn't installed, replies are text-only
  (`reply_audio_available: false`); the Customer Portal shows text instead of
  playing audio.
- **LLM**: if `MISTRAL_API_KEY` is unset, `llm_service.py` uses a deterministic
  keyword classifier (`_keyword_classify`) that scores every taxonomy subtype
  by keyword overlap and picks the best match, plus a small allow-list of
  subtypes it will "auto-resolve" on its own (`_AUTO_RESOLVABLE_SUBTYPES`).
  This is good enough to exercise and demo the full severity-routing pipeline
  without an API key, but it's a **known-weaker stand-in** for real NLU —
  e.g. it won't catch a paraphrase like "someone's stealing electricity next
  door" as Fraud/Theft the way an LLM would, because none of that sentence's
  words are in the taxonomy's literal subtype phrases. Set `MISTRAL_API_KEY`
  for real classification quality.

This mirrors the fallback pattern already established elsewhere in this
codebase (`inventory_v2.py`'s `MODEL_LOADED` check, `email_service.py`'s
SMTP dev-mode console printing) rather than introducing a new idiom.

## Severity tiers & routing (Section 5c)

| Tier | Auto-resolution attempted? | Escalation | Reminder cadence |
|---|---|---|---|
| `small` | N/A — always resolved by the system | Never (no CR involvement) | — |
| `medium` | Yes, first | Only if auto-resolution is inconclusive | Every 30 minutes while `status='escalated'` |
| `critical` | No — skipped entirely | Immediate | Every 15 minutes while `status='escalated'` |

On any resolution (auto or CR), `email_service.send_customer_resolution_email()`
fires: "Your ticket has been resolved."

`reminder_scheduler.check_and_fire_reminders()` runs every minute, finds every
`complaints` row where `status='escalated' AND next_reminder_due <= NOW()`,
notifies every `customer_rep` user via `notify_role()`, logs a `reminder`
`complaint_events` row, bumps `reminder_count`, and reschedules
`next_reminder_due` by the tier's interval. It's a background job registered
in `main.py`'s startup event, not a blocking loop — the request/response cycle
never waits on it.

## Complaint taxonomy (`taxonomy.py`)

The exact category → subtype → default-severity mapping from Section 5. The
classifier (LLM or keyword fallback) can override the default severity based
on content — e.g. `SUBTYPE_SEVERITY_OVERRIDES` bumps "wrongful disconnection"
to critical even though its category (New Connection/Disconnection) defaults
to medium, matching the brief's example.

`GET /api/complaints/taxonomy` exposes this to the frontend for building
manual-entry and filter dropdowns without duplicating the list in TypeScript.

## Data model (`004_add_vema_complaints.sql`)

- **`complaints`** — one row per ticket: who filed it (`customer_id`/name/email,
  nullable for phone-in/manual entries), `channel` (voice/chat/manual),
  `category`/`subtype`/`severity`, lifecycle `status`
  (open/auto_resolved/escalated/resolved), `vema_triggered` (drives the
  frontend badge), reminder bookkeeping (`next_reminder_due`,
  `reminder_count`, `last_reminded_at`).
- **`complaint_events`** — the full conversation history: every voice
  transcript turn, chat message, system action (classification, escalation,
  reminder, resolution), in order. This is what the CR portal's "entire
  conversation history" view reads from — not just a final summary.

Both tables follow the same idempotent-migration pattern as `001`–`003`
(`CREATE TABLE IF NOT EXISTS`, applied automatically by `database.run_schema()`
on every startup).

## New endpoints (`complaints.py`)

| Method | Path | Auth | Purpose |
|---|---|---|---|
| `POST` | `/api/complaints/voice` | customer | Push-to-talk voice complaint (multipart audio upload) |
| `POST` | `/api/complaints/chat` | customer | Text chat complaint |
| `GET` | `/api/complaints/mine` | customer | The logged-in customer's own tickets |
| `POST` | `/api/complaints/manual` | customer_rep (+admin) | Manual/phone-in ticket entry |
| `GET` | `/api/complaints` | customer_rep (+admin) | Full log, filterable by `status`/`category`/`severity`, critical-first ordering |
| `GET` | `/api/complaints/taxonomy` | public | Category → subtypes, for building forms |
| `GET` | `/api/complaints/{id}` | customer_rep/admin, or the owning customer | Full detail + conversation history |
| `PATCH` | `/api/complaints/{id}` | customer_rep (+admin) | `{"action": "resolve", "resolution": "..."}` or `{"action": "escalate", "note": "..."}` |

## Env vars (added to `ai-module/env.example`)

```
MISTRAL_API_KEY=your_mistral_key_here
MISTRAL_MODEL=mistral-small-latest
WHISPER_MODEL_SIZE=base
KOKORO_VOICE=af_heart
```

## Frontend

- `src/data/mockComplaints.ts` is deleted. `src/pages/Complaints.tsx` (Admin)
  now reads `GET /api/complaints` directly, shows a "VEMA-Triggered" badge on
  tickets where `vema_triggered=true`, and resolves via
  `PATCH /api/complaints/{id}`.
- `src/pages/Dashboard.tsx`'s "Unresolved Complaints" KPI and the "VEMA" system
  status badge now reflect real data instead of the mock seed / a hardcoded
  "In Development" label.
- The voice/chat intake widget shipped in the Customer Portal pass
  (`CUSTOMER_PORTAL_WIRING.md`); the CR ticket-log/conversation-history UI
  shipped in the CR Dashboard pass (`src/pages/cr/`).

## Bugs found via live testing (fixed in this pass or the CR Dashboard pass)

- **Timezone bug**: `_escalate()` and `reminder_scheduler.py` originally
  computed `next_reminder_due` as `datetime.utcnow() + timedelta(...)` in
  Python and bound that naive datetime to a `TIMESTAMPTZ` column. Postgres
  reinterprets a naive value using the session's local timezone (this sandbox's
  Postgres defaults to `Asia/Karachi`, UTC+5), shifting the stored instant 5
  hours early — reminders showed as immediately overdue. Fixed by computing
  `NOW() + (:minutes * INTERVAL '1 minute')` server-side instead of binding a
  Python-computed timestamp. Caught by watching the CR Dashboard's "due in Nm"
  badge show "due now" on a ticket that had just been escalated with a
  30-minute cadence.
- **Actor mislabeling**: `_resolve()`/`_escalate()`'s conversation-event
  logging hardcoded the resolving/escalating actor as `"admin"` regardless of
  which role actually took the action. Fixed by threading the real
  `"{role}:{name}"` through from `complaints.py`'s endpoints. Caught by
  resolving a ticket as the seeded `cr@nexus.pk` account and seeing the
  conversation history attribute it to "admin".
