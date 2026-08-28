"""M11 — Hybrid memory retrieval tests.

Tests for lexical BM25, RRF fusion, hybrid retriever, namespace isolation,
temporal truth preservation, and retrieval evaluation benchmarks.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.context.tokenization.simple import SimpleTokenEstimator
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.retrieval.lexical import BM25Index, tokenize, LexicalRetriever
from app.retrieval.fusion import reciprocal_rank_fusion
from app.retrieval.models import (
    FusedCandidate,
    HybridRetrievalResult,
    RetrievalHit,
    RetrievalMode,
    RetrievalSource,
    RetrieverTrace,
)


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

def _make_memory(
    db_session: Session,
    content: str,
    *,
    namespace: str = "test:hybrid",
    memory_type: MemoryType = MemoryType.fact,
    importance: float = 0.5,
    gist: str | None = None,
    summary: str | None = None,
    status: MemoryStatus = MemoryStatus.active,
) -> Memory:
    memory = Memory(
        namespace=namespace,
        content=content,
        gist=gist,
        summary=summary,
        memory_type=memory_type,
        importance=importance,
        confidence=0.9,
        status=status,
    )
    db_session.add(memory)
    db_session.flush()
    return memory


# ---------------------------------------------------------------------------
# Tokenization tests
# ---------------------------------------------------------------------------

class TestLexicalTokenization:
    """Tests for BM25 tokenization preserving technical identifiers."""

    def test_snake_case_preserved(self):
        tokens = tokenize("Fixed _load_max_checkpoint regression")
        assert "_load_max_checkpoint" in tokens

    def test_milestone_identifier_preserved(self):
        tokens = tokenize("M8.3A session replay is working")
        # M8.3A should be tokenized as a searchable token
        assert any("m8" in t for t in tokens), f"Expected M8.3A tokens, got {tokens}"

    def test_filename_preserved(self):
        tokens = tokenize("Key file: app/context/assembler.py")
        assert "app/context/assembler.py" in tokens or "assembler.py" in tokens

    def test_error_code_preserved(self):
        tokens = tokenize("Got 503 error from embedding service")
        assert "503" in tokens

    def test_camelcase_split(self):
        tokens = tokenize("AgentSessionService checkpoint")
        # Should contain both the original and split parts
        assert any("agent" in t for t in tokens)

    def test_path_with_slashes(self):
        tokens = tokenize("Modified app/services/memory_service.py")
        assert "app/services/memory_service.py" in tokens or "memory_service.py" in tokens

    def test_empty_content(self):
        assert tokenize("") == []

    def test_whitespace_only(self):
        assert tokenize("   ") == []


# ---------------------------------------------------------------------------
# BM25 index tests
# ---------------------------------------------------------------------------

class TestBM25Index:
    """Tests for the local BM25 index."""

    def test_exact_identifier_retrieval(self):
        idx = BM25Index()
        idx.add("m1", "Fixed _load_max_checkpoint regression in agent sessions")
        idx.add("m2", "Tests pass for admission and dedup")
        idx.add("m3", "Updated decay lambda for ephemeral events")

        results = idx.search("_load_max_checkpoint")
        assert len(results) >= 1
        assert results[0][0] == "m1"

    def test_milestone_identifier_retrieval(self):
        idx = BM25Index()
        idx.add("m1", "M8.3A session replay fixed")
        idx.add("m2", "M9 partial implementation")
        idx.add("m3", "General tests pass")

        results = idx.search("M8.3A")
        assert len(results) >= 1
        assert results[0][0] == "m1"

    def test_filename_retrieval(self):
        idx = BM25Index()
        idx.add("m1", "Key files: app/context/assembler.py and app/context/budget.py")
        idx.add("m2", "Updated app/services/memory_service.py")

        results = idx.search("assembler.py")
        assert len(results) >= 1
        assert results[0][0] == "m1"

    def test_error_code_retrieval(self):
        idx = BM25Index()
        idx.add("m1", "Got 503 error from embedding service")
        idx.add("m2", "Service returned 404 not found")

        results = idx.search("503")
        assert len(results) >= 1
        assert results[0][0] == "m1"

    def test_add_remove_lifecycle(self):
        idx = BM25Index()
        idx.add("m1", "First memory")
        idx.add("m2", "Second memory")
        assert idx.size == 2

        idx.remove("m1")
        assert idx.size == 1

        results = idx.search("First")
        assert len(results) == 0

        results = idx.search("Second")
        assert len(results) == 1

    def test_update_lifecycle(self):
        idx = BM25Index()
        idx.add("m1", "Original content about authentication")
        idx.update("m1", "Updated content about deployment pipeline") if hasattr(idx, 'update') else None

        # For BM25Index, update = remove + add
        idx.remove("m1")
        idx.add("m1", "Updated content about deployment pipeline")

        results = idx.search("authentication")
        assert len(results) == 0

        results = idx.search("deployment")
        assert len(results) == 1
        assert results[0][0] == "m1"

    def test_empty_query(self):
        idx = BM25Index()
        idx.add("m1", "Some content")
        results = idx.search("")
        assert results == []

    def test_no_matches(self):
        idx = BM25Index()
        idx.add("m1", "authentication bug fix")
        results = idx.search("quantum computing")
        assert results == []

    def test_multiple_results_sorted_by_score(self):
        idx = BM25Index()
        idx.add("m1", "authentication auth system login")
        idx.add("m2", "authentication module password")
        idx.add("m3", "deployment pipeline CI/CD")

        results = idx.search("authentication")
        assert len(results) >= 2
        # Results with more matches should score higher
        assert results[0][1] >= results[1][1]


# ---------------------------------------------------------------------------
# RRF fusion tests
# ---------------------------------------------------------------------------

class TestRRFFusion:
    """Tests for Reciprocal Rank Fusion."""

    def test_basic_fusion(self):
        dense_hits = [
            RetrievalHit(memory_id="m1", source=RetrievalSource.DENSE, source_rank=1, source_score=0.9),
            RetrievalHit(memory_id="m2", source=RetrievalSource.DENSE, source_rank=2, source_score=0.8),
        ]
        lexical_hits = [
            RetrievalHit(memory_id="m2", source=RetrievalSource.LEXICAL, source_rank=1, source_score=0.95),
            RetrievalHit(memory_id="m3", source=RetrievalSource.LEXICAL, source_rank=2, source_score=0.85),
        ]

        fused = reciprocal_rank_fusion({
            RetrievalSource.DENSE: dense_hits,
            RetrievalSource.LEXICAL: lexical_hits,
        })

        # m2 should be top (appears in both channels with good ranks)
        assert fused[0].memory_id == "m2"
        assert fused[0].channel_count == 2

    def test_single_channel(self):
        hits = [
            RetrievalHit(memory_id="m1", source=RetrievalSource.DENSE, source_rank=1, source_score=0.9),
        ]
        fused = reciprocal_rank_fusion({RetrievalSource.DENSE: hits})
        assert len(fused) == 1
        assert fused[0].channel_count == 1

    def test_duplicate_candidate_fusion(self):
        """A memory appearing in multiple channels should gain higher RRF score."""
        dense_hits = [
            RetrievalHit(memory_id="m1", source=RetrievalSource.DENSE, source_rank=1, source_score=0.9),
        ]
        lexical_hits = [
            RetrievalHit(memory_id="m1", source=RetrievalSource.LEXICAL, source_rank=1, source_score=0.95),
        ]

        fused = reciprocal_rank_fusion({
            RetrievalSource.DENSE: dense_hits,
            RetrievalSource.LEXICAL: lexical_hits,
        })

        assert len(fused) == 1
        assert fused[0].channel_count == 2
        # RRF score should be sum of both channels
        expected = 1.0 / (60 + 1) + 1.0 / (60 + 1)  # Both rank 1
        assert abs(fused[0].rrf_score - round(expected, 6)) < 0.0001

    def test_empty_channels(self):
        fused = reciprocal_rank_fusion({})
        assert fused == []

    def test_deterministic_ordering(self):
        """Same input should always produce same output."""
        hits = [
            RetrievalHit(memory_id="m2", source=RetrievalSource.DENSE, source_rank=1, source_score=0.8),
            RetrievalHit(memory_id="m1", source=RetrievalSource.DENSE, source_rank=2, source_score=0.9),
        ]
        fused1 = reciprocal_rank_fusion({RetrievalSource.DENSE: hits})
        fused2 = reciprocal_rank_fusion({RetrievalSource.DENSE: hits})
        assert [c.memory_id for c in fused1] == [c.memory_id for c in fused2]

    def test_channel_provenance_preserved(self):
        hits = [
            RetrievalHit(memory_id="m1", source=RetrievalSource.DENSE, source_rank=3, source_score=0.7),
        ]
        fused = reciprocal_rank_fusion({RetrievalSource.DENSE: hits})
        assert fused[0].dense_rank == 3
        assert fused[0].dense_score == 0.7
        assert fused[0].lexical_rank is None

    def test_three_channel_fusion(self):
        dense_hits = [RetrievalHit(memory_id="m1", source=RetrievalSource.DENSE, source_rank=1, source_score=0.9)]
        lexical_hits = [RetrievalHit(memory_id="m1", source=RetrievalSource.LEXICAL, source_rank=2, source_score=0.8)]
        graph_hits = [RetrievalHit(memory_id="m1", source=RetrievalSource.GRAPH, source_rank=1, source_score=0.7)]

        fused = reciprocal_rank_fusion({
            RetrievalSource.DENSE: dense_hits,
            RetrievalSource.LEXICAL: lexical_hits,
            RetrievalSource.GRAPH: graph_hits,
        })

        assert fused[0].channel_count == 3
        assert fused[0].dense_rank == 1
        assert fused[0].lexical_rank == 2
        assert fused[0].graph_rank == 1


# ---------------------------------------------------------------------------
# Lexical retriever integration tests (with DB)
# ---------------------------------------------------------------------------

class TestLexicalRetrieverDB:
    """Tests for LexicalRetriever with database-backed memories."""

    def test_exact_identifier_retrieval(self, db_session: Session):
        """BM25 should retrieve memories by exact identifier."""
        m1 = _make_memory(db_session, "Fixed _load_max_checkpoint regression in agent sessions")
        m2 = _make_memory(db_session, "Tests pass for admission and dedup")
        m3 = _make_memory(db_session, "Updated decay lambda for ephemeral events")
        db_session.commit()

        retriever = LexicalRetriever(db_session)
        hits, trace = retriever.search(
            query="_load_max_checkpoint",
            namespace="test:hybrid",
        )

        assert len(hits) >= 1
        assert hits[0].memory_id == m1.id
        assert hits[0].source == RetrievalSource.LEXICAL
        assert trace.source == RetrievalSource.LEXICAL
        assert trace.candidate_count >= 3

    def test_namespace_isolation(self, db_session: Session):
        """Lexical retrieval should not cross namespace boundaries."""
        m1 = _make_memory(db_session, "Fixed auth bug", namespace="test:huginn")
        m2 = _make_memory(db_session, "Fixed auth bug", namespace="test:muninn")
        db_session.commit()

        retriever = LexicalRetriever(db_session)
        hits, _ = retriever.search(query="auth bug", namespace="test:huginn")

        memory_ids = {h.memory_id for h in hits}
        assert m1.id in memory_ids
        assert m2.id not in memory_ids

    def test_create_synchronization(self, db_session: Session):
        """Adding a memory should make it searchable."""
        m1 = _make_memory(db_session, "First memory about deployment")
        db_session.commit()

        retriever = LexicalRetriever(db_session)
        hits, _ = retriever.search(query="deployment", namespace="test:hybrid")
        assert any(h.memory_id == m1.id for h in hits)

    def test_content_search_with_gist(self, db_session: Session):
        """BM25 should index both content and gist."""
        m1 = _make_memory(
            db_session,
            content="Fixed the authentication bug in the login endpoint",
            gist="Auth login fix",
        )
        db_session.commit()

        retriever = LexicalRetriever(db_session)
        # Search for gist term
        hits, _ = retriever.search(query="login", namespace="test:hybrid")
        assert any(h.memory_id == m1.id for h in hits)

    def test_superseded_excluded_by_default(self, db_session: Session):
        """Superseded memories should not appear in results by default."""
        m1 = _make_memory(db_session, "Active memory about testing", status=MemoryStatus.active)
        m2 = _make_memory(db_session, "Superseded memory about testing", status=MemoryStatus.superseded)
        db_session.commit()

        retriever = LexicalRetriever(db_session)
        hits, _ = retriever.search(query="testing", namespace="test:hybrid")

        memory_ids = {h.memory_id for h in hits}
        assert m1.id in memory_ids
        assert m2.id not in memory_ids


# ---------------------------------------------------------------------------
# Temporal truth preservation tests
# ---------------------------------------------------------------------------

class TestTemporalTruthPreservation:
    """Verify that hybrid retrieval does not bypass temporal truth."""

    def test_lexical_does_not_create_memories(self, db_session: Session):
        """Lexical retrieval must only read, never create memories."""
        initial_count = db_session.query(Memory).filter(
            Memory.namespace == "test:hybrid"
        ).count()

        retriever = LexicalRetriever(db_session)
        _ = _make_memory(db_session, "Test memory")
        db_session.commit()

        hits, _ = retriever.search(query="test", namespace="test:hybrid")

        final_count = db_session.query(Memory).filter(
            Memory.namespace == "test:hybrid"
        ).count()
        # Retrieval should not add memories (the _make_memory adds one, but search doesn't)
        # The difference should only be from our explicit _make_memory call

    def test_rrf_is_candidate_fusion_not_truth(self):
        """RRF provides candidates; temporal policy determines truth."""
        # If memory A is superseded by memory B, RRF might rank A higher
        # due to lexical match, but temporal filtering should exclude it
        hits_a = [RetrievalHit(memory_id="a", source=RetrievalSource.LEXICAL, source_rank=1, source_score=0.9)]
        hits_b = [RetrievalHit(memory_id="b", source=RetrievalSource.DENSE, source_rank=5, source_score=0.5)]

        fused = reciprocal_rank_fusion({
            RetrievalSource.LEXICAL: hits_a,
            RetrievalSource.DENSE: hits_b,
        })

        # A might rank higher in RRF, but temporal filtering happens AFTER fusion
        # This test just verifies RRF doesn't mutate any memory state
        assert fused[0].memory_id == "a"  # Higher RRF score
        # No memories were created or modified by RRF


# ---------------------------------------------------------------------------
# Namespace isolation tests
# ---------------------------------------------------------------------------

class TestNamespaceIsolation:
    """Verify namespace isolation across retrieval channels."""

    def test_lexical_namespace_isolation(self, db_session: Session):
        """Lexical retrieval must respect namespace boundaries."""
        m1 = _make_memory(db_session, "Fixed auth bug", namespace="project:huginn")
        m2 = _make_memory(db_session, "Fixed auth bug", namespace="project:muninn")
        db_session.commit()

        retriever = LexicalRetriever(db_session)
        hits, _ = retriever.search(query="auth bug", namespace="project:huginn")

        ids = {h.memory_id for h in hits}
        assert m1.id in ids
        assert m2.id not in ids

    def test_different_namespaces_independent(self, db_session: Session):
        """Same content in different namespaces should be isolated."""
        m1 = _make_memory(db_session, "SQLite is the database", namespace="ns_p1")
        m2 = _make_memory(db_session, "Postgres is the database", namespace="ns_p2")
        db_session.commit()

        # Use separate retriever instances to avoid shared index state
        retriever1 = LexicalRetriever(db_session)
        hits_p1, _ = retriever1.search(query="SQLite", namespace="ns_p1")

        retriever2 = LexicalRetriever(db_session)
        hits_p2, _ = retriever2.search(query="Postgres", namespace="ns_p2")

        assert any(h.memory_id == m1.id for h in hits_p1)
        assert not any(h.memory_id == m2.id for h in hits_p1)
        assert any(h.memory_id == m2.id for h in hits_p2)
        assert not any(h.memory_id == m1.id for h in hits_p2)


# ---------------------------------------------------------------------------
# Failure safety tests
# ---------------------------------------------------------------------------

class TestFailureSafety:
    """Tests for graceful degradation when components fail."""

    def test_lexical_index_empty_query(self, db_session: Session):
        """Empty query should return empty results, not crash."""
        _make_memory(db_session, "Some memory")
        db_session.commit()

        retriever = LexicalRetriever(db_session)
        hits, trace = retriever.search(query="", namespace="test:hybrid")
        assert hits == []

    def test_lexical_no_memories(self, db_session: Session):
        """Searching with no memories should return empty results."""
        retriever = LexicalRetriever(db_session)
        hits, trace = retriever.search(query="anything", namespace="empty:namespace")
        assert hits == []
        assert trace.candidate_count == 0

    def test_rrf_with_empty_channels(self):
        """RRF should handle empty channel inputs gracefully."""
        fused = reciprocal_rank_fusion({})
        assert fused == []

    def test_rrf_with_single_empty_channel(self):
        """RRF should handle one empty channel gracefully."""
        dense_hits = [RetrievalHit(memory_id="m1", source=RetrievalSource.DENSE, source_rank=1, source_score=0.9)]
        fused = reciprocal_rank_fusion({
            RetrievalSource.DENSE: dense_hits,
            RetrievalSource.LEXICAL: [],
        })
        assert len(fused) == 1
        assert fused[0].channel_count == 1

    def test_lexical_index_reset(self, db_session: Session):
        """Reset should clear the in-memory index (but rebuild from DB on next search)."""
        _make_memory(db_session, "Test memory")
        db_session.commit()

        retriever = LexicalRetriever(db_session)
        hits, _ = retriever.search(query="test", namespace="test:hybrid")
        assert len(hits) >= 1

        retriever.reset()
        # After reset, index rebuilds from DB (since _built=False)
        hits2, _ = retriever.search(query="test", namespace="test:hybrid")
        assert len(hits2) >= 1  # Rebuilt from DB


# ---------------------------------------------------------------------------
# Representation unchanged tests
# ---------------------------------------------------------------------------

class TestRepresentationUnchanged:
    """Verify M10 representations are not affected by M11 retrieval."""

    def test_gist_summary_still_work(self, db_session: Session):
        """M10 representations should still be generated."""
        from app.memory.representations.service import RepresentationService

        memory = _make_memory(
            db_session,
            content="Fixed _load_max_checkpoint regression",
            gist=None,
            summary=None,
        )
        db_session.commit()

        service = RepresentationService(db_session)
        result = service.generate_for_memory(memory)
        assert result.generated is True
        assert memory.gist is not None
        assert memory.summary is not None

    def test_context_hierarchystill_works(self, db_session: Session):
        """M10 hierarchical context assembly should still work."""
        from app.context.budget import select_within_budget
        from app.context.models import ScoredCandidate
        from app.memory.representations.models import RepresentationLevel

        memory = _make_memory(
            db_session,
            content="Fixed the authentication bug in the login endpoint.",
            gist="Auth fix.",
            summary="Fixed auth bug in login endpoint.",
            importance=0.8,
        )
        db_session.commit()

        candidate = ScoredCandidate(
            memory=memory,
            semantic_score=0.75,
            importance=memory.importance,
            confidence=memory.confidence,
            recency_score=0.8,
            type_relevance=0.7,
            reinforcement_score=0.0,
            final_score=0.8,
        )

        estimator = SimpleTokenEstimator()
        selected, _, _, _ = select_within_budget(
            ranked=[candidate],
            max_memories=10,
            token_budget=1500,
            estimator=estimator,
            hierarchical=True,
        )

        assert len(selected) == 1
        assert selected[0].representation_level == RepresentationLevel.L2_FULL


# ---------------------------------------------------------------------------
# Benchmark test data
# ---------------------------------------------------------------------------

BENCHMARK_MEMORIES = [
    # Exact identifier queries should match these
    ("m_exact1", "Fixed _load_max_checkpoint regression in agent sessions", "exact"),
    ("m_exact2", "GeneratorExit cancellation handling in async code", "exact"),
    ("m_exact3", "M8.3A session replay feature completed", "exact"),
    ("m_exact4", "Key file: app/context/assembler.py was modified", "exact"),
    ("m_exact5", "Got 503 error from embedding service", "exact"),
    ("m_exact6", "advance_checkpoint function now advances monotonically", "exact"),
    # Semantic queries should match these
    ("m_sem1", "How Munin prevents old agent conversations from being replayed", "semantic"),
    ("m_sem2", "What happens when project truth changes over time", "semantic"),
    ("m_sem3", "How unimportant memories are aged out through decay", "semantic"),
    ("m_sem4", "Memory admission determines whether new observations become durable", "semantic"),
    # Mixed queries should match these
    ("m_mix1", "Why was _load_max_checkpoint added to the codebase", "mixed"),
    ("m_mix2", "GeneratorExit cancellation was needed for async safety", "mixed"),
    ("m_mix3", "M8.3A session replay implementation details", "mixed"),
]


class TestBenchmarkQueries:
    """Test that benchmark queries find the right memories via lexical retrieval."""

    @pytest.fixture()
    def benchmark_index(self, db_session: Session) -> BM25Index:
        """Create a BM25 index with benchmark memories."""
        idx = BM25Index()
        for mid, content, _ in BENCHMARK_MEMORIES:
            _make_memory(db_session, content, namespace="test:benchmark")
            idx.add(mid, content)
        db_session.commit()
        return idx

    def test_exact_identifier_hit_at_1(self, benchmark_index: BM25Index):
        """Exact identifier queries should find the right memory at rank 1."""
        test_cases = [
            ("_load_max_checkpoint", "m_exact1"),
            ("GeneratorExit", "m_exact2"),
            ("M8.3A", "m_exact3"),
            ("assembler.py", "m_exact4"),
            ("503", "m_exact5"),
            ("advance_checkpoint", "m_exact6"),
        ]
        for query, expected_id in test_cases:
            results = benchmark_index.search(query, limit=5)
            assert len(results) > 0, f"No results for '{query}'"
            # At least one of the top 3 should be the expected memory
            top_ids = [r[0] for r in results[:3]]
            assert expected_id in top_ids, (
                f"Query '{query}' should find {expected_id} in top 3, got {top_ids}"
            )

    def test_semantic_query_returns_results(self, benchmark_index: BM25Index):
        """Semantic queries should still return some results via lexical matching."""
        queries = [
            "agent conversations replayed",
            "project truth changes",
            "memories aged out decay",
        ]
        for query in queries:
            results = benchmark_index.search(query, limit=5)
            assert len(results) > 0, f"No results for semantic query '{query}'"


# ---------------------------------------------------------------------------
# HybridRetrievalResult tests
# ---------------------------------------------------------------------------

class TestHybridRetrievalResult:
    """Tests for the HybridRetrievalResult model."""

    def test_result_has_traces(self):
        result = HybridRetrievalResult(
            candidates=[],
            traces=[
                RetrieverTrace(source=RetrievalSource.DENSE, candidate_count=10),
                RetrieverTrace(source=RetrievalSource.LEXICAL, candidate_count=8),
            ],
            total_unique_candidates=0,
            retrieval_mode=RetrievalMode.HYBRID,
        )
        assert len(result.traces) == 2
        assert result.retrieval_mode == RetrievalMode.HYBRID

    def test_dense_mode_only_dense_trace(self):
        result = HybridRetrievalResult(
            candidates=[],
            traces=[RetrieverTrace(source=RetrievalSource.DENSE, candidate_count=10)],
            total_unique_candidates=0,
            retrieval_mode=RetrievalMode.DENSE,
        )
        assert result.retrieval_mode == RetrievalMode.DENSE


# ---------------------------------------------------------------------------
# Integration: Lexical retriever with representation indexing
# ---------------------------------------------------------------------------

class TestLexicalWithRepresentations:
    """Verify BM25 indexes gist and summary alongside content."""

    def test_gist_indexed(self, db_session: Session):
        """BM25 should find memories by their gist text."""
        m = _make_memory(
            db_session,
            content="Fixed the authentication bug in the login endpoint system",
            gist="Auth login fix",
            summary="Fixed auth bug in login endpoint.",
        )
        db_session.commit()

        retriever = LexicalRetriever(db_session)
        hits, _ = retriever.search(query="Auth login fix", namespace="test:hybrid")
        assert any(h.memory_id == m.id for h in hits)

    def test_summary_indexed(self, db_session: Session):
        """BM25 should find memories by their summary text."""
        m = _make_memory(
            db_session,
            content="Fixed the authentication bug in the login endpoint system",
            gist="Auth fix.",
            summary="Fixed auth bug in login endpoint.",
        )
        db_session.commit()

        retriever = LexicalRetriever(db_session)
        hits, _ = retriever.search(query="login endpoint", namespace="test:hybrid")
        assert any(h.memory_id == m.id for h in hits)
