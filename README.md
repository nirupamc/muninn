# Munin

**Local-first persistent memory layer for AI agents.**

Munin gives AI agents durable, project-aware memory that survives model switches, session resets, application restarts, and agent changes. Memory belongs to the user and the project—not to a single LLM session.

---

## Why Munin?

You might work on the same repo using Codex today, OpenCode tomorrow, and a local model next week.

Without external memory:
```
Agent A → context disappears → Agent B starts from zero
```

With Munin:
```
Agent A → Munin captures useful state → Agent B continues from project memory
```

---

## Screenshots

<p align="center">
  <img src="./images github/Screenshot 2026-08-26 002817.png" width="49%" />
  <img src="./images github/Screenshot 2026-08-26 004450.png" width="49%" />
</p>
<p align="center">
  <img src="./images github/Screenshot 2026-08-26 004510.png" width="49%" />
  <img src="./images github/Screenshot 2026-08-26 004543.png" width="49%" />
</p>
<p align="center">
  <img src="./images github/Screenshot 2026-08-26 004556.png" width="49%" />
  <img src="./images github/Screenshot 2026-08-26 004628.png" width="49%" />
</p>

*Overview · Projects · Memory Explorer · Graph · Context · Timeline*

---

## How it works

```
Developer Activity
        │
        ├── Git
        ├── Filesystem
        └── Agent Capture Bridge
                ↓
        Project Resolution
                ↓
        Memory Admission
                ↓
        Dedup + Temporal Reasoning
                ↓
        Decay + Consolidation
                ↓
        Context Assembly
                ↓
             Agent
```

**Lifecycle:** Capture → Decide → Remember → Update → Retrieve → Continue

---

## Core capabilities

- **Local-first persistent memory** — SQLite + Alembic, fully offline capable
- **Project discovery** — Scans configured workspace roots, registers Git repositories
- **Git activity capture** — Commits, branch changes, with checkpoint persistence
- **Batched filesystem activity** — Debounced file-change batches, privacy-aware exclusions
- **Generic agent capture bridge** — HTTP API + CLI for Codex / Kilo Code / OpenCode / custom agents
- **Semantic retrieval** — sentence-transformers (MiniLM-L6-v2) with cached offline mode
- **Memory admission** — Explicit + inferred signals, secret filtering
- **Deduplication + Reinforcement** — Semantic shortlist → relationship classification
- **Temporal memory** — NEW / UPDATES / SUPERSEDES / CONTRADICTS with validity windows
- **Decay + Consolidation** — Query-time decay, provenance-preserving consolidation
- **Context assembly** — Hybrid ranking, token budgeting, redundancy suppression
- **Memory Operations UI** — Explorer, 2D/3D Graph, Timeline, Conflicts, Context Trace

---

## Project-aware memory

Munin can scan configured workspace roots and register Git repositories as first-class projects:

```
E:\
├── Muninn        → project:muninn
├── Huginn        → project:huginn
└── Aletheia      → project:aletheia
```

Each project receives a deterministic namespace (`project:<slug>`) with collision resolution.
Captured activity flows through the **existing memory admission pipeline**—it is not blindly stored.
Projects track status: DISCOVERED → CONNECTED → ACTIVE → MEMORIZED → DISABLED.
Git checkpoints persist across restarts; no commit is recaptured.

---

## Memory intelligence (concise)

| Stage | What it does |
|-------|--------------|
| **Admission** | Decides STORE/IGNORE using explicit + inferred signals; rejects secrets |
| **Deduplication** | Semantic shortlist → relationship classification (DUPLICATE / REINFORCES / NEW) |
| **Temporal** | Tracks truth over time: SUPERSEDES, UPDATES, CONTRADICTS with validity windows |
| **Decay** | Query-time exponential decay by memory type; never deletes |
| **Consolidation** | Compresses related memories into derived summaries; preserves source provenance |
| **Context Assembly** | Semantic retrieval → scope filter → temporal validity → hybrid ranking → token budget → conflict awareness |

---

## Cross-agent continuity

```
Codex
  ↓ works on project
  ↓ Munin captures session summary + Git commits
session ends
OpenCode / local LLM
  ↓ requests context via project namespace
  ↓ continues from durable project state
```

**Integrations:** Codex, Kilo, OpenCode, Cline, Aider — each with native session capture adapters and context injection launch adapters.

---

## UI

| Screen | Purpose |
|--------|---------|
| **Overview** | Scope health: counts, recent activity, agent provenance |
| **Projects** | Real registered workstation projects; capture toggle; status; detail view |
| **Explorer** | Searchable, filterable memory list with full inspector |
| **Graph** | 2D Analysis / 3D Spatial modes; SUPERSEDES, UPDATES, CONTRADICTS, DERIVED_FROM |
| **Context** | Query → assembled LLM-ready context; score breakdown; Context Trace graph |
| **Timeline** | Temporal history: how facts changed over time |
| **Conflicts** | Unresolved contradictions surfaced explicitly |

Screenshots above demonstrate each screen.

---

## Tech stack

**Backend:** Python 3.12+ / FastAPI / SQLAlchemy / Alembic / SQLite / Pydantic / sentence-transformers / NumPy
**Frontend:** React 19 / TypeScript / Vite / Tailwind / `react-force-graph-2d` / `react-force-graph-3d` / `@mdrbx/nerv-ui`

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/nirupamc/muninn.git
cd muninn

# 2. Virtual environment
python -m venv .venv
.venv\Scripts\Activate.ps1   # Windows
# source .venv/bin/activate   # macOS/Linux

# 3. Install
pip install -e ".[dev]"
npm install

# 4. Configure
Copy-Item .env.example .env   # Windows
# cp .env.example .env        # macOS/Linux

# 5. Migrate
alembic upgrade head

# 6. Start backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# 7. Start frontend (separate terminal)
npm run dev
```

**URLs**
Frontend: `http://127.0.0.1:5173`
API: `http://127.0.0.1:8000`
Docs: `http://127.0.0.1:8000/docs`
Health: `http://127.0.0.1:8000/health`

---

## Project Discovery

Configure workspace roots in `.env` (semicolon-separated):

```env
MUNIN_WORKSPACE_ROOTS=C:\Projects;D:\Work
```

Then:

```bash
munin project scan
munin project list
munin project enable <project-id>
munin project disable <project-id>
```

---

## Agent capture

Submit a session summary via CLI:

```bash
munin capture summary \
  --path C:\Projects\Muninn \
  --agent codex \
  --session session-1 \
  --content "Implemented JWT auth. Added login/register endpoints. Created AuthMiddleware."
```

Or via HTTP:

```bash
curl -X POST http://127.0.0.1:8000/api/v1/capture/events/agent-summary \
  -H "Content-Type: application/json" \
  -d '{"project_path": "C:\Projects\Muninn", "agent_id": "codex", "session_id": "s-1", "summary": "..."}'
```

Native session adapters are available for Codex, Kilo, OpenCode, Cline, and Aider.
The capture API/CLI remains available for custom integrations.

---

## Verification

| Suite | Result |
|-------|--------|
| Backend tests | 154 passing (targeted suites) |
| Agent session eval | 7/7 passed |
| Capture eval | 9/9 passed, safety targets met |
| Admission | 28 cases, 100% accuracy |
| Deduplication | 32 cases, 100% accuracy, 0 false merges |
| Temporal | 35 cases, 94.3% accuracy, 0 false supersedes |
| Context | 31 cases, 100% top-1 accuracy |

**Safety targets met:**
- Duplicate agent captures: 0
- Namespace leaks: 0
- Secret captures: 0
- Session replay: 0
- Agent session adapters: 5 (Codex, Kilo, OpenCode, Cline, Aider)

---

## Limitations

- **M8.3A live E2E acceptance deferred** — pipeline-level session capture is verified; fresh live session → durable memory requires manual execution
- **Live cross-agent retrieval of newly session-derived memory deferred** — context injection works; session-derived cross-agent continuity is a future acceptance item
- Session capture depends on third-party agent local storage formats
- Filesystem monitoring is polling-based (debounce window), not native OS events
- Git capture tracks current branch only
- Project discovery depth bounded (default 3 levels)
- Windows is the primary verified platform
- Not production-hardened; no auth, no distributed deployment
- Old development DB may contain historical duplicate artifacts from early ingestion

---

## Roadmap

- Full live session-derived cross-agent acceptance
- Native filesystem watcher (watchdog / ReadDirectoryChangesW)
- Windows background service / desktop packaging
- MCP (Model Context Protocol) integration

---

## Name

In Norse mythology, Odin has two ravens:
- **Huginn** — thought
- **Muninn** — memory

This project uses the name **Munin** and represents the memory half of that idea.
