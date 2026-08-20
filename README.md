# Munin

Standalone, local-first long-term memory layer for AI agents.

Munin stores durable memory so different LLMs and agents can share context across model switches, application restarts, and new sessions.

## Current status

**M0 — Durable Memory Foundation** ✅  
**M1 — Semantic Retrieval** ✅  
**M2 — Memory Admission** ✅  
**M3 — Deduplication & Reinforcement** ✅

| Concept | Meaning |
|---------|---------|
| **Event** | Raw evidence (something that happened) |
| **Candidate** | Proposed durable fact extracted from an event |
| **Admission** | STORE / IGNORE decision with scores + reason codes |
| **Deduplication** | NEW / DUPLICATE / REINFORCES vs existing memories |
| **Memory** | Durable knowledge (created only on STORE + NEW) |

Not every message becomes memory. M2 decides what is worth keeping. M3 decides whether we already know it.

## Architecture

```text
Event
  ↓
AdmissionProvider (candidate extraction)
  ↓
Policy (score + threshold + privacy)
  ↓
Audit (memory_admissions)          ← decision remains STORE/IGNORE
  ↓
DeduplicationService               ← only for STORE-worthy candidates
  ↓
semantic shortlist (M1 embeddings)
  ↓
RelationshipProvider
  ↓
NEW         → MemoryService → Memory + Embedding
DUPLICATE   → audit only (no new memory)
REINFORCES  → reinforcement provenance (no new memory)
```

## M3 — Deduplication & Reinforcement

### Why M3 exists

Without deduplication, paraphrases accumulate as separate memories:

```text
User is building RagParser.
RagParser is the document parser I'm working on.
```

Both are the same underlying fact. M3 stops redundant storage while preserving provenance when a fact is reconfirmed.

### Embeddings only shortlist

Embedding similarity retrieves *potential* matches. It does **not** decide semantic equivalence.

```text
"I prefer Python."
"I do not prefer Python."
```

These may be similar in vector space. M3 therefore:

```text
candidate → embed → top-k shortlist → relationship classification → NEW / DUPLICATE / REINFORCES
```

Do not merge on cosine threshold alone.

### Relationship types

| Type | Meaning |
|------|---------|
| **NEW** | Genuinely new durable information |
| **DUPLICATE** | Same proposition (exact, normalized, or paraphrase) |
| **REINFORCES** | Independently confirms an existing memory without adding meaningful new information |

### Conservative policy

When the relationship provider is unavailable, returns invalid output, or confidence is below `DEDUP_RELATIONSHIP_MIN_CONFIDENCE`:

```text
default to NEW
```

False negatives create redundant memories. **False positives destroy information.** Munin prefers redundancy over silent merges.

### Exact vs semantic duplicates

1. **Exact / normalized** — trim, collapse whitespace, case-fold. Cheap path; no provider call.
2. **Semantic shortlist** — reuse M1 search (`DEDUP_CANDIDATE_LIMIT`, `DEDUP_MIN_SIMILARITY`).
3. **Relationship classification** — deterministic or OpenAI-compatible provider.

### Reinforcement provenance

REINFORCES does **not** overwrite `source_event_id` on the canonical memory.

Additional evidence is stored in `memory_reinforcements` (event, admission, confidence, timestamp).

Dedup decisions are audited in `memory_deduplication_decisions`.

### Admission vs dedup

A candidate can be:

```text
admission decision = STORE   (worth remembering)
dedup outcome      = DUPLICATE / REINFORCES
```

M2 audit stays truthful: STORE means store-*worthy*, not “a new row was inserted.”

### Scope isolation

Deduplication never merges across:

- different **namespaces**
- different **user_id** values (when user scoping applies)

### Providers

| Provider | Purpose |
|----------|---------|
| `deterministic` | Rule-based, offline, default for tests/dev |
| `openai_compatible` | Local OpenAI-compatible chat endpoint |

```bash
DEDUP_PROVIDER=deterministic

# or local LLM:
DEDUP_PROVIDER=openai_compatible
DEDUP_BASE_URL=http://localhost:8080/v1
DEDUP_MODEL=local-model-name
DEDUP_API_KEY=
```

### Inspect dedup decisions

```bash
curl http://127.0.0.1:8000/api/v1/events/<event_id>/deduplication
```

Admit responses include a `deduplication` object on STORE-worthy results.

### Regression evaluation

```bash
python -m app.deduplication.evaluate
```

Primary metric: **false_merge_count** (predicting DUPLICATE/REINFORCES when the truth is NEW).

### M3 limitations (deferred to M4+)

M3 does **not** yet understand:

- contradictions (`CONTRADICTS`)
- updates / superseding
- temporal truth / validity windows
- memory decay or consolidation

Opposite polarity (prefer vs do not prefer) is preserved as **NEW**.

---

## M2 — Memory Admission

### Why admission exists

Chat is noisy. Eating a burger is not durable knowledge. Building RagParser is.

### STORE vs IGNORE

Munin computes an experimental `admission_score` from provider dimensions:

```text
admission_score =
    future_utility * 0.30
  + stability      * 0.15
  + specificity    * 0.15
  + explicitness   * 0.15
  + importance     * 0.20
  - triviality     * 0.25
```

Default policy (configurable, experimental):

- `admission_score >= 0.65` → STORE (if confidence OK and privacy OK)
- `confidence < 0.60` → IGNORE (`TOO_UNCERTAIN`)
- secret-like content → IGNORE (`SECRET_LIKE_DATA`), candidate text redacted

### Privacy filtering

Deterministic patterns block API keys, tokens, passwords, JWTs, private keys, etc.  
Secrets are not written into memories, admission candidate text, or default logs.

### Admit an event

```bash
# 1) store event
curl -X POST http://127.0.0.1:8000/api/v1/events ^
  -H "Content-Type: application/json" ^
  -d "{\"namespace\":\"personal\",\"role\":\"user\",\"content\":\"I'm building RagParser.\"}"

# 2) admit
curl -X POST http://127.0.0.1:8000/api/v1/events/<event_id>/admit

# 3) inspect admission + dedup
curl http://127.0.0.1:8000/api/v1/events/<event_id>/admissions
curl http://127.0.0.1:8000/api/v1/events/<event_id>/deduplication
```

Debug without persistence:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/admission/analyze ^
  -H "Content-Type: application/json" ^
  -d "{\"role\":\"user\",\"content\":\"I ate a burger today.\"}"
```

Re-admitting the same event returns previous results (`idempotent_replay: true`) and does not create duplicate memories, dedup audits, or reinforcements.

### Regression evaluation

```bash
python -m app.admission.evaluate
```

## M1 — Semantic Retrieval

Embeddings enable retrieval by meaning. Default model: `sentence-transformers/all-MiniLM-L6-v2` (CPU).  
Vectors live in `memory_embeddings` as float32 BLOBs. Similarity thresholds are model-dependent.

```bash
python -m app.cli embed-memories
```

## Requirements

- Python 3.12+
- pip

## Install

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
copy .env.example .env
```

## Database migrations

```bash
alembic upgrade head
```

## Run the server

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

## Run tests

```bash
pytest
python -m app.admission.evaluate
python -m app.deduplication.evaluate
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/munin.db` | DB URL |
| `EMBEDDING_PROVIDER` | `sentence_transformers` | Embedding backend |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `EMBEDDING_DEVICE` | `cpu` | Device |
| `ADMISSION_PROVIDER` | `deterministic` | Admission backend |
| `ADMISSION_STORE_THRESHOLD` | `0.65` | Experimental STORE threshold |
| `ADMISSION_MIN_CONFIDENCE` | `0.60` | Minimum confidence to store |
| `ADMISSION_BASE_URL` | _(empty)_ | OpenAI-compatible base URL |
| `ADMISSION_MODEL` | _(empty)_ | Model name for compatible provider |
| `ADMISSION_API_KEY` | _(empty)_ | Optional API key |
| `DEDUP_PROVIDER` | `deterministic` | Relationship classifier backend |
| `DEDUP_CANDIDATE_LIMIT` | `5` | Semantic shortlist depth |
| `DEDUP_MIN_SIMILARITY` | `0.55` | Minimum cosine for shortlist |
| `DEDUP_RELATIONSHIP_MIN_CONFIDENCE` | `0.70` | Min confidence to accept DUPLICATE/REINFORCES |
| `DEDUP_BASE_URL` | _(empty)_ | OpenAI-compatible base URL for dedup |
| `DEDUP_MODEL` | _(empty)_ | Model name for dedup provider |
| `DEDUP_API_KEY` | _(empty)_ | Optional API key |

## API surface

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness |
| `POST` | `/api/v1/events` | Create event |
| `GET` | `/api/v1/events` | List events |
| `GET` | `/api/v1/events/{id}` | Get event |
| `DELETE` | `/api/v1/events/{id}` | Delete event |
| `POST` | `/api/v1/events/{id}/admit` | Admit event → dedup → memories |
| `GET` | `/api/v1/events/{id}/admissions` | Inspect admission audits |
| `GET` | `/api/v1/events/{id}/deduplication` | Inspect dedup decisions |
| `POST` | `/api/v1/admission/analyze` | Dry-run analysis |
| `POST` | `/api/v1/memories` | Create memory (+ embed) |
| `POST` | `/api/v1/memories/search` | Semantic search |
| `GET/PATCH/DELETE` | `/api/v1/memories...` | Memory CRUD |

## Roadmap

| Milestone | Focus | Status |
|-----------|--------|--------|
| **M0** | Durable Memory Foundation | ✅ |
| **M1** | Semantic Retrieval | ✅ |
| **M2** | Memory Admission | ✅ |
| **M3** | Deduplication & Reinforcement | ✅ |
| **M4** | Contradiction + Temporal Memory | future |
| **M5** | Context Assembly | future |
| **M6** | Decay + Consolidation | future |
| **M7** | Agent Integrations + Graph UI | future |
