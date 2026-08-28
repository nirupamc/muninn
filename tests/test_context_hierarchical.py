"""M10 — Hierarchical context assembly tests.

Tests proving that hierarchical representation selection works correctly
and actually saves tokens compared to flat L2-only assembly.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.context.budget import format_memory_line, select_within_budget
from app.context.models import (
    ContextConfig,
    ScoredCandidate,
    SelectedMemory,
)
from app.context.tokenization.simple import SimpleTokenEstimator
from app.memory.representations.models import (
    ContextState,
    RepresentationLevel,
)
from app.memory.representations.service import RepresentationService
from app.models.memory import Memory, MemoryStatus, MemoryType


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


def _make_memory(
    db_session: Session,
    content: str,
    gist: str | None = None,
    summary: str | None = None,
    namespace: str = "test:hierarchical",
    importance: float = 0.5,
    memory_type: MemoryType = MemoryType.fact,
) -> Memory:
    """Create a test memory with optional representations."""
    memory = Memory(
        namespace=namespace,
        content=content,
        gist=gist,
        summary=summary,
        memory_type=memory_type,
        importance=importance,
        confidence=0.9,
        status=MemoryStatus.active,
    )
    db_session.add(memory)
    db_session.flush()
    return memory


def _make_candidate(memory: Memory, final_score: float = 0.8) -> ScoredCandidate:
    """Create a ScoredCandidate wrapping a Memory."""
    return ScoredCandidate(
        memory=memory,
        semantic_score=0.75,
        importance=memory.importance,
        confidence=memory.confidence,
        recency_score=0.8,
        type_relevance=0.7,
        reinforcement_score=0.0,
        final_score=final_score,
    )


# ---------------------------------------------------------------------------
# Budget selection tests
# ---------------------------------------------------------------------------


class TestSelectWithinBudgetFlat:
    """Tests for the original flat (L2-only) selection behavior."""

    def test_flat_uses_full_content(self, db_session: Session):
        """Flat mode should always use full L2 content."""
        memory = _make_memory(
            db_session,
            content="This is a detailed memory about the authentication system.",
            gist="Auth fix.",
            summary="Fixed auth system.",
        )
        candidate = _make_candidate(memory)
        estimator = SimpleTokenEstimator()

        selected, used_tokens, truncated, skipped = select_within_budget(
            ranked=[candidate],
            max_memories=10,
            token_budget=1500,
            estimator=estimator,
            hierarchical=False,
        )

        assert len(selected) == 1
        assert selected[0].content == "This is a detailed memory about the authentication system."
        assert selected[0].representation_level == RepresentationLevel.L2_FULL

    def test_flat_respects_token_budget(self, db_session: Session):
        """Flat mode should skip memories that don't fit."""
        memory = _make_memory(
            db_session,
            content="This is a very long memory content. " * 50,
            importance=0.5,
        )
        candidate = _make_candidate(memory)
        estimator = SimpleTokenEstimator()

        # Very tight budget
        selected, used_tokens, truncated, skipped = select_within_budget(
            ranked=[candidate],
            max_memories=10,
            token_budget=10,
            estimator=estimator,
            hierarchical=False,
        )

        assert len(selected) == 0
        assert truncated is True


class TestSelectWithinBudgetHierarchical:
    """Tests for M10 hierarchical representation selection."""

    def test_hierarchical_uses_l2_with_sufficient_budget(self, db_session: Session):
        """With enough budget, should use L2 full content."""
        memory = _make_memory(
            db_session,
            content="Fixed the authentication bug in the login endpoint.",
            gist="Auth fix.",
            summary="Fixed auth bug in login endpoint.",
            importance=0.8,
        )
        candidate = _make_candidate(memory)
        estimator = SimpleTokenEstimator()

        selected, used_tokens, truncated, skipped = select_within_budget(
            ranked=[candidate],
            max_memories=10,
            token_budget=1500,
            estimator=estimator,
            hierarchical=True,
        )

        assert len(selected) == 1
        assert selected[0].representation_level == RepresentationLevel.L2_FULL

    def test_hierarchical_downgrades_to_l0_when_tight(self, db_session: Session):
        """With tight budget and low importance, should downgrade to L0."""
        # Create a long content memory with low importance
        long_content = "Detailed memory about the bug fix. " * 30
        memory = _make_memory(
            db_session,
            content=long_content,
            gist="Fixed bug.",
            summary="Fixed detailed bug in auth module.",
            importance=0.3,
        )
        candidate = _make_candidate(memory)
        estimator = SimpleTokenEstimator()

        # Very tight budget — less than 3x the L2 cost
        l2_tokens = estimator.count(f"- {long_content}")
        tight_budget = l2_tokens * 2  # Less than 3x

        selected, used_tokens, truncated, skipped = select_within_budget(
            ranked=[candidate],
            max_memories=10,
            token_budget=tight_budget,
            estimator=estimator,
            hierarchical=True,
        )

        assert len(selected) == 1
        assert selected[0].representation_level == RepresentationLevel.L0_GIST
        assert "Fixed bug." in selected[0].content

    def test_hierarchical_falls_back_to_l2_without_representations(self, db_session: Session):
        """Memories without gist/summary should use L2."""
        memory = _make_memory(
            db_session,
            content="Old memory without representations.",
            gist=None,
            summary=None,
            importance=0.5,
        )
        candidate = _make_candidate(memory)
        estimator = SimpleTokenEstimator()

        selected, used_tokens, truncated, skipped = select_within_budget(
            ranked=[candidate],
            max_memories=10,
            token_budget=1500,
            estimator=estimator,
            hierarchical=True,
        )

        assert len(selected) == 1
        assert selected[0].representation_level == RepresentationLevel.L2_FULL

    def test_hierarchical_preserves_identifiers_in_l0(self, db_session: Session):
        """L0 gist should preserve critical identifiers."""
        memory = _make_memory(
            db_session,
            content="The _load_max_checkpoint function in app/capture/service.py failed.",
            gist="Fixed _load_max_checkpoint regression.",
            summary="The _load_max_checkpoint function failed in app/capture/service.py.",
            importance=0.3,
        )
        candidate = _make_candidate(memory)
        estimator = SimpleTokenEstimator()

        # Force tight budget to get L0
        l2_tokens = estimator.count(f"- {memory.content}")
        tight_budget = l2_tokens * 2

        selected, used_tokens, truncated, skipped = select_within_budget(
            ranked=[candidate],
            max_memories=10,
            token_budget=tight_budget,
            estimator=estimator,
            hierarchical=True,
        )

        assert len(selected) == 1
        assert "_load_max_checkpoint" in selected[0].content


# ---------------------------------------------------------------------------
# Token savings tests
# ---------------------------------------------------------------------------


class TestTokenSavings:
    """Prove that hierarchical representation actually saves context tokens."""

    def test_hierarchical_fits_more_memories(self, db_session: Session):
        """With hierarchical selection, more memories should fit in the same budget."""
        estimator = SimpleTokenEstimator()
        memories = []

        # Create 10 memories with long content but good gist/summary
        for i in range(10):
            content = f"Memory {i}: This is a detailed memory about topic {i}. " * 10
            gist = f"Topic {i} update."
            summary = f"Memory {i} about topic {i} with key details."
            memory = _make_memory(
                db_session,
                content=content,
                gist=gist,
                summary=summary,
                importance=0.5,
            )
            memories.append(memory)

        candidates = [_make_candidate(m, final_score=0.8 - i * 0.05) for i, m in enumerate(memories)]

        # Fixed budget
        budget = 500

        # Flat mode
        selected_flat, tokens_flat, _, _ = select_within_budget(
            ranked=candidates,
            max_memories=20,
            token_budget=budget,
            estimator=estimator,
            hierarchical=False,
        )

        # Hierarchical mode
        selected_hier, tokens_hier, _, _ = select_within_budget(
            ranked=candidates,
            max_memories=20,
            token_budget=budget,
            estimator=estimator,
            hierarchical=True,
        )

        # Hierarchical should fit at least as many (usually more) memories
        assert len(selected_hier) >= len(selected_flat), (
            f"Hierarchical ({len(selected_hier)}) should fit >= flat ({len(selected_flat)})"
        )

        # Hierarchical should use less or equal tokens
        assert tokens_hier <= tokens_flat + 10, (
            f"Hierarchical tokens ({tokens_hier}) should be <= flat ({tokens_flat})"
        )

    def test_hierarchical_token_count_is_accurate(self, db_session: Session):
        """The estimated_tokens should match the actual content length."""
        memory = _make_memory(
            db_session,
            content="Fixed the bug in auth module.",
            gist="Auth fix.",
            summary="Fixed auth bug.",
            importance=0.5,
        )
        candidate = _make_candidate(memory)
        estimator = SimpleTokenEstimator()

        selected, used_tokens, _, _ = select_within_budget(
            ranked=[candidate],
            max_memories=10,
            token_budget=1500,
            estimator=estimator,
            hierarchical=True,
        )

        assert len(selected) == 1
        # Verify token count matches estimator
        expected_tokens = estimator.count(f"- {selected[0].content}")
        assert selected[0].estimated_tokens == expected_tokens


# ---------------------------------------------------------------------------
# Trace tests
# ---------------------------------------------------------------------------


class TestRepresentationTrace:
    """Tests for representation selection trace recording."""

    def test_trace_records_level(self, db_session: Session):
        """Trace should record which level was selected."""
        from app.context.models import RepresentationTraceEntry

        entry = RepresentationTraceEntry(
            memory_id="test-id",
            selected_level=RepresentationLevel.L1_SUMMARY,
            available_levels=[RepresentationLevel.L1_SUMMARY, RepresentationLevel.L2_FULL],
            token_cost=25,
            importance=0.5,
            final_rank=1,
            selection_reason="tight_budget",
        )

        assert entry.selected_level == RepresentationLevel.L1_SUMMARY
        assert entry.selection_reason == "tight_budget"
        assert entry.token_cost == 25

    def test_trace_available_levels_listed(self, db_session: Session):
        """Trace should list available levels."""
        from app.context.models import RepresentationTraceEntry

        entry = RepresentationTraceEntry(
            memory_id="test-id",
            selected_level=RepresentationLevel.L0_GIST,
            available_levels=[
                RepresentationLevel.L0_GIST,
                RepresentationLevel.L1_SUMMARY,
                RepresentationLevel.L2_FULL,
            ],
            token_cost=10,
            importance=0.3,
            final_rank=1,
            selection_reason="tight_budget_low_importance",
        )

        assert len(entry.available_levels) == 3
        assert RepresentationLevel.L0_GIST in entry.available_levels
        assert RepresentationLevel.L2_FULL in entry.available_levels


# ---------------------------------------------------------------------------
# API schema tests
# ---------------------------------------------------------------------------


class TestAPISchemaRepresentation:
    """Tests for representation info in API schemas."""

    def test_memory_read_includes_gist_summary(self, db_session: Session):
        """MemoryRead schema should include gist and summary."""
        from app.schemas.memory import MemoryRead

        memory = _make_memory(
            db_session,
            content="Fixed the bug.",
            gist="Bug fix.",
            summary="Fixed the auth bug.",
        )
        db_session.commit()

        mem_read = MemoryRead.model_validate(memory)
        assert mem_read.gist == "Bug fix."
        assert mem_read.summary == "Fixed the auth bug."
        assert mem_read.content == "Fixed the bug."

    def test_memory_read_null_representations(self, db_session: Session):
        """MemoryRead should handle NULL gist/summary."""
        from app.schemas.memory import MemoryRead

        memory = _make_memory(
            db_session,
            content="Old memory.",
            gist=None,
            summary=None,
        )
        db_session.commit()

        mem_read = MemoryRead.model_validate(memory)
        assert mem_read.gist is None
        assert mem_read.summary is None

    def test_context_response_includes_representation_info(self):
        """ContextResponse MemoryUsed should include representation level."""
        from app.schemas.context import MemoryUsed

        mem_used = MemoryUsed(
            memory_id="test-id",
            memory_type=MemoryType.fact,
            content="Fixed the bug.",
            semantic_score=0.8,
            importance=0.7,
            confidence=0.9,
            recency_score=0.85,
            type_relevance=0.7,
            reinforcement_score=0.0,
            final_score=0.75,
            estimated_tokens=10,
            representation_level="L1",
            selection_reason="tight_budget",
        )

        assert mem_used.representation_level == "L1"
        assert mem_used.selection_reason == "tight_budget"
