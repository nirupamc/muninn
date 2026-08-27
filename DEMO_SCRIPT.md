# Munin Demo Script (3-5 minutes)

## Prerequisites
- Backend running: `python -m uvicorn app.main:app --host 127.0.0.1 --port 8000`
- Frontend running: `npm run dev`

## Demo Flow

### 1. Show Project Registry (30s)
Open frontend → Projects tab
- Show registered workstation projects (8 projects)
- Point out Huginn with 146 memories
- Show capture status and memory counts

### 2. Show Memory Explorer (30s)
Open frontend → Explorer tab
- Search for "decision" in Huginn namespace
- Show memory content, timestamps, provenance
- Demonstrate filtering by project

### 3. Show Graph (30s)
Open frontend → Graph tab
- Show memory relationships (SUPERSEDES, UPDATES, CONTRADICTS)
- Toggle between 2D Analysis and 3D Spatial modes
- Point out provenance metadata

### 4. Agent Detection (30s)
Run in terminal:
```bash
python -m app.cli agents
```
- Show 5 detected agents: Codex, Kilo, OpenCode, Cline, Aider
- All installed and supported

### 5. Context Injection Dry Run (30s)
Run in terminal:
```bash
python -m app.cli run --project "E:\huginn" --dry-run -- codex
```
- Show resolved project: huginn
- Show namespace: project:huginn
- Show 8 context memories, 300 tokens
- Show Munin briefing that would be injected

### 6. Explain Architecture (30s)
- Project discovery scans workspace roots
- Capture pipeline: Git + Filesystem + Agent Sessions
- Memory pipeline: Admission → Dedup → Temporal → Consolidation
- Context assembly: Semantic retrieval → token budget → agent injection
- Session capture: AgentSessionAdapter reads local session files

### 7. State Limitations Honestly (30s)
- Pipeline-level session capture is verified
- Fresh live session → durable memory is a deferred acceptance item
- Cross-agent retrieval of newly captured session memory is deferred
- All core architecture is implemented and tested

## Key Numbers
- 154/154 backend tests passing
- 7/7 agent session eval passing
- 9/9 capture eval passing, all safety targets met
- 5 agent integrations (Codex, Kilo, OpenCode, Cline, Aider)
- 1450 memories across 8 projects
- 0 session replays, 0 duplicate captures, 0 secret leaks
