# Munin

Standalone, local-first long-term memory layer for AI agents.

Munin stores durable memory so different LLMs and agents can share context across model switches, application restarts, and new sessions.

## Current status

**M0 — Durable Memory Foundation** ✅  
**M1 — Semantic Retrieval** ✅  
**M2 — Memory Admission** ✅

| Concept | Meaning |
|---------|---------|
| **Event** | Raw evidence (something that happened) |
| **Candidate** | Proposed durable fact extracted from an event |
| **Admission** | STORE / IGNORE decision with scores + reason codes |
| **Memory** | Durable knowledge (only created on STORE) |

Not every message becomes memory. M2 decides what is worth keeping.

## Architecture

```text
Event
  ↓
AdmissionProvider (candidate extraction)
  ↓
Policy (score + threshold + privacy)
  ↓
Audit (memory_admissions)
  ↓
MemoryService (M1) → Memory + Embedding   [only on STORE]
```

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

**importance** ≠ **admission_score** ≠ **confidence**.

### Privacy filtering

Deterministic patterns block API keys, tokens, passwords, JWTs, private keys, etc.  
Secrets are not written into memories, admission candidate text, or default logs.

### Providers

| Provider | Purpose |
|----------|---------|
| `deterministic` | Rule-based, offline, default for tests/dev |
| `openai_compatible` | Local OpenAI-compatible chat endpoint (llama.cpp, LM Studio, Ollama, …) |

```bash
ADMISSION_PROVIDER=deterministic

# or local LLM:
ADMISSION_PROVIDER=openai_compatible
ADMISSION_BASE_URL=http://localhost:8080/v1
ADMISSION_MODEL=local-model-name
ADMISSION_API_KEY=
```

### Admit an event

```bash
# 1) store event
curl -X POST http://127.0.0.1:8000/api/v1/events ^
  -H "Content-Type: application/json" ^
  -d "{\"namespace\":\"personal\",\"role\":\"user\",\"content\":\"I'm building RagParser.\"}"

# 2) admit
curl -X POST http://127.0.0.1:8000/api/v1/events/<event_id>/admit

# 3) inspect
curl http://127.0.0.1:8000/api/v1/events/<event_id>/admissions
```

Debug without persistence:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/admission/analyze ^
  -H "Content-Type: application/json" ^
  -d "{\"role\":\"user\",\"content\":\"I ate a burger today.\"}"
```

Re-admitting the same event returns previous results (`idempotent_replay: true`) and does not create duplicate memories.

### Regression evaluation

```bash
python -m app.admission.evaluate
```

### M2 limitations (deferred)

Duplicates across events, contradictions, superseding, decay, consolidation — **M3+**.

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

## API surface

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness |
| `POST` | `/api/v1/events` | Create event |
| `GET` | `/api/v1/events` | List events |
| `GET` | `/api/v1/events/{id}` | Get event |
| `DELETE` | `/api/v1/events/{id}` | Delete event |
| `POST` | `/api/v1/events/{id}/admit` | Admit event → memories |
| `GET` | `/api/v1/events/{id}/admissions` | Inspect admission audits |
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
| **M3** | Deduplication | future |
| **M4** | Contradiction + Temporal Memory | future |
| **M5** | Context Assembly | future |
| **M6** | Decay + Consolidation | future |
| **M7** | Agent Integrations + Graph UI | future |
