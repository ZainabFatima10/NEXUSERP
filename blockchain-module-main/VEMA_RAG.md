# VEMA_RAG.md — Retrieval-Augmented Q&A and Complaint Grounding

How VEMA answers customer questions and grounds complaint handling from a
retrieval store, instead of relying only on the LLM's general knowledge or
guessing. Two features share one retrieval layer:

- **Feature C** — informational Q&A (`POST /api/rag/query`)
- **Feature D** — the same retrieval layer assisting (never deciding) the
  existing complaint-intake flow: category suggestion, follow-up questions,
  guidance while filing, duplicate/known-issue awareness, and "similar
  resolved cases" for staff

The deterministic ticket lifecycle (`vema_orchestrator.py` — classification
validation, severity tiers, reminders, resolution) is **unchanged**. RAG
informs it; it never writes a ticket, sets a severity, or decides anything
that code already owned.

## End-to-end flow

```
1. Customer turn (voice or chat) arrives at the existing complaint
   endpoints, OR a new question arrives at POST /api/rag/query
        │
        ▼
2. rag/intent.py classifies: complaint_intake | information_question | smalltalk
   (keyword heuristic in dev-mode; strict-JSON via llm_client.py — Gemini,
   then Mistral — when a provider is configured)
        │
        ├── complaint_intake  → unchanged: POST /api/complaints/chat|voice
        │                        (vema_orchestrator.create_ticket — see step 5)
        ├── smalltalk         → a canned reply, no retrieval
        └── information_question
                │
                ▼
3. rag/retrieval.py: embed the query (rag/embeddings.py), pgvector cosine
   search over rag_documents (doc_type='qa'), filtered by category if given,
   then a lexical-overlap gate (see "A gap the eval script caught" below)
        │
        ▼
4. rag/generation.py: the configured provider (llm_client.py) answers ONLY
   from the retrieved Q&A pairs (dev-mode: returns the top match's stored
   answer verbatim — still genuinely grounded, just no LLM synthesis) →
   echo_guard.strip_echo()
   (Feature A) → honest "I don't know, want to file a complaint?" if
   nothing cleared the relevance bar
        │
        ▼
   bot_reply → (voice path) Kokoro TTS → spoken back

5. Inside create_ticket() (complaint_intake path), RAG assists three points
   without ever writing the ticket itself:
     - rag/category_kb.py's taxonomy-derived documents can few-shot-ground
       the LLM category call (LLM path only — the dev-mode keyword
       classifier doesn't need this)
     - taxonomy.py's required_fields drive which field to ask for next
     - _find_duplicate_ticket() links a new ticket to an already-open one
       in the same category+area — creation is never blocked
   Severity, routing, and the ticket write itself stay exactly the
   pre-existing deterministic code.
```

## LLM / embedding provider — two pivots, both made by testing, not assumed

**Pivot 1 — embeddings, torch blocked.** The plan was a local multilingual
`sentence-transformers` model (`paraphrase-multilingual-MiniLM-L12-v2`).
Testing it on this machine:

```
OSError: [WinError 4551] An Application Control policy has blocked this
file. Error loading "...\torch\lib\torch.dll"...
```

Windows Application Control blocks `torch.dll` outright — not a pip or
version problem, a system security policy this session has no business
overriding. `torch`/`sentence-transformers`/`transformers` were installed,
confirmed unusable, and uninstalled again.

**Pivot 2 — Mistral wasn't a workable free option for the team.** The
initial design used Mistral for both chat completions and embeddings
(reusing `MISTRAL_API_KEY`). The team found Mistral's tier requirements
weren't actually free for this use — swapped to **Gemini** (Google AI
Studio, `https://aistudio.google.com/apikey`) as the primary provider,
genuinely free with no card required. `llm_client.py` is the one shared
module both `llm_service.py` and `rag/`'s intent/generation code call
through, so this swap happened in one place: **Gemini → Mistral → dev-mode
keyword/canned fallback**, in that priority order (Mistral stays as a
secondary option for anyone who already has that key).

| | Condition | What |
|---|---|---|
| **Primary** | `GEMINI_API_KEY` set | Gemini's embeddings API (`gemini-embedding-001` truncated to 768-dim via `outputDimensionality`) + `gemini-2.5-flash-lite` for chat/classification/intent. **Live-verified against a real key 2026-09-29** (see below). |
| **Secondary** | only `MISTRAL_API_KEY` set | Mistral (`mistral-small-latest` chat) — unchanged from before, still untested live (no Mistral key available). |
| **Fallback** | either provider's call fails (rate limit, network) or neither key is set | scikit-learn `HashingVectorizer` (768-dim) for embeddings; the deterministic keyword classifier + canned replies for chat. Exercised automatically and correctly every time Gemini's free-tier quota ran out during live testing — see "Live-testing the real Gemini key" below. |

### Model names move fast on this API — what actually worked (2026-09-29)

The originally-coded defaults (`gemini-2.0-flash`, `text-embedding-004`) no
longer exist on the API at all (`404`) — both were retired after this
project's knowledge cutoff. Diagnosed live via `GET /v1beta/models?key=...`
and confirmed corrected:

- **Chat/classification**: tried `gemini-flash-latest` (timed out twice),
  `gemini-2.5-flash` (`404`, "no longer available to new users, use
  gemini-3.8-flash"), `gemini-3.8-flash` (`503`, "high demand"). Settled on
  **`gemini-2.5-flash-lite`** — responded reliably in both plain-text and
  JSON mode.
- **Embeddings**: `text-embedding-004` is retired; its replacement
  **`gemini-embedding-001`** is natively **3072-dim**, not 768 — would have
  silently broken the `vector(768)` schema. Fix: pass
  `"outputDimensionality": 768` in each request object (confirmed via a
  direct test to return exactly 768 values, on both the singular
  `:embedContent` and the batch `:embedContent`s endpoints) — a genuinely
  supported Matryoshka-style truncation, not a workaround. No new migration
  was needed.

If these stop working again, re-run `GET /v1beta/models?key=<your key>` to
see what's current before guessing a name.

### Live-testing the real Gemini key — free tier is capped at 20 requests/day per model

Once a real key was added, live end-to-end testing (`classify_complaint`,
`generate_chat_reply`, `classify_intent`, `/api/rag/query`, embedding a
23-document seed corpus + reindexing the category KB and resolved tickets)
worked correctly — until Gemini started returning `429`s. The raw error body
identifies the quota precisely:

```
quotaId: "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
quotaValue: "20"   (model: gemini-2.5-flash-lite)
```

This project's free tier allows only **20 requests/day per model** — enough
to prove the integration works, not enough for sustained real usage or a
long testing session. Two things worth knowing if you hit this:
1. It resets daily; a lower-traffic demo (a handful of live calls) stays
   under it.
2. Every fallback held up correctly under it: `chat_json`/`chat_text`
   return `None` on any failure (never raise), and every caller's dev-mode
   fallback took over cleanly and instantly — the full pytest suite (see
   below) and a burst of manual `/api/complaints/chat` calls all completed
   successfully even while `429`s were firing, because they use the
   *actual ticket_code*, not a network response.
3. Raising this needs a Google Cloud billing account attached to the
   project (still free-tier pricing, but unlocks the standard, much higher
   free-tier RPD) — outside the scope of a code change.

### Every LLM-backed voice-call feature now has a real per-turn call budget

Adding the one-shot clarifying follow-up question (`classify_complaint()`'s
`followup_question` field, used by `/api/complaints/preview` and
`CustomerPortal.tsx`'s voice call) is a second, concrete lesson from the
20/day cap above: a single complaint turn in a live call can trigger
several Gemini calls back to back — intent routing (`/api/rag/query`),
classification, and the post-file conversational reply. The follow-up
question was first built as its *own* separate `chat_json` call
(classify, then a second call asking "what's missing") — correct, but it
roughly doubled the quota cost of every complaint turn, and on a 20/day
budget that meant the feature stopped firing (silently, correctly, via the
existing fail-open path) after only a handful of turns, read by a live
user as "it doesn't ask follow-up questions" with no error anywhere to
explain why.

Fixed by folding the follow-up decision into `classify_complaint()`'s
*existing* call instead of a second one — the taxonomy's `required_fields`
were already embedded in that prompt for classification, so asking the
same call to also decide "is anything important missing, and if so what's
the one question to ask" costs nothing extra. Confirmed via the backend
log: before the merge, one preview request logged two consecutive
`[WARN] Gemini call failed` lines; after, exactly one. **Lesson for any
future addition to this voice flow**: before adding a new LLM call to a
per-turn path, check whether it can be folded into an existing one in the
same turn — the 20/day cap makes this a real design constraint here, not
just a performance nicety.

### A hallucination a live LLM reply caught (and fixed)

`generate_chat_reply()`'s prompt told Gemini to "let them know it's been
recorded as a ticket" but never gave it the real ticket code — with a real
model actually generating prose (rather than the old dev-mode template),
it predictably **invented a plausible-looking ticket number** ("ticket
#12345") that had nothing to do with the real one. This is exactly the
"no fabricated data presented as real" failure mode the project's
guardrails exist to catch, and it only surfaces once a real LLM is in the
loop — no dev-mode fallback or hashing-embedding test could have found it.

Fix: the frontend (`CustomerPortal.tsx`) already renders the real
`ticket_code` as its own badge, independent of the chat bubble text, so the
reply text never needed to state one. `_CHAT_SYSTEM_PROMPT` in
`llm_service.py` now explicitly forbids stating, inventing, or guessing any
ticket number — confirmed fixed by re-running the same complaint text
several times post-fix.

`rag_documents.embedding` is `vector(768)` (migration 008 — widened from
007's `vector(512)` when the primary provider changed, wiping the then-23-
document corpus and requiring a re-ingest since pgvector enforces dimension
per column). Introducing a third backend with yet another output width
means widening again and re-ingesting — the schema doesn't try to support
two dimensions in one column.

## A gap the eval script caught: cosine similarity alone isn't enough

`HashingVectorizer` cosine scores do not reliably separate in-domain from
out-of-domain text. Measured against the real 23-document seed corpus:

```
"who won the cricket match yesterday"  -> top score 0.202 (against an unrelated doc)
"what is the capital of France"        -> top score 0.382 (against an unrelated doc)
"my bill seems too high this month"    -> top score 0.092 (against the RIGHT doc)
```

A 512-dimension hash space is small enough that short strings collide into
overlapping buckets regardless of actual meaning — an out-of-domain query
can score *higher* than a genuine in-domain paraphrase. `RAG_MIN_SIMILARITY`
alone cannot fix this; raising it high enough to reject "capital of France"
would also reject real matches like the billing one above.

**Fix**: `rag/retrieval.py` adds a lexical-overlap gate on top of the
similarity threshold — a result only counts if it shares at least one real
(non-stopword, length > 3) word with the query, checked against both the
question and the answer. This directly fixes the demonstrated false
positives (`test_retrieval.py::test_out_of_domain_query_returns_nothing`)
without needing semantic embeddings. It's a mitigation for a disclosed
embedding-quality gap, not a substitute for real embeddings — a semantic
model wouldn't have this specific failure mode at all.

## Measured retrieval quality (this environment's actual numbers)

`python -m rag.eval.run_eval` against `rag/eval/eval_set.jsonl` (12
paraphrased in-domain queries, 5 out-of-domain):

**Hashing fallback** (no API key / Gemini unavailable):

```
hit@1: 6/12 (50%)
hit@3: 8/12 (67%)
hit@5: 8/12 (67%)
groundedness-consistency (in-domain): 12/12 (100%)
no-answer precision (out-of-domain):  4/5 (80%)
```

**Real Gemini embeddings** (`gemini-embedding-001`, truncated to 768-dim),
measured 2026-09-29 against the same 23-document corpus + eval set:

```
hit@1: 8/12 (67%)
hit@3: 9/12 (75%)
hit@5: 9/12 (75%)
groundedness-consistency (in-domain): 12/12 (100%)
no-answer precision (out-of-domain):  4/5 (80%)
```

Confirms the prediction below: real semantic embeddings meaningfully
improve retrieval (hit@1 50%→67%) without changing groundedness or
no-answer precision, which are governed by the lexical-overlap gate and
generation logic, not the embedding backend. The one remaining false
positive ("recommend a good restaurant nearby") still slips past the
lexical gate on a coincidentally shared common word — a lexical-overlap
gate weakness, not an embedding-quality one, and unaffected by the
provider swap. Also observed directly (not part of the scored eval): a
genuinely out-of-domain query ("what is the capital of France") that used
to score *higher* than a real billing match under hashing (0.382 vs 0.092)
now scores far below any real match (below the lexical gate's threshold
entirely) under real Gemini embeddings — the false-positive risk described
below is specific to the hashing fallback.

## Two intent-routing bugs a live test caught (and fixed)

Both `rag/intent.py`'s dev-mode keyword heuristic:

1. **"How do I report a wrong bill?" was misrouted to `complaint_intake`.**
   `_COMPLAINT_KEYWORDS` includes "wrong bill"; the keyword check ran before
   the question-starter check, so a genuine process question about billing
   lost to a substring match. Fixed by tiering: strong, unambiguous question
   openers ("how do i", "can i", "is there"...) are checked *first* — these
   essentially never describe an active problem being reported — complaint
   keywords second, weaker question signals (why/who/ends-with-`?`) last.
2. Verified the reorder didn't break the reverse case: "There is no
   electricity in my area" (no question opener, no `?`) still correctly
   routes to `complaint_intake`.

See `tests/test_intent.py` for both as regression tests.

## Dataset ingestion (Feature C)

```bash
python -m rag.ingest --path data/qa/ --rebuild                    # a whole directory
python -m rag.ingest --path some_export.csv \
    --question-col Question --answer-col Answer --category-col Cat # custom columns
```

Supports **CSV, JSON** (array of objects, or `{"data": [...]}`), **JSONL**,
and **XLSX** (needs `openpyxl`; skips with a clear message if it isn't
installed — never crashes the run). Column names default to
`question`/`answer`/`category`/`language`/`source`; override any of them per
run so a public Q&A dataset can be dropped in without touching code.

**Defensive by construction**: a malformed line, a missing question/answer,
or an unreadable row is logged and skipped — it never aborts the batch
(verified in `tests/test_ingest.py` with a file mixing valid rows, empty
fields, and literally invalid JSON on one line). Near-duplicate questions
(`SequenceMatcher` ratio ≥ 0.92) are deduped **against the database**, not
just the current batch — re-running `ingest_file()` on the same file twice
is a no-op, not a second copy (this needed a real fix: the first version
only deduped within one file's own rows, then silently re-duplicated
everything on a second run because the seed dataset carries its own
`"source"` field per row that didn't match the file-based default the dedup
query was scoped to).

**Seed dataset**: `data/qa/seed_qa.jsonl` — 23 sample DISCO-style Q&A pairs
(billing, meter, connections, outages, fraud, infrastructure, process
questions; English + Roman-Urdu). **Sample content for the team to review
and extend, not official policy or real historical data.**

No real Q&A datasets were already in the repo — the seed set above is
newly authored for this feature.

## Feature D — the RAG-grounded complaint path

Three sources in one shared table (`rag_documents.doc_type`):

| `doc_type` | Built from | Purpose |
|---|---|---|
| `qa` | Ingested datasets (above) | Also answers "how does the process work" questions asked mid-intake |
| `category_kb` | `taxonomy.py`, automatically (`rag/category_kb.py`) | Category description + examples as the retrieval key, guidance text as the answer |
| `resolved_ticket` | Resolved/auto-resolved complaints (`rag/resolved_tickets.py`) | Anonymized summaries for staff-only "similar cases" |

### The hard boundary, respected

RAG **suggests**; existing code **decides and writes**. Concretely:
`_find_duplicate_ticket()` only reads and links (`related_ticket_id`) —
`create_ticket()`'s own INSERT already happened before it runs. Severity is
never touched by RAG; `default_severity_for()` + `SUBTYPE_SEVERITY_OVERRIDES`
remain the only source. If retrieval is empty or the whole RAG layer is
down, `create_ticket()` completes exactly as it did before this feature
existed — verified structurally: nothing in the create-ticket path can raise
because a RAG call fails (each RAG touchpoint is `try`/`except`-wrapped, see
`vema_orchestrator.py`'s resolve hook and `n8n`-style non-fatal pattern used
throughout this codebase).

### PII scrubbing — two layers, not one

`resolved_ticket` documents are built from **category + subtype only**
(`"Billing Issues — overbilling/incorrect meter reading"`) for the
retrieval key — a fixed taxonomy vocabulary, zero free text, zero PII by
construction. The customer's original complaint description is **never**
embedded. Only the staff-written resolution note becomes the "answer", and
that note still goes through `rag/pii.py`'s regex scrubbing (phone, CNIC,
email, long digit sequences/account-meter numbers) plus an exact-match
redaction of that specific ticket's own `customer_name`.

**Disclosed limitation**: free-form name detection beyond the ticket's own
known name is not attempted — there's no NER model available (same
torch-blocked-DLL problem as the embeddings). Given layer one above, the
blast radius of a residual name slipping through is limited to whatever a
staff member happened to type in a resolution note, not the customer's own
complaint text. `tests/test_pii.py` (10 cases, all passing) is why
`RAG_INDEX_RESOLVED_TICKETS` defaults to **on** rather than off — the spec's
own instruction was to default off unless the scrub tests pass.

### Duplicate/known-issue rule — proposed, not precise

Same `category` AND an already-`escalated` (open) ticket AND overlapping
free-text `area` (case-insensitive substring match, checked both
directions — `area` has no controlled vocabulary in this schema, it's
whatever the customer typed, so `"G-11"` needs to match `"G-11 Islamabad"`).
This is a heuristic, not a geo-match — flagged for team review, same as the
spec asked. Creation is never blocked; the new ticket just gets
`related_ticket_id` pointed at the existing one and the response carries
`related_ticket_reference`.

## API additions

```
POST /api/rag/query      { question, category? } -> { reply, intent, grounded, sources, retrieval_scores }
POST /api/rag/ingest      multipart file upload (admin)
GET  /api/rag/stats       doc counts per source + last ingest time (admin/CR)
POST /api/rag/reindex     rebuilds category_kb + resolved_ticket (admin)
GET  /api/complaints/{id}/similar   up to 3 anonymized similar resolved cases (staff-only)
```

`POST /api/complaints/chat|voice` responses gained `related_ticket_reference`
(null unless a duplicate/known-issue was linked). No existing field changed
shape.

## Running the eval

```bash
python -m rag.ingest --path data/qa/ --rebuild   # load the seed corpus first
python -m rag.eval.run_eval
```

## Config (`ai-module/env.example`)

```
GEMINI_API_KEY=                          # free, no card — https://aistudio.google.com/apikey
GEMINI_MODEL=gemini-2.5-flash-lite       # verified working live 2026-09-29 — see "Model names move fast" above
GEMINI_EMBEDDING_MODEL=gemini-embedding-001
MISTRAL_API_KEY=                         # secondary, only used if GEMINI_API_KEY is unset
MISTRAL_MODEL=mistral-small-latest
RAG_TOP_K=5
RAG_MIN_SIMILARITY=0.05                  # calibrated for the hashing fallback — raise a lot for real embeddings
RAG_INDEX_RESOLVED_TICKETS=true          # on because the PII scrub tests pass
```

## What wasn't fully verified

- The Mistral secondary path — no Mistral key was ever available to test
  against; the Gemini primary and the keyword/hashing fallback are both now
  live-verified (see above).

Everything else previously listed here (XLSX ingestion, the admin frontend
page, the Customer Portal's live voice/chat wiring) has since been
live-tested — see "XLSX ingestion is now live-tested" and "Feature C is now
live in the Customer Portal" below.

## XLSX ingestion is now live-tested

`data/qa/sample_import.xlsx` (3 valid rows + 1 deliberately blank-question
row) was ingested via `python -m rag.ingest --path data/qa/ --rebuild` —
the real `openpyxl` reader path, not just the "not installed" skip message.
Confirmed: the directory scan picks up `.xlsx` alongside `.jsonl` in the
same call, the malformed row is skipped without aborting the batch (`[OK]
sample_import.xlsx: ingested=3 skipped=1 duplicates=0`), and a question from
the sheet is retrievable end-to-end through `/api/rag/query` (score 1.0 on
an exact match). `openpyxl` itself is commented into `requirements.txt` as
an optional dependency, matching the existing STT/TTS pattern — install it
only if you need `.xlsx` ingestion.

## Feature C is now live in the Customer Portal

Previously, grounded Q&A was only reachable through the admin test-query
box — every message typed or spoken into the actual customer-facing portal
was treated as a complaint, regardless of what it said. `CustomerPortal.tsx`
now calls `POST /api/rag/query` to classify intent *before* deciding what
to do with a message:

- `complaint_intake` → unchanged: opens the existing review-before-submit
  draft panel (chat) or confirm-and-file loop (voice), same deterministic
  ticket-creation path as before.
- `information_question` / `smalltalk` → answered directly with the RAG
  reply, no draft, no ticket. In a voice call, VEMA speaks the answer and
  keeps listening (`continue`s the call loop) rather than asking "would you
  like to report anything else", since nothing was filed.

Routing fails open: if `/api/rag/query` errors (network, rate limit), the
message falls through to the complaint flow exactly as before this change,
so a customer's message is never silently dropped. A new `routing` state
drives a "Thinking…" indicator (chat bubble / call status bar) while the
classification call is in flight.

## A migration gotcha this pass re-triggered

`008_widen_rag_embedding_dimension.sql` first failed on startup with
`syntax error at or near "the"` — a literal `;` inside a `--` comment line
("...text-embedding-004 is natively 768-dim; the local scikit-learn...")
tripped the naive `sql.split(";")` splitter (`database.py`), sending
"the local scikit-learn... DELETE FROM rag_documents" as one garbled
statement to Postgres. This is the exact gotcha `CLAUDE.md` already
documents — re-triggered here despite knowing about it going in. Fixed by
rewording the comment (em dash instead of semicolon) and confirmed the
migration hadn't partially applied before the fix (column was still
`vector(512)`, all rows intact) before re-running it clean.

## A second, more serious migration-008 bug: it wiped the corpus on every restart, not just once

`database.run_schema()` re-applies every numbered migration file on *every*
startup (by design — see `CLAUDE.md`'s "Migrations" section), so every
migration must be safe to re-run indefinitely. Migration 008's original
body was:

```sql
DELETE FROM rag_documents;
ALTER TABLE rag_documents ALTER COLUMN embedding TYPE vector(768);
```

The `ALTER` is genuinely idempotent (a no-op against an already-`vector(768)`
column), but the `DELETE` had no guard at all — it unconditionally erased
the entire table on *every single backend restart*, forever, not just once
during the 512→768 widen it was written for. This was caught live, by
accident: a routine restart (to pick up an unrelated code fix) silently
wiped an already-ingested 38-document corpus (23 Q&A + 8 category KB + 7
resolved tickets) down to zero, with no error, no warning — the next
`/api/rag/query` call just stopped returning grounded answers, and only
checking `rag_documents` row counts directly surfaced that anything had
gone wrong.

Fixed by guarding the `DELETE` on the column's *current* dimension, so it
only fires the first time this runs against a pre-768-dim column:

```sql
DELETE FROM rag_documents
WHERE (
  SELECT atttypmod FROM pg_attribute
  WHERE attrelid = 'rag_documents'::regclass AND attname = 'embedding'
) IS DISTINCT FROM 768;
ALTER TABLE rag_documents ALTER COLUMN embedding TYPE vector(768);
```

(pgvector stores a `vector(n)` column's dimension directly in `atttypmod` —
confirmed `768`, not an offset value, by querying the live DB.) No `DO`
block was used to express this, specifically *because* a `DO $$ ... $$`
block's internal statements are separated by semicolons too, and the naive
splitter would shred it — the one-statement `WHERE`-subquery form avoids
that entirely. (First draft of this very fix wrote a code comment that said
literally "splits each file naively on literal `;`" — the semicolon *inside
the backticks* was still a real semicolon character in the file, and broke
the migration a second time before it ever ran. Re-triggered the gotcha
while writing prose about the gotcha.)

Verified: restarted the backend twice in a row post-fix; `rag_documents`
row counts (`resolved_ticket: 9, qa: 3` at the time) were identical before
and after both restarts, and `python -m pytest tests/ -q` still passes
(49/49).
