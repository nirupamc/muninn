# Munin

**Local-first long-term memory for AI agents.**

Munin gives AI agents durable memory that survives model switches, new sessions, and application restarts.

The core idea is simple:

> **Memory should belong to the agent system, not the LLM.**

Instead of letting memory disappear whenever a model changes or a chat resets, Munin stores durable, model-independent memory behind a local API and assembles only the most relevant current context for whichever agent is asking.

---

## Why the name Munin?

In Norse mythology, Odin has two ravens:

- **Huginn** — thought
- **Muninn** — memory

The name fit this project almost perfectly.

Munin is the memory half of that idea: a system that persists what matters, tracks how knowledge changes, and gives different agents access to the same durable context.

The repository is named `muninn`, while the project itself is branded **Munin**.

---

## Why Munin exists

AI agents are good at reasoning inside one session.

They are much worse at remembering across:

- model switches
- application restarts
- different agents
- long-running projects
- changing facts over time
- disconnected conversations

A local coding agent may understand a project perfectly today, then lose most of that context after a restart.

A different model may start from zero.

Munin moves memory outside the model.

```text
Cursor --------┐
Claude Code ---┤
OpenCode ------┤
Local Models --┼────> Munin ────> Persistent Memory
DeepSeek ------┤
Other Agents --┘
```

A memory written by one agent can later be retrieved by another, as long as they share the same memory scope.

---

## What Munin does

Munin is more than a vector database.

It manages the full lifecycle of agent memory.

```text
Raw Event
   ↓
Memory Admission
   ↓
Deduplication / Reinforcement
   ↓
Temporal Reasoning
   ↓
Durable Memory
   ↓
Decay / Consolidation
   ↓
Context Assembly
   ↓
Agent-ready Context
```

### Core capabilities

- Durable local memory
- Namespace- and user-scoped isolation
- Provenance for stored memories
- Semantic retrieval using sentence transformers
- Cached offline embedding support
- Automatic memory admission
- Secret-like data filtering
- Duplicate detection
- Reinforcement tracking
- Temporal truth management
- Contradiction detection
- Memory decay
- Provenance-preserving consolidation
- Token-budgeted context assembly
- Explainable ranking traces
- Cross-agent continuity
- REST API
- Python SDK
- CLI
- Memory Operations frontend
- 2D and 3D memory graph

---

# Memory Lifecycle

Not every message should become permanent memory.

Munin processes new information through several stages before deciding what belongs in long-term storage.

---

## 1. Memory Admission

The first question is:

> **Is this information worth remembering?**

For example:

```text
"hello"
→ IGNORE
```

while:

```text
"I'm building Munin."
→ STORE
```

Admission considers signals such as:

- future usefulness
- stability
- specificity
- explicitness
- importance
- triviality

It also applies privacy rules before durable storage.

Secret-like data such as API keys, tokens, passwords, JWTs, and private keys are rejected or redacted rather than silently stored.

---

## 2. Deduplication

The next question is:

> **Do we already know this?**

Example:

```text
"Munin uses SQLite."

"Munin uses SQLite as its database."
→ DUPLICATE
```

Semantic similarity is used only to retrieve possible matches.

Similarity alone never decides that two memories are equivalent.

This matters because:

```text
"I prefer Python."
"I do not prefer Python."
```

may be close in embedding space while meaning very different things.

Munin therefore uses semantic retrieval as a shortlist, followed by relationship classification.

---

## 3. Reinforcement

Sometimes new information confirms something already known.

Example:

```text
"Munin uses FastAPI."

"Yes, Munin still uses FastAPI."
→ REINFORCES
```

Munin does not create another canonical memory.

Instead, the confirmation is preserved as reinforcement provenance.

The memory remains one fact with multiple pieces of evidence behind it.

---

## 4. Temporal Memory

Facts change.

A useful memory system should not simply overwrite history.

Example:

```text
Munin uses SQLite.
        ↓
   SUPERSEDES
        ↓
Munin uses PostgreSQL.
```

The original SQLite memory remains stored, but becomes historical.

Munin can classify temporal relationships as:

```text
NEW
UPDATES
SUPERSEDES
CONTRADICTS
```

A superseded memory is preserved with its validity window rather than deleted.

---

## Contradictions

Not every conflict has an obvious winner.

Example:

```text
User prefers Python.
User prefers Rust.
```

If Munin cannot confidently determine that one replaced the other, the relationship can remain:

```text
CONTRADICTS
```

Both memories remain available and the unresolved conflict is explicitly recorded.

Munin prefers exposing uncertainty over silently inventing certainty.

---

# Context Assembly

Semantic search answers:

> **Which memories are similar to this query?**

Munin's Context Assembly asks a more useful question:

> **Which memories should the agent actually know right now?**

```text
Agent Query
   ↓
Semantic Retrieval
   ↓
Scope Filtering
   ↓
Temporal Validity
   ↓
Hybrid Ranking
   ↓
Redundancy Suppression
   ↓
Token Budgeting
   ↓
Conflict Awareness
   ↓
LLM-ready Context
```

Several signals contribute to ranking:

```text
semantic relevance
importance
confidence
recency
memory type relevance
reinforcement
```

Semantic relevance remains the dominant signal.

A highly important memory that has nothing to do with the current task should not outrank a strongly relevant memory.

---

## Why Context Assembly matters

Imagine Munin contains:

```text
User is building Munin.
Munin is a long-term memory system.
Current persistence is PostgreSQL.
M7A is complete.
The current task is frontend polish.
User also likes a completely unrelated project.
```

An agent asking:

```text
"Continue working on Munin."
```

does not need every stored memory.

Munin should assemble something closer to:

```text
Relevant durable memory:

[Project]
- User is building Munin.
- Munin is a long-term memory system.

[Current decisions]
- Current persistence is PostgreSQL.
- The current task is frontend polish.

[Progress]
- M7A is complete.
```

That assembled context can then be passed to whichever model or agent is currently working.

---

# Cross-Agent Memory

One of Munin's main goals is continuity between different agents.

For example:

```text
Cursor
  ↓ remembers
"Current milestone is M7A."

Qwen
  ↓ starts a new session
  ↓ retrieves the context

DeepSeek
  ↓ starts later
  ↓ sees the updated project state
```

No shared chat history is required.

The persistent memory belongs to Munin, not to Cursor, Qwen, DeepSeek, or any other individual model.

---

## Scope Semantics

Munin separates access scope from provenance.

| Field | Purpose |
|---|---|
| `namespace` | Project or memory scope |
| `user_id` | Ownership / access scope |
| `agent_id` | Writer provenance |
| `session_id` | Session provenance |

Example namespaces:

```text
project:munin
project:ragparser
personal
demo:munin
```

`agent_id` does **not** automatically isolate memory.

A memory written by one agent can be retrieved by another when they share the same namespace and user scope.

---

# Decay

Not every memory should remain equally relevant forever.

Munin uses query-time decay to reduce the effective relevance of stale information.

The original stored importance is never mutated.

Conceptually:

```text
effective importance
=
stored importance
×
decay multiplier
```

Different types of memory age differently.

Long-lived things such as:

```text
projects
goals
preferences
```

decay slowly.

Short-lived events decay faster.

Decay never automatically deletes a memory.

It only affects ranking.

---

# Consolidation

Long-running agents can accumulate many narrow memories around the same topic.

Munin can consolidate related memories into a derived summary.

For example:

```text
Memory A
Memory B
Memory C
      ↓
Consolidation
      ↓
Derived Summary Memory
```

The source memories remain stored.

The consolidated memory keeps provenance links back to the evidence it was derived from.

Consolidation is therefore not the same thing as superseding.

One compresses related knowledge.

The other represents changing truth.

---

# Memory Operations UI

Munin includes a React/Vite frontend for inspecting how the memory system behaves.

The frontend is an observability and debugging layer.

It does **not** reimplement backend memory logic.

---

## Overview

Shows the current state of the selected scope.

Includes:

- total memories
- active memories
- superseded memories
- invalidated memories
- recent activity
- namespaces
- agent provenance

---

## Memory Graph

Visualizes relationships between real memories.

Supported relationship types include:

```text
SUPERSEDES
UPDATES
CONTRADICTS
DERIVED_FROM
```

The graph supports both:

```text
2D Analysis Mode
3D Spatial Mode
```

The same backend memory graph is used in both modes.

Only the renderer changes.

---

## Memory Explorer

A searchable, filterable view of stored memories.

The Inspector can expose:

- memory content
- type
- status
- importance
- confidence
- namespace
- agent provenance
- source event
- validity window
- temporal history
- consolidation provenance
- raw metadata

---

## Context Assembly

This screen shows what Munin would actually send to an agent.

It exposes:

- the query
- selected memories
- assembled context
- token usage
- score components
- selection reason codes
- Context Trace
- graph visualization of selected memories

This makes retrieval behavior inspectable rather than opaque.

---

## Timeline

Displays how facts change over time.

Example:

```text
SQLite
  │
  │ SUPERSEDES
  ▼
PostgreSQL
```

The original memory remains visible as historical state.

---

## Conflict Center

Displays unresolved contradictions.

Example:

```text
Memory A
    ╲
     CONTRADICTS
    ╱
Memory B
```

Munin does not fabricate a resolution when the evidence is insufficient.

---

# Architecture

```text
External Agent
      │
      ▼
Munin API / SDK
      │
      ├──────────── remember()
      │
      ▼
    Event
      │
      ▼
  Admission
      │
      ▼
Deduplication
      │
      ▼
Temporal Reasoning
      │
      ▼
 Durable Memory
      │
      ├──────── embeddings
      ├──────── provenance
      ├──────── lifecycle
      ├──────── reinforcement
      └──────── consolidation
      │
      ▼
Context Assembly
      │
      ▼
Agent-ready Context
```

---

# Tech Stack

## Backend

- Python 3.12+
- FastAPI
- SQLAlchemy
- Alembic
- SQLite
- Pydantic
- Sentence Transformers
- NumPy

## Frontend

- React
- TypeScript
- Vite
- Tailwind CSS
- Custom NERV-inspired UI
- `react-force-graph-2d`
- `react-force-graph-3d`

---

# Quick Start

## 1. Clone the repository

```bash
git clone https://github.com/nirupamc/muninn.git
cd muninn
```

---

## 2. Create a virtual environment

```bash
python -m venv .venv
```

### Windows

```powershell
.venv\Scripts\Activate.ps1
```

### macOS / Linux

```bash
source .venv/bin/activate
```

---

## 3. Install the backend

```bash
pip install -e ".[dev]"
```

---

## 4. Configure the environment

### Windows

```powershell
Copy-Item .env.example .env
```

### macOS / Linux

```bash
cp .env.example .env
```

---

## 5. Run database migrations

```bash
alembic upgrade head
```

---

## 6. Start the backend

```bash
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

API documentation:

```text
http://127.0.0.1:8000/docs
```

Health endpoint:

```text
http://127.0.0.1:8000/health
```

---

## 7. Start the frontend

In another terminal:

```bash
npm install
npm run dev
```

Open:

```text
http://127.0.0.1:5173
```

---

# Offline Embeddings

Munin uses:

```text
sentence-transformers/all-MiniLM-L6-v2
```

After the model has been cached locally, strict offline mode can be enabled.

### Windows PowerShell

```powershell
$env:EMBEDDING_LOCAL_FILES_ONLY="true"
$env:HF_HUB_OFFLINE="1"
$env:TRANSFORMERS_OFFLINE="1"

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Munin fails clearly if strict local mode is enabled and the real embedding model is unavailable.

It does not silently substitute fake embeddings.

---

# Demo Dataset

With the backend running:

```bash
python scripts/seed_demo.py
```

This creates the repeatable namespace:

```text
demo:munin
```

through the normal Munin pipeline.

The demo includes:

- multiple agents
- durable memories
- reinforcement
- temporal replacement
- unresolved contradiction
- consolidation
- context retrieval

Recommended walkthrough:

```text
Overview
   ↓
Memory Explorer
   ↓
Memory Graph
   ↓
Context Assembly
   ↓
Timeline
   ↓
Conflict Center
```

---

# Python SDK

External agents can interact with Munin through the HTTP SDK.

```python
from app.sdk import MuninClient

client = MuninClient(
    base_url="http://127.0.0.1:8000",
    namespace="project:munin",
    user_id="user-1",
    agent_id="cursor",
)

client.remember(
    "Munin is the current project."
)

context = client.get_context(
    "Continue working on Munin."
)

print(context.text)
```

The SDK talks to Munin over HTTP.

It never accesses the SQLite database directly.

---

# Agent-Facing API

The two main high-level operations are:

```text
POST /api/v1/agent/remember
POST /api/v1/agent/context
```

External agents should normally use these instead of manually orchestrating admission, deduplication, temporal reasoning, and context assembly themselves.

Lower-level APIs remain available for debugging and inspection.

FastAPI exposes the complete current API surface at:

```text
/docs
```

---

# Safety Principles

Munin intentionally prefers conservative behavior.

## False merges are dangerous

Embedding similarity never directly merges memories.

---

## History should survive change

Superseded memories remain stored.

---

## Contradictions should remain visible

Munin does not silently resolve uncertain conflicts.

---

## Decay should not destroy knowledge

Decay only changes effective ranking.

---

## Consolidation should preserve evidence

Source memories remain available.

---

## Context is untrusted data

Retrieved memory is context for an agent.

It should not be treated as privileged system instruction.

---

# Testing

Run the full test suite:

```bash
pytest
```

Evaluation suites:

```bash
python -m app.admission.evaluate
python -m app.deduplication.evaluate
python -m app.temporal.evaluate
python -m app.context.evaluate
python -m app.decay.evaluate
python -m app.consolidation.evaluate
python -m app.agent.evaluate
```

---

# Project Status

| Milestone | Focus | Status |
|---|---|---|
| M0 | Durable Memory Foundation | ✅ |
| M1 | Semantic Retrieval | ✅ |
| M2 | Memory Admission | ✅ |
| M3 | Deduplication & Reinforcement | ✅ |
| M4 | Contradiction + Temporal Memory | ✅ |
| M4.1 | Temporal Boundary Hardening | ✅ |
| M5 | Context Assembly | ✅ |
| M6 | Decay + Consolidation | ✅ |
| M7A | Agent Integration | ✅ |
| M7B | Memory Operations Frontend | ✅ |

**Munin v1 is functionally complete.**

---

# Known Limitations

- SQLite is currently the primary persistence backend.
- Temporal and conflict views currently perform bounded per-memory history reads because no global temporal relationship endpoint exists.
- Graph rendering intentionally uses node limits for performance.
- Reinforcement relationships do not yet have a dedicated graph-read endpoint.
- Context Assembly currently exposes selected memories but not all skipped candidates.
- The deterministic temporal evaluation contains one known missed-supersede case.
- MCP support is intentionally deferred.

---

# Roadmap

Potential future work includes:

- MCP integration
- PostgreSQL backend
- typed entity knowledge graph
- richer hybrid graph + vector retrieval
- additional ingestion sources
- background consolidation / memory maintenance
- deeper agent-runtime integration

These are deliberately outside the scope of Munin v1.

---

# Philosophy

Munin is not trying to make an LLM remember everything.

It is trying to build a reliable memory system around the LLM.

The model can change.

The session can disappear.

The application can restart.

The agent can be replaced.

**The memory remains.**
