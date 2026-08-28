# M10 — HIERARCHICAL MEMORY REPRESENTATION + TRACE FOUNDATION

## STATUS: IN PROGRESS

---

## TAKEOVER AUDIT (Phase 0 — COMPLETE)

### Repository State
- **Branch:** main
- **Working tree:** clean (1 minor change in tsconfig.json — trailing whitespace)
- **Current migration head:** `a7c1f0d9e2b4` (M8.1 project discovery)
- **Migration chain:** 001_initial → 002 → 003 → 004 → 005 → 006 → bd4354d → a7c1f0d9e2b4
- **Test count:** 455 collected (full suite slow due to sentence-transformers model loading)
- **No ARCHITECTURE.md exists**

### Key Architecture Findings

#### Memory Model (`app/models/memory.py`)
- ORM model: `Memory` in `memories` table
- Fields: id, namespace, user_id, agent_id, content (Text), memory_type (Enum), importance, confidence, status, created_at, updated_at, last_accessed_at, valid_from, valid_until, source_event_id, metadata (JSON)
- **No gist/summary fields exist yet**
- Table indexes: namespace, namespace+status, created_at

#### Memory Creation Path
1. `AgentService.remember()` → `EventService.create()` → `AdmissionService.admit_event()`
2. Admission → `DeduplicationService.process_candidate()` → `MemoryService.create()`
3. Capture → `CaptureService._process_capture()` → `AgentService.remember()`

#### Context Assembly (`app/context/`)
- `ContextAssembler.assemble()` pipeline: embed query → retrieve candidates → score → sort → suppress redundancy → select within budget → detect conflicts → format
- **Currently uses L2 (full content) only** — no representation selection
- `SelectedMemory.content` is always `memory.content` (full text)
- Token estimation: `SimpleTokenEstimator` (ceil(len/4))
- `AssemblyTrace` already exists with basic metadata

#### Context Models
- `ScoredCandidate`, `SelectedMemory`, `AssemblyTrace`, `ContextConfig`, `ConflictPair`
- `SkipReason` enum: REDUNDANT, OUT_OF_BUDGET, SUPERSEDED, etc.
- `ReasonCode` enum: HIGH_SEMANTIC_RELEVANCE, HIGH_IMPORTANCE, RECENT, etc.

#### Context Budget (`app/context/budget.py`)
- `select_within_budget()` uses `format_memory_line(content)` → `- {content}`
- Full content always used, no representation selection

#### API Schemas
- `MemoryRead` (response): id, namespace, user_id, agent_id, content, memory_type, importance, confidence, status, timestamps, metadata
- **No gist/summary in response**
- `ContextResponse` / `MemoryUsed`: no representation level info

#### Frontend
- Explorer: `frontend/src/features/explorer/MemoryExplorer.tsx`
- Inspector: `frontend/src/components/inspector/MemoryInspector.tsx`

### Files That Will Need Changes
1. `app/models/memory.py` — add gist, summary fields
2. `app/schemas/memory.py` — add to MemoryRead, MemoryCreate
3. `app/context/assembler.py` — representation selection
4. `app/context/budget.py` — use selected representation
5. `app/context/models.py` — add representation level to SelectedMemory, trace
6. `app/services/memory_service.py` — generate representations on create
7. `app/api/memories.py` — expose gist/summary
8. `app/config.py` — representation config options
9. `app/cli.py` — backfill command
10. Alembic migration for gist + summary columns
11. New: `app/memory/representations/` module
12. Tests: `tests/test_representations.py`, `tests/test_context_hierarchical.py`

### Critical Constraints
- Memory.content remains the authoritative L2 source
- gist/summary are representations of a memory, NOT separate memories
- Must not break: temporal, dedup, decay, namespace isolation, existing retrieval
- Representation generation failure must NOT lose the memory
- Backward compat: existing rows with NULL gist/summary must work

---

## BASELINE TESTS (Phase 1)

**Status:** PARTIAL — full suite very slow (sentence-transformers model load per file)
- `test_health.py`: 1 pass ✅
- `test_memories.py`: 10 collected, 8+ passed before timeout
- Full collection: 455 tests
- **Note:** Test suite is known to be slow due to sentence-transformers; individual file runs work with generous timeout

---

## IMPLEMENTATION PLAN

### Phase 2 — Design Representation Contract
- [ ] Document L0/L1/L2 model in M10_TODO.md
- [ ] Define token limits and selection rules

### Phase 3 — Database / Migration
- [ ] Add gist (Text, nullable) and summary (Text, nullable) to Memory model
- [ ] Create Alembic migration
- [ ] Verify upgrade/downgrade

### Phase 4 — Representation Service
- [ ] Create `app/memory/representations/` module
- [ ] Implement `RepresentationService.build_representations(memory)`
- [ ] Implement `select_representation(memory, context_state)`

### Phase 5 — Deterministic Baseline
- [ ] L0 gist: extract concise first-sentence gist
- [ ] L1 summary: preserve important clauses, bounded length
- [ ] No LLM dependency

### Phase 6 — Generation Timing
- [ ] Generate on memory admission (post-create hook)
- [ ] Failure-safe: gist/summary remain null if generation fails

### Phase 7 — Backfill
- [ ] CLI command for backfilling existing memories
- [ ] Idempotent, batched, skip already-generated

### Phase 8 — Context Assembly Integration
- [ ] Extend `select_within_budget()` to use representation level
- [ ] Add `select_representation()` function

### Phase 9 — Token Accounting
- [ ] Track L0/L1/L2 costs per memory
- [ ] Tests comparing flat vs hierarchical

### Phase 10 — Trace Foundation
- [ ] Extend `AssemblyTrace` / `SelectedMemory` with representation info
- [ ] Record selected_level, token_cost, selection_reason

### Phase 11 — API Extension
- [ ] Add gist/summary to `MemoryRead`
- [ ] Add representation info to `ContextResponse` / `MemoryUsed`

### Phase 12 — Frontend Minimal Support
- [ ] Show gist/summary in MemoryInspector
- [ ] Show representation level in context view

### Phase 13-14 — Semantic Invariants
- [ ] L0/L1 are NOT separate memories (no dedup/decay/temporal on them)
- [ ] Embeddings remain on authoritative memory only

### Phase 15-16 — Test Data + Tests
- [ ] 10 representative fixtures
- [ ] 20+ focused test cases

### Phase 17-20 — Regression + Evaluation
- [ ] Retrieval regression
- [ ] Context quality evaluation (flat vs hierarchical)
- [ ] Backward compat: NULL gist/summary rows
- [ ] Failure safety tests

### Phase 21 — Documentation
- [ ] Update README with Hierarchical Memory Representation section
- [ ] Create ARCHITECTURE.md

### Phase 22 — Final Regression
- [ ] Full test suite
- [ ] git diff --check clean

---

## RESUME HERE

**Last verified:** Phase 0 — Takeover audit complete. Architecture fully understood.
**Next command/action:** Begin Phase 2 — Design representation contract, then Phase 3 — Alembic migration.
**Known blockers:**
- Full test suite is slow (sentence-transformers); run targeted subsets for verification
- Frontend files are TypeScript/React — changes there need careful attention
