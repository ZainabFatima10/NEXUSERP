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
   (keyword heuristic in dev-mode; Mistral strict-JSON when configured)
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
4. rag/generation.py: Mistral answers ONLY from the retrieved Q&A pairs
   (dev-mode: returns the top match's stored answer verbatim — still
   genuinely grounded, just no LLM synthesis) → echo_guard.strip_echo()
   (Feature A) → honest "I don't know, want to file a complaint?" if
   nothing cleared the relevance bar
        │
        ▼
   bot_reply → (voice path) Kokoro TTS → spoken back

5. Inside create_ticket() (complaint_intake path), RAG assists three points
   without ever writing the ticket itself:
     - rag/category_kb.py's taxonomy-derived documents can few-shot-ground
       Mistral's category call (LLM path only — the dev-mode keyword
       classifier doesn't need this)
     - taxonomy.py's required_fields drive which field to ask for next
     - _find_duplicate_ticket() links a new ticket to an already-open one
       in the same category+area — creation is never blocked
   Severity, routing, and the ticket write itself stay exactly the
   pre-existing deterministic code.
```

## Embedding model — a decision made by testing, not assumed

The plan was a local multilingual `sentence-transformers` model
(`paraphrase-multilingual-MiniLM-L12-v2`). Testing it on this machine:

```
OSError: [WinError 4551] An Application Control policy has blocked this
file. Error loading "...\torch\lib\torch.dll"...
```

Windows Application Control blocks `torch.dll` outright — not a pip or
version problem, a system security policy this session has no business
overriding. `torch`/`sentence-transformers`/`transformers` were installed,
confirmed unusable, and uninstalled again.

Two backends instead, selected the same way every other external-API
dependency in this codebase already is:

| | Condition | What |
|---|---|---|
| **Primary** | `MISTRAL_API_KEY` set | Mistral's embeddings API (`mistral-embed`, 1024-dim). **Coded but not live-tested** — no key in this environment. |
| **Fallback** | unset (this environment's actual state) | scikit-learn `HashingVectorizer` (512-dim, bigrams, L2-normalized). Stateless — no fitted vocabulary to persist, no model download, no torch. **This is the path every test, the eval script, and the live demo actually exercise.** |

`rag_documents.embedding` is `vector(512)` (migration 007) to match the
tested fallback. Switching backends to a different output width means
`ALTER TABLE rag_documents ALTER COLUMN embedding TYPE vector(<dim>)` and a
full re-ingest — the schema doesn't try to support two dimensions in one
column.

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

```
hit@1: 4/12 (33%)
hit@3: 8/12 (67%)
hit@5: 8/12 (67%)
groundedness-consistency (in-domain): 12/12 (100%)
no-answer precision (out-of-domain):  4/5 (80%)
```

Reported as measured, not claimed as good — this is the honest ceiling of a
term-hashing embedding on a 23-document corpus. The 4 misses at k=5 are
genuine lexical-overlap failures (e.g. "settle my bill" shares no word root
with "pay"); the 1 false positive ("recommend a good restaurant nearby")
slipped past the lexical gate on a coincidentally shared common word. A real
semantic embedding model (Mistral's API, or sentence-transformers on a
machine without this environment's DLL block) would be expected to
substantially improve both numbers — this is a property of the embedding
backend, not the retrieval/generation pipeline wrapped around it, which
behaves correctly given its input.

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
RAG_EMBEDDING_MODEL=mistral-embed        # only used if MISTRAL_API_KEY is set
RAG_TOP_K=5
RAG_MIN_SIMILARITY=0.05                  # calibrated for the hashing fallback — raise a lot for real embeddings
RAG_INDEX_RESOLVED_TICKETS=true          # on because the PII scrub tests pass
```

## What wasn't fully verified

- The Mistral-embeddings backend path (`EMBEDDING_BACKEND == "mistral"`) —
  coded, never exercised against a real key in this environment.
- Mistral-driven (vs. keyword-heuristic) intent classification and
  retrieval-assisted category grounding — same reason, no key configured
  here. The keyword fallback path this repo actually runs on is fully
  tested.
- XLSX ingestion's `openpyxl` path — the reader is written and the "not
  installed" skip message is real, but no `.xlsx` sample was ingested live
  in this pass (CSV/JSON/JSONL all were).
- Frontend admin page for `/api/rag/*` — see `FRONTEND.md` for what shipped
  and what's still a stub.
