# Munin Architecture

**Local-first persistent memory layer for AI agents.**

---

## System Overview

```
Developer Activity
        │
        ├── Git
        ├── Filesystem
        └── Agent Capture Bridge
                ↓
        Project Resolution
                ↓
        Memory Admission (M2)
                ↓
        Dedup + Temporal Reasoning (M3/M4)
                ↓
        Decay + Consolidation (M6)
                ↓
        Hierarchical Representation (M10)
                ↓
        Hybrid Retrieval (M11)
            ├── Dense (semantic/vector)
            ├── Lexical (BM25)
            ├── Graph (temporal/dedup relationships)
            └── RRF Fusion
                ↓
        Context Assembly (M5)
                ↓
             Agent
```

---

## Core Modules

| Module | Location | Purpose |
|--------|----------|---------|
| **Admission** | `app/admission/` | Decides STORE/IGNORE for incoming events |
| **Deduplication** | `app/deduplication/` | Semantic shortlist → relationship classification |
| **Temporal** | `app/temporal/` | Tracks truth over time with validity windows |
| **Decay** | `app/decay/` | Query-time exponential decay by memory type |
| **Consolidation** | `app/consolidation/` | Compresses related memories into derived summaries |
| **Context Assembly** | `app/context/` | Retrieval → ranking → budget → formatting |
| **Representations** | `app/memory/representations/` | Hierarchical L0/L1/L2 representation generation and selection |
| **Retrieval** | `app/retrieval/` | Hybrid retrieval: dense, lexical BM25, graph, RRF fusion |
| **Observations** | `app/observations/` | Structured observation types and normalization (M12) |
| **Capture** | `app/capture/` | Git, filesystem, and agent session capture |
| **Embeddings** | `app/embeddings/` | sentence-transformers with cached offline mode |
| **Projects** | `app/projects/` | Project discovery, registration, and management |
| **Agent** | `app/agent/` | High-level agent service (remember, context) |

---

## Memory Model

### Core Entity: `Memory` (table: `memories`)

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Primary key |
| `namespace` | String | Project-scoped namespace |
| `content` | Text | **L2 — Authoritative full content** |
| `gist` | Text (nullable) | **L0 — One-line gist** |
| `summary` | Text (nullable) | **L1 — Compact summary** |
| `memory_type` | Enum | fact, preference, project, goal, decision, event, relationship, procedure, other |
| `importance` | Float | Stored importance (0.0–1.0) |
| `confidence` | Float | Confidence score (0.0–1.0) |
| `status` | Enum | active, superseded, invalidated, archived |
| `valid_from` / `valid_until` | DateTime | Temporal validity window |
| `metadata` | JSON | Arbitrary metadata |

### Hierarchical Representation (M10)

Each memory has three representation levels:

- **L0 (Gist):** One concise sentence, ≤50 tokens, preserves critical identifiers
- **L1 (Summary):** Compact summary, ≤200 tokens, preserves key clauses
- **L2 (Full):** Authoritative content, always available

**Generation:** Deterministic (no LLM required), runs at memory creation time.
**Selection:** Context assembly chooses L0/L1/L2 based on token budget and importance.
**Invariant:** L0/L1 are *views* of L2, not separate memories.

---

## Data Flow

### Memory Creation

```
Event → AdmissionService.admit_event()
  → AdmissionProvider.analyze_event()
  → PolicyDecision (STORE/IGNORE)
  → DeduplicationService.process_candidate()
    → Relationship classification (NEW/DUPLICATE/REINFORCES)
    → MemoryService.create() ← HERE: representations generated
      → Memory persisted
      → EmbeddingService.embed_memory()
      → RepresentationService.generate_for_memory() ← M10
        → build_gist() + build_summary()
        → memory.gist = ..., memory.summary = ...
  → TemporalService.process_new_candidate()
    → Temporal relationship classification
```

### Observation Pipeline (M12)

```
Raw Agent/Tool Activity
        ↓
ObservationNormalizer
  → classify type (DECISION, TEST_RESULT, ERROR, etc.)
  → extract structured data
  → filter trivial/secret content
  → produce canonical Observation
        ↓
CaptureService (existing)
  → CaptureEvent persisted (fingerprint = idempotency)
  → Admission pipeline
  → Dedup / Temporal logic
  → Durable Memory (if admitted)
```

**Key invariant:** Observation != Memory. Observations flow through existing admission.

---

## Observation Types (M12)

| Type | Description | Memory Value |
|------|-------------|--------------|
| `DECISION` | Explicit architectural/design decision | High |
| `TEST_RESULT` | Test execution result with counts | High |
| `ERROR` | Error/exception occurrence | High |
| `BLOCKER` | Blocking issue | High |
| `VERIFICATION` | Verified outcome (git diff clean, etc.) | High |
| `GIT_COMMIT` | New commit | High |
| `FILE_EDIT` / `CREATE` / `DELETE` | File changes | Medium |
| `COMMAND_RUN` | Shell command executed | Low |
| `AGENT_MESSAGE` / `USER_MESSAGE` | Conversation text | Low |
| `TOOL_CALL` / `TOOL_RESULT` | Raw tool activity | Low |

**Structured data** preserved: test counts, error types, file paths, commands.
**Trivial filtering:** single words, "continue", "okay" → ignored.
**Secret filtering:** API keys, passwords, private keys → rejected.

---

### Context Assembly

```
ContextService.assemble(req)
  → ContextAssembler.assemble()
    1. Hybrid Retrieval (M11):
       → DenseRetriever: embed query → cosine similarity
       → LexicalRetriever: BM25 over content + gist + summary
       → GraphRetriever: traverse temporal/dedup relationships
       → RRF Fusion: combine ranked results
    2. Embed query (for dense component)
    3. Retrieve candidates from embedding store
    4. Blend semantic scores with hybrid RRF scores
    5. Add candidates from lexical/graph that aren't in dense results
    6. Temporal validity filter
    7. Score candidates (semantic + importance + confidence + recency + type + reinforcement)
    8. Sort deterministically
    9. Suppress redundant near-duplicates
    10. SELECT WITHIN BUDGET (M10: hierarchical representation selection)
    11. Detect conflict pairs
    12. Format output
```

### Retrieval Modes (M11)

| Mode | Channels | Use Case |
|------|----------|----------|
| `dense` | Semantic/vector only | Default, backward compatible |
| `lexical` | BM25 only | Exact identifier queries |
| `hybrid` | Dense + Lexical + Graph + RRF | Best overall, opt-in |

**Default:** `dense` (safe, proven). Switch to `hybrid` via `retrieval_mode` parameter.

### Lexical Tokenization (M11)

BM25 tokenization preserves technical identifiers:
- `_load_max_checkpoint` → preserved as whole token
- `M8.3A` → preserved as searchable token
- `app/context/assembler.py` → preserved as path token
- `503` → preserved as error code token
- `AgentSessionService` → split into components + original

---

## Token Budget & Representation Selection

### Selection Logic

| Condition | Selected Level | Reason |
|-----------|---------------|--------|
| Budget comfortable (>3× L2 cost) | L2 | Sufficient budget |
| Tight budget + low importance (<0.7) | L0 | Maximize memory count |
| Tight budget + medium importance (<0.5) | L1 | Balance detail and count |
| No gist available | L2 | Fallback |
| No summary available | L2 | Fallback |

### Token Accounting

Each `SelectedMemory` includes:
- `representation_level`: L0, L1, or L2
- `selection_reason`: Why this level was chosen
- `estimated_tokens`: Token cost of the selected representation

---

## API Endpoints

### Memory Endpoints (`/api/v1/memories`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/memories` | Create memory (auto-generates representations) |
| GET | `/memories` | List memories (includes gist, summary) |
| GET | `/memories/{id}` | Get memory detail (includes gist, summary) |
| PATCH | `/memories/{id}` | Update memory (regenerates representations on content change) |
| DELETE | `/memories/{id}` | Delete memory |
| POST | `/memories/search` | Semantic search |

### Context Endpoint (`/api/v1/context`)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/context` | Assemble context with hierarchical representation selection |

Response includes `representation_level` and `selection_reason` for each memory used.

---

## CLI Commands

| Command | Description |
|---------|-------------|
| `munin memory-representations backfill` | Backfill L0/L1 for existing memories |
| `munin memory-representations backfill --dry-run` | Preview backfill without writing |
| `munin memory-representations backfill --force` | Regenerate even if representations exist |
| `munin embed-memories` | Backfill embeddings for memories |

---

## Database Migrations

Alembic manages schema changes. Migration chain:

```
001_initial → 002 → 003 → 004 → 005 → 006 → bd4354d → a7c1f0d → c8d1a0f (M10)
```

M10 adds `gist` and `summary` columns (nullable Text) to the `memories` table.
M11 adds no new tables — retrieval is implemented in-memory (BM25 index, graph traversal).

---

## Memory Debugger / Observability (M13)

M13 makes Munin's internal decisions inspectable.

### Debug API Endpoints (`/api/v1/debug`)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/debug/memories/{id}` | Complete debug view for one memory |
| GET | `/debug/observations/{id}` | Debug view for one capture event / observation |
| GET | `/debug/timeline` | Bounded recent debug timeline (namespace-filterable) |

### Memory Debug View Sections

| Section | Content |
|---------|--------|
| **Identity** | ID, namespace, type, status, importance, confidence, timestamps |
| **Representations** | L0 gist, L1 summary, L2 full content, token costs per level |
| **Provenance** | Agent host, model, session, observation type, source event |
| **Admission** | Decision, score, reason codes, provider |
| **Dedup / Reinforcement** | Relationship, matched memory, similarity, reinforcement count |
| **Temporal** | Relationships (SUPERSEDES, UPDATES, CONTRADICTS), validity changes |
| **Source Events** | Capture events linked to this memory |
| **Timeline** | Recent activity across all capture events |

### Key Invariants

- **Read-only** — Debugger never mutates memory state (no reinforcement, no last_accessed, no retrieval events)
- **Secret-safe** — API keys, passwords, tokens, private keys are never exposed
- **Graceful degradation** — Historical memories with missing trace data return null/empty sections, not errors
- **Namespace isolation** — Debug APIs respect the same access boundaries as memory APIs

### Frontend Integration

The `MemoryInspector` includes a DEBUG button that opens the `MemoryDebugPanel`, providing:
- Expandable sections for each trace category
- Color-coded representation badges (L0/L1/L2)
- Admission decision badges (STORED/IGNORED)
- Timeline view with recent activity

---

## Testing

- **Backend:** `pytest` with in-memory SQLite
- **M10 tests:** `tests/test_representations.py`, `tests/test_context_hierarchical.py` (61 tests)
- **M11 tests:** `tests/test_hybrid_retrieval.py` (46 tests)
- **M12 tests:** `tests/test_observations.py` (46 tests)
- **M13 tests:** `tests/test_debug.py` (27 tests)
- **M10 coverage:** Representation generation, selection, backfill, backward compat, failure safety
- **M11 coverage:** BM25 tokenization, lexical retrieval, RRF fusion, namespace isolation, temporal truth preservation, benchmark queries, failure safety
- **M12 coverage:** Observation types, classification, trivial/secret filtering, command/test/file/error/decision normalization, provenance, namespace isolation, malformed event safety
- **M13 coverage:** Debug views (identity, representations, provenance, admission, dedup, temporal, source events), timeline, secret sanitization, no-side-effect invariant, namespace isolation, graceful degradation

---

## Frontend V2 (Information Architecture Update)

The frontend exposes all M10-M13 capabilities with a clean information architecture:

### Navigation

| Sector | Path | Purpose |
|--------|------|---------|
| 01 | `/overview` | Core status, projects, recent activity |
| 02 | `/memories` | Memory Explorer with L0/L1/L2 |
| 03 | `/graph` | Memory Network (2D/3D) |
| 04 | `/context` | Context Assembly + Hybrid Retrieval |
| 05 | `/observations` | M12 Observation Timeline |
| 06 | `/timeline` | Temporal Trace |
| 07 | `/conflicts` | Conflict Center |
| 08 | `/agents` | Agent Integrations + System |

### Key UI Features

- **Memory Explorer:** Table with L0 gist badge, type/status tags, importance/confidence
- **Memory Inspector:** Hierarchical representations (L0/L1/L2 badges), provenance, consolidation, DEBUG button
- **Memory Debug Panel:** Full M13 debugger with identity, representations, provenance, admission, dedup, temporal, source events, timeline
- **Context Assembly:** Retrieval mode selector (hybrid/dense/lexical), representation level per memory, token telemetry
- **Observations:** M12 timeline with observation types, outcomes (STORED/IGNORED/TRIVIAL), capture events
- **Temporal Trace:** Summary cards (active/superseded/contradictions/chains), chain visualization
- **Agents:** Integration cards for Codex/Kilo/OpenCode/Cline/Aider with availability status
- **System Status:** Backend health, capture status, adapter health, capability matrix

### Design System

- Black background, orange/cyan/green accents, NERV terminal aesthetic
- Georgia serif for display, Cascadia Mono for data
- CRT scanline effects, phosphor glow
- No gradients, no glassmorphism
- `munin-panel`, `munin-btn`, `munin-input` component primitives

---

## Design Principles

1. **Local-first** — No external API required for core functionality
2. **Deterministic** — Same input produces same output (no randomness)
3. **Failure-safe** — Representation generation never prevents memory storage
4. **Backward compatible** — NULL gist/summary rows work (fallback to L2)
5. **Additive** — M10 extends, never rewrites existing systems
6. **Testable** — All new logic has focused unit tests
