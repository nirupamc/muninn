# Munin

Standalone, local-first long-term memory layer for AI agents.

Munin stores durable memory so different LLMs and agents can share context across model switches, application restarts, and new sessions.

## Thesis

Memory should belong to the agent system, not the LLM. Munin keeps durable,
model-independent state behind a local-first API, then assembles relevant memory as
explicitly untrusted data for any agent or model.

## Features

- Durable, namespace- and user-scoped memory with source provenance
- Real sentence-transformer semantic retrieval, including cached offline operation
- Admission, privacy filtering, deduplication, and reinforcement provenance
- Temporal truth through `UPDATES`, `SUPERSEDES`, and unresolved `CONTRADICTS`
- Backend-authoritative context ranking, explainability traces, and token budgeting
- Non-mutating decay, explicit consolidation, and relational source provenance
- Cross-agent continuity through REST, synchronous Python SDK, and CLI
- Operations UI with Overview, Explorer, canonical Inspector, Graph, Context Preview,
  Timeline, and Conflict Center

## Frontend

The React/Vite UI is an observability and debugging console, not a second reasoning
engine. It visualizes backend records without reimplementing admission, ranking,
temporal, decay, or consolidation semantics.

| Route | Screen |
|-------|--------|
| `/overview` | Health, lifecycle inventory, recent activity, scopes, provenance |
| `/memories` | Searchable/filterable memory Explorer and canonical Inspector |
| `/graph` | Real temporal and consolidation relationship network |
| `/context` | Exact M5 context, selected memories, trace, and graph overlay |
| `/timeline` | Backend-linked temporal chains and validity history |
| `/conflicts` | Read-only real `CONTRADICTS` comparisons |
| `/projects`, `/agents`, `/status` | Scope, provenance, and service diagnostics |

## Quick start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
npm install
npm run dev
```

Open `http://127.0.0.1:5173`.

## Portfolio demo

With the backend running, seed the repeatable dataset through the normal agent API:

```powershell
python scripts/seed_demo.py
```

The script uses the dedicated `demo:munin` namespace, stable idempotency keys, real
event → admission → dedup → temporal processing, idempotent consolidation, and
cross-agent context retrieval. It prints actual counts and verification outcomes.

Recommended walkthrough:

1. Select `demo:munin` in the sidebar and inspect lifecycle counts on Overview.
2. Search `PostgreSQL` in Explorer and open its temporal/source provenance.
3. Inspect real supersession, contradiction, and consolidation edges in Graph.
4. Assemble `Continue working on Munin.` in Context Preview, then use View in Graph
   and Why Selected.
5. Inspect the replacement chain in Timeline and unresolved pair in Conflict Center.

Suggested capture set: Overview, Memory Graph, Context Preview, Timeline, and Conflict
Center. Screenshots are intentionally not committed by the seed script.

## Offline embeddings

Download the configured model once during setup. Cached normal runs are local-first.
To require strict network-independent loading:

```powershell
$env:EMBEDDING_LOCAL_FILES_ONLY='true'
$env:HF_HUB_OFFLINE='1'
$env:TRANSFORMERS_OFFLINE='1'
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Munin fails clearly if strict local mode is enabled and the real model is unavailable;
it never silently substitutes fake embeddings.

## Security and identity scopes

Memory context is data, not trusted instruction or a privileged system prompt.
Admission rejects or redacts supported secret-like inputs before durable storage.

| Field | Meaning |
|-------|---------|
| `namespace` | Project or memory scope |
| `user_id` | Ownership/access isolation scope |
| `agent_id` | Writer provenance by default, not access control |
| `session_id` | Working-session provenance; not durable-memory isolation |

## Known limitations

- Temporal and conflict screens load per-memory history with bounded concurrency because
  no global temporal-read endpoint exists.
- The Graph renders at most the selected node limit and labels truncation explicitly.
- No clean reinforcement relationship read endpoint exists, so Graph does not fabricate
  reinforcement edges.
- M5 does not expose skipped candidate records or structured conflict pairs.
- `react-force-graph` keeps the lazy Graph route chunk above Vite's 500 kB advisory;
  other large screens are route-split and the warning is non-blocking.
- The deterministic M4 evaluation retains one known missed-supersede case while
  `false_supersede_count` and `false_contradiction_count` remain zero.
- MCP is intentionally not implemented in M7B.

## Current status

**M0 — Durable Memory Foundation** ✅  
**M1 — Semantic Retrieval** ✅  
**M2 — Memory Admission** ✅  
**M3 — Deduplication & Reinforcement** ✅  
**M4 — Contradiction + Temporal Memory** ✅  
**M5 — Context Assembly** ✅  
**M6 — Decay + Consolidation** ✅  
**M7A — Agent Integration Layer** ✅
**M7B — Memory Operations Frontend** ✅

| Concept | Meaning |
|---------|---------|
| **Event** | Raw evidence (something that happened) |
| **Candidate** | Proposed durable fact extracted from an event |
| **Admission** | STORE / IGNORE decision with scores + reason codes |
| **Deduplication** | NEW / DUPLICATE / REINFORCES vs existing memories |
| **Temporal** | NEW / UPDATES / CONTRADICTS / SUPERSEDES for M3-NEW candidates |
| **Memory** | Durable knowledge with lifecycle (`active`, `superseded`, …) |

Not every message becomes memory. M2 decides what is worth keeping. M3 decides whether we already know it. M4 decides whether new information changes, conflicts with, or replaces prior truth.

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
NEW         → TemporalService (M4) → lifecycle + audit
DUPLICATE   → audit only (no new memory)
REINFORCES  → reinforcement provenance (no new memory)
  ↓
TemporalRelationshipProvider (M3 NEW only)
  ↓
NEW         → memory unchanged (additional fact)
UPDATES     → old superseded, new active, validity windows set
CONTRADICTS → both active, conflict audited
SUPERSEDES  → old superseded, new active, explicit replacement
```

## M4 — Contradiction + Temporal Memory

### Why M4 exists

M3 stops duplicate storage but does not model changing truth:

```text
User prefers Python.
User prefers Rust.
User no longer uses SQLite.
I switched from OpenAI to local models.
```

M4 classifies temporal relationships and applies conservative lifecycle transitions **without deleting history**.

### M2 vs M3 vs M4

| Layer | Question |
|-------|----------|
| **M2 Admission** | Is this candidate worth durable memory? |
| **M3 Dedup** | Do we already know essentially the same thing? |
| **M4 Temporal** | Does this new fact update, conflict with, or replace prior truth? |

M2 STORE decisions are never rewritten to IGNORE because of M3/M4.

### Relationship types

| Type | Meaning | Typical outcome |
|------|---------|-----------------|
| **NEW** | Related or unrelated additional information | New memory; old unchanged |
| **UPDATES** | Same subject with changed details | Old → `superseded`; new → `active` |
| **CONTRADICTS** | Conflict without explicit replacement language | Both stay `active`; conflict audited |
| **SUPERSEDES** | Explicit replacement (`now`, `no longer`, `switched`, negated preference) | Old → `superseded` with `valid_until`; new → `active` with `valid_from` |

### Conservative policy

When the temporal provider is unavailable, returns invalid output, or confidence is below `TEMPORAL_RELATIONSHIP_MIN_CONFIDENCE`:

```text
default to NEW
```

**False supersedes destroy current truth** — worse than redundant memories. Munin never auto-supersedes on ambiguous contradiction.

### Memory lifecycle

Memories reuse existing fields:

- `status`: `active`, `superseded`, `invalidated`, `archived`
- `valid_from` / `valid_until`: validity window for historical retrieval

Superseded rows remain in the database. Search defaults to active-only; pass `statuses=["active","superseded"]` to retrieve history explicitly.

### Temporal audit

Decisions are persisted in `memory_temporal_decisions` with provenance links back to the event, admission row, dedup decision, matched memory, and created memory.

### Providers

| Provider | Purpose |
|----------|---------|
| `deterministic` | Phrase-aware rules, default for tests/dev |
| `openai_compatible` | Local OpenAI-compatible chat endpoint |

```bash
TEMPORAL_PROVIDER=deterministic

# or local LLM:
TEMPORAL_PROVIDER=openai_compatible
TEMPORAL_BASE_URL=http://localhost:8080/v1
TEMPORAL_MODEL=local-model-name
TEMPORAL_API_KEY=
```

### Inspect temporal decisions

```bash
curl http://127.0.0.1:8000/api/v1/events/<event_id>/temporal
curl http://127.0.0.1:8000/api/v1/memories/<memory_id>/history
```

Admit responses include a `temporal` object when M3 returns NEW.

Example:

```json
{
  "decision": "STORE",
  "deduplication": { "relationship": "NEW" },
  "temporal": {
    "relationship": "SUPERSEDES",
    "matched_memory_id": "...",
    "created_memory_id": "...",
    "relationship_confidence": 0.94
  }
}
```

### Regression evaluation

```bash
python -m app.temporal.evaluate
```

Primary metric: **false_supersede_count** (predicting SUPERSEDES when the truth is not SUPERSEDES).

### M4.1 — Dedup / Temporal boundary

M3 owns **semantic duplicate and reinforcement** detection:

```text
"Munin uses SQLite."  ≈  "Munin is using SQLite."  → DUPLICATE / REINFORCES
```

M4 owns **changes of state**. Candidates with explicit transition language are preserved as **M3 NEW** (reason code `STATE_CHANGE_REQUIRES_TEMPORAL_ANALYSIS`) so temporal analysis can classify them:

```text
"Munin still uses SQLite."              → M3 REINFORCES (continuity)
"Munin switched from SQLite to PostgreSQL." → M3 NEW → M4 SUPERSEDES / UPDATES
```

Continuity phrases (`still`, `remains`, `continues to`) do **not** trigger the boundary. Change cues (`switched`, `migrated`, `no longer`, `now prefers`, `used to`, `replaced`, …) do.

---

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

Boundary metric (M4.1): **false_duplicate_on_temporal_change_count** — must be `0` on `tests/fixtures/dedup_boundary_cases.json`.

### M4.1 boundary (M3 side)

Change-of-state candidates must not be collapsed as M3 DUPLICATE. See M4.1 section under M4 above.

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

Re-admitting the same event returns previous results (`idempotent_replay: true`) and does not create duplicate memories, dedup audits, temporal audits, or reinforcements.

### Regression evaluation

```bash
python -m app.admission.evaluate
```

## M1 — Semantic Retrieval

Embeddings enable retrieval by meaning. Default model: `sentence-transformers/all-MiniLM-L6-v2` (CPU).  
Vectors live in `memory_embeddings` as float32 BLOBs. Similarity thresholds are model-dependent.

Munin checks the local Hugging Face cache before allowing a first-time model download.
After setup, set `EMBEDDING_LOCAL_FILES_ONLY=true` to require network-independent
runtime loading. Model loading fails clearly when that mode is enabled and the model is absent.

```bash
python -m app.cli embed-memories
```

## Requirements

- Python 3.12+
- pip
- Node.js 20+ and npm (frontend)

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

## Run the frontend

```bash
npm install
npm run dev
```

Vite serves the UI at `http://127.0.0.1:5173` and proxies `/api` to the backend.

## Run tests

```bash
pytest
python -m app.admission.evaluate
python -m app.deduplication.evaluate
python -m app.temporal.evaluate
python -m app.context.evaluate
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/munin.db` | DB URL |
| `EMBEDDING_PROVIDER` | `sentence_transformers` | Embedding backend |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Embedding model |
| `EMBEDDING_DEVICE` | `cpu` | Device |
| `EMBEDDING_LOCAL_FILES_ONLY` | `false` | Require the embedding model to exist locally; no download fallback |
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
| `TEMPORAL_PROVIDER` | `deterministic` | Temporal classifier backend |
| `TEMPORAL_CANDIDATE_LIMIT` | `5` | Semantic shortlist depth for M4 |
| `TEMPORAL_MIN_SIMILARITY` | `0.50` | Minimum cosine for temporal shortlist |
| `TEMPORAL_RELATIONSHIP_MIN_CONFIDENCE` | `0.75` | Min confidence to accept UPDATES/CONTRADICTS/SUPERSEDES |
| `TEMPORAL_BASE_URL` | _(empty)_ | OpenAI-compatible base URL for temporal |
| `TEMPORAL_MODEL` | _(empty)_ | Model name for temporal provider |
| `TEMPORAL_API_KEY` | _(empty)_ | Optional API key |
| `CONTEXT_MAX_CANDIDATES` | `50` | Max embedding candidates retrieved |
| `CONTEXT_DEFAULT_MAX_MEMORIES` | `20` | Max memories returned per request |
| `CONTEXT_WEIGHT_SEMANTIC` | `0.45` | Semantic similarity weight |
| `CONTEXT_WEIGHT_IMPORTANCE` | `0.20` | Importance weight |
| `CONTEXT_WEIGHT_CONFIDENCE` | `0.10` | Confidence weight |
| `CONTEXT_WEIGHT_RECENCY` | `0.10` | Recency weight |
| `CONTEXT_WEIGHT_TYPE_RELEVANCE` | `0.10` | Memory-type relevance weight |
| `CONTEXT_WEIGHT_REINFORCEMENT` | `0.05` | Reinforcement signal weight |
| `CONTEXT_REDUNDANCY_THRESHOLD` | `0.85` | Cosine threshold for diversity suppression |
| `CONTEXT_DEFAULT_TOKEN_BUDGET` | `1500` | Default token budget per request |
| `CONTEXT_MAX_TOKEN_BUDGET` | `20000` | Hard cap on token_budget field |
| `CONTEXT_RECENCY_LAMBDA` | `0.05` | Exponential decay rate for recency (per day) |

## API surface

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness |
| `POST` | `/api/v1/events` | Create event |
| `GET` | `/api/v1/events` | List events |
| `GET` | `/api/v1/events/{id}` | Get event |
| `DELETE` | `/api/v1/events/{id}` | Delete event |
| `POST` | `/api/v1/events/{id}/admit` | Admit event → dedup → temporal → memories |
| `GET` | `/api/v1/events/{id}/admissions` | Inspect admission audits |
| `GET` | `/api/v1/events/{id}/deduplication` | Inspect dedup decisions |
| `GET` | `/api/v1/events/{id}/temporal` | Inspect temporal decisions |
| `POST` | `/api/v1/admission/analyze` | Dry-run analysis |
| `POST` | `/api/v1/memories` | Create memory (+ embed) |
| `POST` | `/api/v1/memories/search` | Semantic search |
| `GET` | `/api/v1/memories/{id}/history` | Temporal history for a memory |
| `GET/PATCH/DELETE` | `/api/v1/memories...` | Memory CRUD |
| `POST` | `/api/v1/context` | Assemble agent context (read-only) |
| `POST` | `/api/v1/agent/remember` | High-level remember (event → M2/M3/M4) |
| `POST` | `/api/v1/agent/context` | High-level agent-ready context retrieval |

---

## M5 — Context Assembly

### What M5 does

M1 semantic search retrieves memories that are *similar* to a query. M5 assembles memories that are *relevant* to an agent's current task — applying temporal filtering, hybrid ranking, contradiction awareness, diversity suppression, and token budgeting to produce LLM-ready context.

```text
POST /api/v1/context
  ↓
embed query (M1 embedding provider, once)
  ↓
retrieve candidates (namespace / user / agent / type / status filtered)
  ↓
temporal validity filter (valid_from / valid_until at as_of)
  ↓
hybrid ranking
  ↓
redundancy suppression
  ↓
token budget selection
  ↓
conflict detection
  ↓
formatted context + explainability trace
```

### Semantic search vs assembled context

| | Semantic search (`POST /memories/search`) | Context assembly (`POST /context`) |
|--|------------------------------------------|-------------------------------------|
| Goal | Find similar memories | Assemble relevant current truth |
| Filtering | Namespace + status | Namespace + status + temporal validity + superseded exclusion |
| Ranking | Cosine similarity only | Hybrid (semantic + importance + confidence + recency + type + reinforcement) |
| Output | Raw search hits + scores | Formatted context text + trace |
| Side effects | None | None (read-only) |

### Request

```json
{
  "query": "Continue helping me build Munin.",
  "namespace": "personal",
  "user_id": "user-1",
  "agent_id": null,
  "token_budget": 1500,
  "max_candidates": 50,
  "max_memories": 20,
  "memory_types": null,
  "include_superseded": false,
  "as_of": null
}
```

`as_of` defaults to the current UTC time when omitted.

### Response

```json
{
  "query": "Continue helping me build Munin.",
  "namespace": "personal",
  "context": "Relevant durable memory:\n\n[Project]\n- User is building Munin.\n\n[Current decisions]\n- Munin uses FastAPI.\n- Current database is PostgreSQL.\n\n[Goals]\n- Munin should preserve context when switching LLMs.\n\n[Preferences]\n- User prefers local-first AI infrastructure.",
  "token_budget": 1500,
  "estimated_tokens": 68,
  "truncated": false,
  "memories_used": [
    {
      "memory_id": "...",
      "memory_type": "project",
      "content": "User is building Munin.",
      "semantic_score": 0.9993,
      "importance": 0.95,
      "confidence": 1.0,
      "recency_score": 0.998,
      "type_relevance": 1.0,
      "reinforcement_score": 0.0,
      "final_score": 0.9397,
      "estimated_tokens": 8,
      "reason_codes": ["HIGH_SEMANTIC_RELEVANCE", "HIGH_IMPORTANCE", "RECENT", "TYPE_RELEVANT"]
    }
  ]
}
```

Raw embeddings are never returned.

### Hybrid ranking formula

```python
final_score = (
    semantic_similarity * 0.45   # dominant signal
  + importance          * 0.20
  + confidence          * 0.10
  + recency             * 0.10
  + type_relevance      * 0.10
  + reinforcement       * 0.05
)
```

Weights are experimental and configurable. Semantic relevance is kept dominant: a high-importance but unrelated memory does not outrank a strongly relevant memory.

**Recency** is computed at query time only (`exp(-λ * age_days)`, λ=0.05 by default). No importance values are changed.

**Type relevance** is a small deterministic bonus. Continuation queries favour `project`, `goal`, `decision`, `procedure`, `fact`, `preference` types over `event`.

**Reinforcement signal** is a bounded boost from M3 reinforcement provenance (`0 reinforcements → 0`, capped at 0.8). Repetition cannot override semantic relevance.

### Current-state filtering

By default only `active` memories are returned.

A memory is temporally valid at `as_of` only if:

```text
(valid_from is null  OR valid_from  <= as_of)
AND
(valid_until is null OR valid_until >= as_of)
```

Pass `include_superseded: true` to include superseded memories in ranking.

### Contradiction representation

M4 may leave two active memories in unresolved contradiction. M5 detects these via temporal audit data and formats them faithfully — it does not resolve the conflict:

```text
[Unresolved conflicts]
- User prefers Python.
- User prefers Rust.
```

### Diversity suppression

Near-duplicate memories are suppressed at selection time (cosine threshold 0.85, configurable). Memories are never deleted or merged — only withheld from the current context window.

### Token budgeting

Selection never exceeds `token_budget`. Memories are counted as complete units; content is not truncated mid-fact. A tiny budget returns a valid empty response rather than raising an error.

Token estimates use `ceil(len(text) / 4)` — a deterministic approximation. A model-specific tokenizer can be substituted by implementing `TokenEstimator`.

### Context is read-only

`POST /api/v1/context` does not mutate any memory field: `content`, `importance`, `confidence`, `status`, `valid_from`, `valid_until`, `last_accessed_at`, or reinforcement counts are all unchanged.

### curl example

```bash
curl -X POST http://127.0.0.1:8000/api/v1/context \
  -H "Content-Type: application/json" \
  -d '{
    "query": "Continue helping me build Munin.",
    "namespace": "personal",
    "user_id": "user-1",
    "token_budget": 1500
  }'
```

### Model-switch continuity demo

With these memories stored by Agent A:

```text
User is building Munin.
Munin is a durable memory layer for AI agents.
M0 through M4.1 are complete.
The current milestone is M5 Context Assembly.
Munin uses FastAPI.
Current persistence is PostgreSQL.
Do not build the frontend yet.
```

Agent B asking `"Continue from where we left off on Munin."` receives:

```text
Relevant durable memory:

[Project]
- User is building Munin.
- Munin is a durable memory layer for AI agents.

[Current decisions]
- Do not build the frontend yet.
- Munin uses FastAPI.
- Current persistence is PostgreSQL.

[Facts]
- The current milestone is M5 Context Assembly.
- M0 through M4.1 are complete.
```

This is sufficient for Agent B to understand what Munin is, which milestones are done, the current task, the current architecture, and the important constraint — without any shared session state.

### Evaluation

```bash
python -m app.context.evaluate
```

Required safety targets:

```text
superseded_leak_count  = 0
namespace_leak_count   = 0
user_leak_count        = 0
budget_violation_count = 0
```

Manual verification:

```bash
python scripts/manual_m5_verify.py
```

### M5 module layout

```text
app/context/
├── __init__.py          — exports ContextService
├── assembler.py         — full assembly pipeline
├── service.py           — orchestration + ContextResponse
├── models.py            — ScoredCandidate, SelectedMemory, ContextConfig, …
├── scoring.py           — recency, type relevance, reinforcement, final_score
├── budget.py            — token selection, context formatting
├── evaluate.py          — evaluation harness (python -m app.context.evaluate)
└── tokenization/
    ├── base.py          — TokenEstimator ABC
    └── simple.py        — ceil(len/4) estimator
```

## M6 — Decay + Consolidation

M6 adds two complementary, conservative mechanisms so memory remains relevant without ever destroying or mutating knowledge:

1. **Decay** — stale memories lose *effective relevance* over time (computed at query time).
2. **Consolidation** — groups of related memories are compressed into a **derived** summary memory, with full provenance.

### Stored importance vs effective importance

Munin keeps two distinct notions of importance:

| Concept | Meaning | Where it lives |
|---------|---------|----------------|
| **Stored importance** | The `importance` column on a memory row. Set at admission (M2) and never changed by decay. | Persisted in the DB |
| **Effective importance** | Stored importance × decay multiplier, computed at query time. Used for ranking only. | Computed on the fly; never written back |

**Stored importance never changes.** Decay is a pure, deterministic function of (`memory_type`, `created_at`, `as_of`). It is recomputed on every query and produces identical results for a fixed `as_of`.

### Decay profiles

`DecayProfile` controls how quickly a memory type ages out of effective relevance:

| Profile | λ (per-day) | Meaning |
|---------|------------|---------|
| **NONE** | `0.0` | Importance never decays (e.g. pinned system memories) |
| **SLOW** | `0.002` | Long-lived knowledge: projects, goals, preferences |
| **NORMAL** | `0.01` | Medium-lived: decisions, procedures, facts |
| **FAST** | `0.05` | Short-lived: events |
| **EPHEMERAL** | `0.20` | Very transient content (e.g. debugging sessions) |

### Profile mapping by memory type

The default profile is looked up per memory type (no DB column is added):

```text
project / goal / preference / relationship → SLOW
decision / procedure / fact / other        → NORMAL
event                                      → FAST
```

A type without an explicit mapping defaults to `NORMAL`.

<!-- M6REST -->
### Decay formula

```
decay_multiplier = exp(-λ · age_days)     (λ = profile decay rate)

effective_importance = clamp(
    stored_importance × decay_multiplier × reinforcement_modifier,
    0, 1
)
```

- `age_days` is the (non-negative) age between `created_at` and `as_of`.
- `reinforcement_modifier` is a small bounded boost (1.0 → at most 1.1) from M3 reinforcement provenance.
- For `DecayProfile.NONE`, the multiplier is always `1.0`.

### as_of-aware decay

All decay calculations accept an explicit `as_of` timestamp. This makes decay **deterministic for historical queries**: the same fixed `as_of` always yields the same profile, multiplier, and effective importance — even after a restart.

### M5 now uses effective importance

M5's hybrid ranking `final_score` now uses **effective importance** (stored importance × decay multiplier) for its importance component. This means old, fast-decaying events rank below stable projects of equal age and stored importance.

### Recency remains query-time only

M5's small recency signal (`exp(-λ·age)`) is **separate** from the decay multiplier. Both act at query time, but decay adjusts the importance component while recency remains its own small factor. Neither ever persists a decay value back to the row.

### Decay never deletes memories

- Decay does **not** mutate stored importance.
- Decay alone does **not** archive, delete, or supersede any memory.
- A memory whose effective importance has decayed is simply ranked lower in context; it is never automatically destroyed.

<!-- M6REST2 -->
### Why consolidation exists

Long-lived agents accumulate many narrow, related memories. Consolidation compresses a group of related memories into **one derived summary** so context stays concise without discarding the underlying evidence.

### Consolidated memory vs source memories

- A **consolidated memory** is a *new* `memories` row produced by a provider from a group of source memories.
- It is marked by `metadata_.is_consolidated = true`.
- **Source memories are never deleted or superseded.** A consolidated summary is evidence about many sources, not a replacement for them.

### Consolidation is NOT superseding

M4 `supersedes` replaces a truth with a newer truth. Consolidation **never** changes a source memory's `status`. A consolidated memory has status `active` alongside its sources, which remain active and queryable.

### Relational provenance

Every consolidation creates audit rows in two tables:

- `memory_consolidations` — one row per operation: derived memory id, namespace, user, provider, confidence, reason.
- `memory_consolidation_sources` — one row per source memory, linking the audit record to each source memory id.

`GET /api/v1/memories/{id}/consolidation` returns provenance for a derived memory.
`GET /api/v1/memories/{id}/consolidated-from` lists every consolidation that used a memory as a source.

### Providers

| Provider | Purpose |
|----------|---------|
| `deterministic` | Rule-based, offline. Default for tests / dev. |
| `openai_compatible` | Any OpenAI-style chat completions endpoint (OpenAI or local: Ollama, LM Studio, vLLM). |

```bash
CONSOLIDATION_PROVIDER=deterministic

# or local LLM:
CONSOLIDATION_PROVIDER=openai_compatible
CONSOLIDATION_BASE_URL=http://localhost:8080/v1
CONSOLIDATION_MODEL=local-model-name
CONSOLIDATION_API_KEY=
```

The provider abstraction enforces **safety in all implementations**: only summarise facts already in the sources, preserve negation/uncertainty/entity names, never infer new facts, and refuse (return None) when contradictions are detected.

<!-- M6REST3 -->
### Manual consolidation endpoint

```bash
curl -X POST http://127.0.0.1:8000/api/v1/memories/consolidate \
  -H "Content-Type: application/json" \
  -d '{
    "namespace": "personal",
    "memory_ids": ["<id-1>", "<id-2>", "<id-3>"],
    "dry_run": false
  }'
```

The response returns the new `consolidated_memory_id`, the derived content, and `is_new` (whether this exact source set has already been consolidated).

### Preview endpoint

```bash
curl -X POST http://127.0.0.1:8000/api/v1/memories/consolidate/preview \
  -H "Content-Type: application/json" \
  -d '{ "namespace": "personal", "memory_ids": ["<id-1>", "<id-2>", "<id-3>"] }'
```

`preview` runs the provider and returns the proposed summary **without persisting anything**. It is safe to call repeatedly and creates zero DB rows.

### Contradiction safety

Munin never silently merges contradictory memories. If the provider detects an unresolved contradiction (or confidence is below `CONSOLIDATION_MIN_CONFIDENCE`), consolidation is **refused** with HTTP 422. The default safe behavior is to refuse consolidation rather than collapse conflicting facts.

### Namespace / user isolation

Consolidation is scoped to **one namespace, one user**. `_validate_sources` rejects any memory whose namespace or `user_id` differs from the request — a foreign memory raises HTTP 422. A derived memory inherits the namespace/user of its sources.

### Idempotency

Repeating an identical source set returns the existing derived memory instead of creating a duplicate (`is_new=false`). A second semantic duplicate check compares the proposal embedding against existing consolidated memories in the same namespace (cosine ≥ 0.92, stricter than M5 redundancy suppression).

<!-- M6REST4 -->
### Evaluation commands

```bash
python -m app.deduplication.evaluate   # M3
python -m app.temporal.evaluate        # M4
python -m app.context.evaluate         # M5
python -m app.decay.evaluate           # M6 decay
python -m app.consolidation.evaluate   # M6 consolidation
```

M6 decay safety targets:

```text
no_mutation_count                = 0
historical_determinism_failures  = 0
ranking_regression_count         = 0
```

M6 consolidation safety targets:

```text
unsupported_fact_count        = 0
contradiction_merge_count     = 0
namespace_leak_count          = 0
user_leak_count               = 0
duplicate_consolidation_count = 0
rollback_failure_count        = 0
```

Manual verification:

```bash
python scripts/manual_m6_verify.py
```

### Module layout

```text
app/decay/
├── __init__.py       — exports DecayProfile, decay_lambda, profile_for_type,
│                       compute_decay_multiplier, compute_effective_importance
├── profiles.py        — DecayProfile enum + memory-type mapping
├── calculator.py      — multiplier / effective importance (pure functions)
└── evaluate.py        — evaluation harness

app/consolidation/
├── __init__.py
├── base.py            — ConsolidationProvider ABC
├── factory.py         — provider factory
├── models.py          — request/response + proposal models
├── service.py         — orchestration + atomic persistence
├── evaluate.py        — evaluation harness
└── providers/
    ├── deterministic.py
    └── openai_compatible.py

app/models/consolidation.py             — MemoryConsolidation + Source ORM
app/repositories/consolidation_repository.py
app/api/consolidation.py                — HTTP endpoints
```

### Database migration 006

Migration `alembic/versions/006_memory_consolidation.py` creates two tables:

- `memory_consolidations` — one row per consolidation operation (namespace, user, created_memory_id FK, provider, confidence, reason, created_at).
- `memory_consolidation_sources` — many-to-many source links (consolidation_id FK, source_memory_id FK to `memories`).

Both use `ondelete="CASCADE"`: deleting a source or derived memory removes its orphan links, never the other memories. Downgrade drops the source table first, then the audit table.

Run:

```bash
alembic upgrade head
```

### Status

- **M6** ✅ — Decay + Consolidation implemented, tested, and verified.
- **M7A** ✅ — Agent Integration Layer implemented, tested, and verified.
- **M7B** ✅ — Memory Operations Frontend implemented and release-verified.

## M7A — Agent Integration Layer

M7A is the **agent-facing contract** on top of the existing engine. External agents
interact only through two high-level operations — `remember` and `get_context` — and
never run M2/M3/M4 directly. The `AgentService` is a thin orchestration layer that
delegates context assembly to the existing `ContextService` (it never re-implements
ranking).

### Agent-facing architecture

```text
External Agent (Cursor / Qwen / DeepSeek / …)
   │
   │  MuninClient  (SDK, HTTP only — never touches the DB)
   ▼
POST /api/v1/agent/remember   →  AgentService.remember
POST /api/v1/agent/context    →  AgentService.get_context
   │
   ▼
Event  →  AdmissionService (M2)  →  DeduplicationService (M3)
                                       →  TemporalService (M4)  →  Memory / Reinforcement
                                   ContextService (M5) for get_context
```

**Scope semantics**

| Field | Role | Used for access? |
|-------|------|------------------|
| `namespace` | Project / access scope (e.g. `project:munin`) | **Yes** — always scopes storage + retrieval |
| `user_id` | Owner / access scope | **Yes** — scopes when provided |
| `agent_id` | Provenance only | **No** — does NOT isolate project memory |
| `session_id` | Provenance only (conversation/session) | No |
| `idempotency_key` | Client-supplied dedupe key for safe retries | No (used for replay) |

`agent_id` is **provenance**, not scope. Memories written by agent `qwen` are visible to
agent `deepseek` as long as they share the same `namespace` + `user_id`. Explicit
`agent_id` filtering remains available in low-level search for callers that want it, but
the default project memory is shared across agents.

### Remember flow

```text
client.remember(content, …)
   → AgentService.remember  (metadata.explicit_remember = true)
   → Event created (agent_id / session_id / idempotency_key stored as provenance)
   → AdmissionService.admit_event
        M2: extract candidate, privacy check, STORE/IGNORE
        M3: DUPLICATE / REINFORCES / NEW
        M4: NEW → SUPERSEDES / UPDATES / CONTRADICTS
   → compact AgentRememberResponse:
        decision, memory_id, dedup_relationship, temporal_relationship,
        idempotent_replay
```

**Explicit remember intent.** Every `remember()` call sets `explicit_remember=true`.
This boosts explicitness/future-utility for substantive statements so they STORE, while
trivial chatter (`"hello"`) is still ignored and secret-like content (`"My API key is
sk-…"`) is still ignored and redacted (`SECRET_LIKE_DATA` → `[REDACTED]`). Privacy
thresholds are never lowered for M7A.

**Reinforcement vs duplicate (M7A boundary).** Exact normalized duplicate candidates
take a cheap DUPLICATE path and create no new memory. When the *original event* contains
explicit confirmation language (`yes`, `still`, `remains`, `continues`, `confirmed`,
`correct`, `exactly`, `as always`) **and** the canonical candidate is an otherwise-exact
match, the engine escalates to the relationship provider (using the original event
wording, which still carries the cue) and may produce **REINFORCES** — a reinforcement
provenance row, no second canonical memory. State-change language (`switched`, `migrated`,
`no longer`, …) is preserved as M3 NEW so M4 resolves the lifecycle. `again` is treated as
a plain duplicate, not reinforcement.

### Context flow

```text
client.get_context(query, …)
   → AgentService.get_context → ContextService.assemble
   → semantic retrieval (namespace + user_id scoped; agent_id optional filter)
   → temporal validity + hybrid ranking + token budget
   → AgentContextResponse.text  (LLM-ready context)
```

The assembled `text` is **data, not a privileged system instruction**. Integrations must
present it as untrusted context — it must never be injected as control/instruction text.

### Idempotency

If the same `idempotency_key` is sent twice within the same `namespace`/`user_id`/
`agent_id` scope, the second call replays the original admission outcome and returns
`idempotent_replay=true` — **no second event, no duplicate memory, no duplicate audit
rows**. This makes transport retries safe (see SDK safe-retry policy below).

### SDK usage

```python
from app.sdk import MuninClient

client = MuninClient(
    base_url="http://127.0.0.1:8000",
    namespace="project:munin",
    user_id="user-1",
    agent_id="cursor",
    timeout=(5.0, 30.0),   # (connect, read) seconds
    max_retries=2,
)

client.health()                                  # connectivity check
ctx = client.get_context("Continue the Munin project.")   # AgentContext
result = client.remember(
    "Current milestone is M7A Agent Integration.",
    session_id="session-123",
    idempotency_key="ik-001",
)
if result.remembered:
    print(result.memory_id, result.dedup_relationship)
```

The SDK talks to the HTTP API only — it never opens the database. Structured errors
(`MuninConnectionError`, `MuninTimeoutError`, `MuninValidationError`, `MuninServerError`,
`MuninHTTPError`) are raised instead of leaking raw `httpx` exceptions.

### Error model & timeouts / retries

- **Timeouts:** per-request `(connect, read)` via `httpx.Timeout`; default `(5.0, 30.0)`.
- **Safe retries:** only *idempotent* requests are retried — `GET`/`HEAD`/`OPTIONS` and
  writes that carry an `idempotency_key`. Non-idempotent writes are never retried.
  Retries apply only to `502/503/504`. All other statuses fail fast with a structured
  `MuninError` subclass.
- **Validation:** `400/422` → `MuninValidationError`; `>=500` → `MuninServerError`.

### CLI

```bash
munin-agent health   --namespace project:munin --user user-1 --agent cursor
munin-agent context  --namespace project:munin --user user-1 --agent cursor `
                     --query "Continue where we left off"
munin-agent remember --namespace project:munin --user user-1 --agent cursor `
                     --content "M7A integration verified" --session session-123
```

`munin` and `munin-agent` are aliases for the same CLI.

### A → B → C continuity demo

Because memory is project-scoped (not session-scoped), three different agents share
durable context without any shared chat history:

```text
Agent A (Cursor)   remembers: M0–M6 complete; M7A is current; frontend must wait.
Agent B (Qwen)     new session → get_context → sees all three facts.
                   remembers: "M7A continuity verification passed."
Agent C (DeepSeek) new session → get_context → sees the updated state.
```

### Evaluations

```bash
python -m app.agent.evaluate        # 16 cases, all safety metrics must be 0
python -m app.admission.evaluate
python -m app.deduplication.evaluate
python -m app.temporal.evaluate
python -m app.context.evaluate
python -m app.decay.evaluate
python -m app.consolidation.evaluate
python scripts/manual_m7a_verify.py  # A–J + A→B→C + restart checks
```

M7A safety targets (must all be `0`):

```text
namespace_leak_count       = 0
user_leak_count            = 0
duplicate_event_count      = 0
duplicate_memory_count     = 0
idempotency_failure_count  = 0
```

### MCP status

**Deferred.** No Model Context Protocol server is implemented in M7A. The HTTP API
(`/api/v1/agent/remember`, `/api/v1/agent/context`) already provides a complete,
provider-agnostic agent integration surface; adding an MCP server is a separate,
optional concern that does not affect M7A's definition of done. M7A was not expanded to
include MCP.

## Roadmap

| Milestone | Focus | Status |
|-----------|--------|--------|
| **M0** | Durable Memory Foundation | ✅ |
| **M1** | Semantic Retrieval | ✅ |
| **M2** | Memory Admission | ✅ |
| **M3** | Deduplication & Reinforcement | ✅ |
| **M4** | Contradiction + Temporal Memory | ✅ |
| **M5** | Context Assembly | ✅ |
| **M6** | Decay + Consolidation | ✅ |
| **M7A** | Agent Integration Layer | ✅ |
| **M7B** | Memory operations frontend | ✅ |
