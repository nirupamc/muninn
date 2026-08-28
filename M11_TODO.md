# M11 — HYBRID MEMORY RETRIEVAL

## STATUS: COMPLETE

---

## TAKEOVER AUDIT (Phase 0 — COMPLETE)

### Repository State
- **Branch:** main
- **Working tree:** M10 + M11 changes uncommitted
- **Test count:** 455 collected (full suite slow due to sentence-transformers)
- **M10 tests:** 61/61 pass
- **M11 tests:** 46/46 pass

### Current Retrieval Architecture (BEFORE M11)
```
API: POST /api/v1/context
  → ContextService.assemble(req)
    → ContextAssembler.assemble(...)
      1. Embed query
      2. Retrieve candidates (EmbeddingRepository.list_search_candidates)
      3. Score: cosine_similarity → weighted sum
      4. Sort, suppress redundant
      5. Select within budget (M10: L0/L1/L2)
      6. Detect conflicts, format
```

**Purely dense/vector retrieval. No lexical, no graph.**

---

## IMPLEMENTATION SUMMARY

### Files Created (M11)
| File | Purpose |
|------|---------|
| `app/retrieval/__init__.py` | Retrieval module |
| `app/retrieval/models.py` | RetrievalHit, FusedCandidate, RetrievalMode, RetrieverTrace |
| `app/retrieval/dense.py` | DenseRetriever (wraps existing semantic search) |
| `app/retrieval/lexical.py` | LexicalRetriever with local BM25 + tokenizer |
| `app/retrieval/graph.py` | GraphRetriever (temporal/dedup relationship traversal) |
| `app/retrieval/fusion.py` | RRF fusion (reciprocal rank fusion) |
| `app/retrieval/service.py` | HybridRetriever orchestrator |
| `tests/test_hybrid_retrieval.py` | 46 focused tests |

### Files Modified (M11)
| File | Change |
|------|--------|
| `app/config.py` | Added `retrieval_mode`, `retrieval_rrf_k`, `retrieval_graph_enabled` |
| `app/context/assembler.py` | Integrated HybridRetriever, blended semantic+RRF scores |
| `app/context/models.py` | Added `RetrievalTraceEntry`, `retrieval_trace` to `AssemblyTrace` |
| `app/context/service.py` | Pass `retrieval_mode` from request to assembler |
| `app/schemas/context.py` | Added `retrieval_mode` to `ContextRequest` |
| `ARCHITECTURE.md` | Added M11 retrieval architecture docs |
| `README.md` | Added Hybrid Retrieval section |

### Retrieval Architecture (AFTER M11)
```
API: POST /api/v1/context (optional retrieval_mode=dense|lexical|hybrid)
  → ContextAssembler.assemble(...)
    1. Hybrid Retrieval (if mode != dense):
       → DenseRetriever: embed query → cosine similarity
       → LexicalRetriever: BM25 over content + gist + summary
       → GraphRetriever: traverse temporal/dedup relationships (seeds from dense/lexical)
       → RRF Fusion: combine ranked results
    2. Blend semantic scores with hybrid RRF scores
    3. Add candidates from lexical/graph not in dense
    4. Temporal validity filter
    5. Score, sort, suppress redundancy
    6. Select within budget (M10: L0/L1/L2)
    7. Detect conflicts, format
```

---

## TEST RESULTS

### M11 Tests: 46/46 PASS
| Category | Tests | Status |
|----------|-------|--------|
| Tokenization | 8 | ✅ All pass |
| BM25 Index | 9 | ✅ All pass |
| RRF Fusion | 7 | ✅ All pass |
| Lexical Retriever DB | 5 | ✅ All pass |
| Temporal Truth | 2 | ✅ All pass |
| Namespace Isolation | 2 | ✅ All pass |
| Failure Safety | 5 | ✅ All pass |
| Representation Unchanged | 2 | ✅ All pass |
| Benchmark Queries | 2 | ✅ All pass |
| HybridRetrievalResult | 2 | ✅ All pass |
| Lexical + Representations | 2 | ✅ All pass |

### M10 Regression: 61/61 PASS ✅

---

## DEFINITION OF DONE

- [x] existing dense retrieval preserved
- [x] lexical BM25 retrieval implemented
- [x] technical identifiers preserved (_load_max_checkpoint, M8.3A, paths, error codes)
- [x] lexical lifecycle correct (create/patch/delete sync)
- [x] RRF implemented (k=60, deterministic)
- [x] hybrid retrieval implemented
- [x] namespace isolation proven
- [x] temporal truth preserved (retrieval is read-only)
- [x] dedup semantics unchanged
- [x] context hierarchy unchanged (M10 L0/L1/L2 still works)
- [x] retrieval trace extended (per-channel rank/score/error)
- [x] exact identifier benchmark created
- [x] semantic benchmark created
- [x] mixed benchmark created
- [x] failure fallbacks verified
- [x] docs updated (README + ARCHITECTURE)
- [x] M11 tests pass (46/46)
- [x] relevant regressions pass (M10 61/61)
- [x] git diff --check clean
- [x] M11_TODO.md current and accurate

### Graph retrieval:
- [x] implemented using temporal/dedup relationships (MemoryTemporalDecision + MemoryReinforcement)
- Bounded traversal: max depth 2, 20 candidates, namespace-locked
- Seeded from dense/lexical hits (not standalone)

### Acceptance condition:
- Default remains `dense` (safe, proven)
- `hybrid` available via `retrieval_mode` parameter
- Evaluation shows lexical improves exact identifier retrieval
- No semantic regression

---

## RESUME HERE

**Last verified:** All 46 M11 tests pass. 61/61 M10 tests pass. git diff --check clean.
**Next command/action:** M11 complete. Ready for M12 or commit.
**Known blockers:**
- Full test suite (sentence-transformers) very slow on this Windows machine; targeted subsets verified
- M10 + M11 changes are uncommitted
- Default retrieval mode is `dense` (not `hybrid`) for safety

## M11 final status: COMPLETE
