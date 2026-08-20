# Munin

Standalone, local-first long-term memory layer for AI agents.

Munin stores durable memory so different LLMs and agents can share context across model switches, application restarts, and new sessions.

## Current status

**M0 — Durable Memory Foundation** ✅  
**M1 — Semantic Retrieval** ✅

Events and Memories remain distinct:

| Concept | Meaning | Example |
|---------|---------|---------|
| **Event** | Something that happened | `"I am building Munin using FastAPI."` |
| **Memory** | Durable knowledge | `"User is building Munin using FastAPI."` |

Memories are **not** auto-created from events. Both are created explicitly via the API.

## Architecture

```text
HTTP (FastAPI)
   ↓
API routes        /api/v1/...
   ↓
Services          memory + embedding services
   ↓
Repositories      database access
   ↓
SQLAlchemy 2.x → SQLite
   +
EmbeddingProvider (sentence-transformers by default)
```

Key design points:

- Clear separation of API / schemas / services / repositories / models
- Namespace isolation for multi-app / multi-agent tenancy
- Alembic migrations (not `create_all` for production)
- Provider-independent embedding interface
- Structured logging that avoids dumping private memory contents, queries, or raw vectors

## M1 — Semantic Retrieval

Embeddings turn memory text into vectors so Munin can retrieve by **meaning**, not only exact filters.

Keyword/filter search finds rows matching fields such as `namespace` or `memory_type`.  
Semantic search ranks memories by cosine similarity between a query embedding and stored memory embeddings.

### How embeddings are stored

Vectors are stored in a separate `memory_embeddings` table as float32 BLOBs (not inside `memories`).

Each row records:

- `provider`
- `model_name`
- `dimension`
- serialized embedding bytes

A memory has at most one embedding in M1 (`memory_id` unique). Deleting a memory cascades to its embedding.

### Default model

| Setting | Default |
|---------|---------|
| Provider | `sentence_transformers` |
| Model | `sentence-transformers/all-MiniLM-L6-v2` |
| Device | `cpu` |
| Typical dimension | `384` (read from the model, not hard-coded globally) |

### Similarity scores

Search returns cosine similarity in roughly `[0, 1]` for normalized vectors.

**Thresholds are model-dependent.** There is no universal “0.8 means excellent” rule. M1 exposes configurable `min_score` so you can tune per deployment/model.

Search only compares embeddings whose `provider` / `model_name` / `dimension` match the currently configured provider. Incompatible vectors are skipped (not compared silently).

### Lifecycle

| Action | Embedding behavior |
|--------|--------------------|
| `POST /memories` | Memory + embedding created atomically |
| `PATCH` content | Memory updated and re-embedded |
| `PATCH` other fields | Embedding left unchanged |
| `DELETE /memories/{id}` | Embedding removed via FK cascade |

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
```

Copy environment defaults:

```bash
copy .env.example .env   # Windows
# cp .env.example .env   # macOS / Linux
```

The first real embedding call downloads the sentence-transformers model (lazy load).

## Database migrations

```bash
alembic upgrade head
```

Default database path: `data/munin.db`  
Override with `DATABASE_URL`.

## Backfill existing memories

Memories created before M1 (or without embeddings) can be indexed:

```bash
python -m app.cli embed-memories
# or: munin embed-memories
```

The command is idempotent: it only embeds memories missing an embedding row and will not duplicate embeddings or change memory content.

## Run the server

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Health check:

```bash
curl http://127.0.0.1:8000/health
```

## Run tests

```bash
pytest
```

Core tests use a deterministic fake embedding provider (no model download). They never write to `data/munin.db`.

## Example curl requests

### Create a memory

```bash
curl -X POST http://127.0.0.1:8000/api/v1/memories ^
  -H "Content-Type: application/json" ^
  -d "{\"namespace\":\"personal\",\"user_id\":\"user-1\",\"agent_id\":\"cursor\",\"content\":\"User is building Munin.\",\"memory_type\":\"project\",\"importance\":0.95,\"confidence\":1.0,\"metadata\":{\"project\":\"munin\"}}"
```

### Semantic search

```bash
curl -X POST http://127.0.0.1:8000/api/v1/memories/search ^
  -H "Content-Type: application/json" ^
  -d "{\"query\":\"What document parser am I working on?\",\"namespace\":\"personal\",\"limit\":5,\"min_score\":0.3}"
```

### Create an event

```bash
curl -X POST http://127.0.0.1:8000/api/v1/events ^
  -H "Content-Type: application/json" ^
  -d "{\"namespace\":\"cortex-development\",\"user_id\":\"user-1\",\"agent_id\":\"cursor\",\"session_id\":\"session-001\",\"role\":\"user\",\"content\":\"I am building Munin using FastAPI.\",\"metadata\":{\"source\":\"chat\"}}"
```

### List / patch / delete

```bash
curl "http://127.0.0.1:8000/api/v1/memories?namespace=personal"

curl -X PATCH http://127.0.0.1:8000/api/v1/memories/<memory_id> ^
  -H "Content-Type: application/json" ^
  -d "{\"importance\":0.8,\"content\":\"User is building Munin M1.\"}"

curl -X DELETE http://127.0.0.1:8000/api/v1/events/<event_id>
```

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `MUNIN_ENV` | `development` | Environment name |
| `DATABASE_URL` | `sqlite:///./data/munin.db` | SQLAlchemy database URL |
| `API_HOST` | `127.0.0.1` | Bind host (docs / ops) |
| `API_PORT` | `8000` | Bind port (docs / ops) |
| `LOG_LEVEL` | `INFO` | Logging level |
| `EMBEDDING_PROVIDER` | `sentence_transformers` | Embedding backend |
| `EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Model id |
| `EMBEDDING_DEVICE` | `cpu` | Device (`cpu` recommended for portability) |

## API surface

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Liveness |
| `POST` | `/api/v1/events` | Create event |
| `GET` | `/api/v1/events` | List/filter events |
| `GET` | `/api/v1/events/{id}` | Get event |
| `DELETE` | `/api/v1/events/{id}` | Delete event |
| `POST` | `/api/v1/memories` | Create memory (+ embed) |
| `POST` | `/api/v1/memories/search` | Semantic search |
| `GET` | `/api/v1/memories` | List/filter memories |
| `GET` | `/api/v1/memories/{id}` | Get memory |
| `PATCH` | `/api/v1/memories/{id}` | Partial update (+ re-embed if content changes) |
| `DELETE` | `/api/v1/memories/{id}` | Hard delete (+ cascade embedding) |

Search filters: `namespace` (required), optional `user_id`, `agent_id`, `memory_types`, `statuses`, `limit` (default 10, max 50), `min_score` (default 0.0).

## Roadmap

| Milestone | Focus | Status |
|-----------|--------|--------|
| **M0** | Durable Memory Foundation | ✅ |
| **M1** | Semantic Retrieval | ✅ |
| **M2** | Memory Admission | future |
| **M3** | Deduplication | future |
| **M4** | Contradiction + Temporal Memory | future |
| **M5** | Context Assembly | future |
| **M6** | Decay + Consolidation | future |
| **M7** | Agent Integrations + Graph UI | future |

Intentionally deferred: LLM reasoning, automatic memory extraction, vector DB servers (Qdrant/Chroma/pgvector), MCP, auth, frontend, WebSockets.
