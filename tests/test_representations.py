"""M10 — Hierarchical memory representation tests.

Tests for representation generation, selection, and backfill.
"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.memory.representations.models import (
    L0_MAX_CHARS,
    L1_MAX_CHARS,
    ContextState,
    RepresentationLevel,
    RepresentationSelection,
)
from app.memory.representations.providers import (
    _build_gist,
    _build_summary,
    _extract_first_sentence,
    _truncate_at_word,
    generate_representations,
)
from app.memory.representations.service import RepresentationService
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.services.memory_service import MemoryService


# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sample_memories(db_session: Session) -> list[Memory]:
    """Create representative memory fixtures for testing."""
    memories = []
    contents = [
        # 1. Short decision
        ("Use FastAPI for the REST API instead of Flask.", MemoryType.decision, 0.8),
        # 2. Long bug investigation
        (
            "Fixed agent-session checkpoint regression. AgentSessionService could regress "
            "its checkpoint when older sessions were processed after newer ones. The root cause "
            "was in _load_max_checkpoint which did not advance monotonically. Checkpoints now "
            "advance monotonically and repeated polls do not replay events.",
            MemoryType.fact,
            0.9,
        ),
        # 3. Verified test result
        ("All 154 backend tests passing. Admission: 28/28, Dedup: 32/32, Temporal: 35/35.", MemoryType.event, 0.7),
        # 4. Architecture decision
        (
            "Project structure follows domain-driven layout: app/admission, app/deduplication, "
            "app/temporal, app/context as separate modules.",
            MemoryType.decision,
            0.85,
        ),
        # 5. Blocker
        ("BLOCKED: Alembic migration fails on PostgreSQL due to batch_alter_table incompatibility.", MemoryType.event, 0.95),
        # 6. Temporal update
        (
            "Updated the decay lambda for ephemeral events from 0.15 to 0.20 based on "
            "measured half-life analysis.",
            MemoryType.event,
            0.6,
        ),
        # 7. Contradiction/supersession
        (
            "Previously used SQLite WAL mode. Now switched to journal_mode=DELETE for "
            "better cross-process compatibility.",
            MemoryType.decision,
            0.75,
        ),
        # 8. Memory containing code identifiers
        (
            "The _load_max_checkpoint function in app/capture/agent_sessions/service.py "
            "was the root cause of the regression.",
            MemoryType.fact,
            0.85,
        ),
        # 9. Memory with path/file names
        (
            "Key files: app/context/assembler.py, app/context/budget.py, "
            "app/services/memory_service.py were modified in M5.",
            MemoryType.fact,
            0.65,
        ),
        # 10. Very short memory
        ("Tests pass.", MemoryType.event, 0.3),
    ]

    for content, mtype, importance in contents:
        memory = Memory(
            namespace="test:representations",
            content=content,
            memory_type=mtype,
            importance=importance,
            confidence=0.9,
            status=MemoryStatus.active,
        )
        db_session.add(memory)
        db_session.flush()
        memories.append(memory)

    db_session.commit()
    return memories


# ---------------------------------------------------------------------------
# Provider tests
# ---------------------------------------------------------------------------


class TestExtractFirstSentence:
    """Tests for _extract_first_sentence helper."""

    def test_simple_sentence(self):
        assert _extract_first_sentence("Fixed the bug.") == "Fixed the bug."

    def test_label_prefix_stripped(self):
        result = _extract_first_sentence("Agent session summary:\nImplemented auth.")
        assert "Agent session summary" not in result
        assert "Implemented auth" in result

    def test_empty_content(self):
        assert _extract_first_sentence("") == ""

    def test_whitespace_only(self):
        assert _extract_first_sentence("   ") == ""

    def test_multiline_content(self):
        result = _extract_first_sentence("First important fact.\nSecond line.")
        assert result.startswith("First important fact")

    def test_code_identifiers_preserved(self):
        content = "The _load_max_checkpoint function failed."
        result = _extract_first_sentence(content)
        assert "_load_max_checkpoint" in result


class TestTruncateAtWord:
    """Tests for _truncate_at_word helper."""

    def test_no_truncation_needed(self):
        assert _truncate_at_word("short", 100) == "short"

    def test_truncates_at_word_boundary(self):
        result = _truncate_at_word("this is a long sentence with many words", 20)
        assert len(result) <= 20
        assert not result.endswith(" ")

    def test_exact_boundary(self):
        result = _truncate_at_word("exactly twenty chars", 20)
        assert result == "exactly twenty chars"


class TestBuildGist:
    """Tests for L0 gist generation."""

    def test_simple_gist(self):
        gist = _build_gist("Fixed the checkpoint regression.")
        assert gist is not None
        assert len(gist) <= L0_MAX_CHARS
        assert "checkpoint" in gist.lower() or "fixed" in gist.lower()

    def test_gist_preserves_identifiers(self):
        gist = _build_gist("Fixed _load_max_checkpoint regression.")
        assert "_load_max_checkpoint" in gist

    def test_gist_empty_content(self):
        assert _build_gist("") is None

    def test_gist_bounded(self):
        long_content = "This is a very long sentence. " * 50
        gist = _build_gist(long_content)
        assert gist is not None
        assert len(gist) <= L0_MAX_CHARS

    def test_gist_from_multiline(self):
        content = "Agent session summary:\nFixed auth bug in login endpoint."
        gist = _build_gist(content)
        assert gist is not None
        assert "Agent session summary" not in gist


class TestBuildSummary:
    """Tests for L1 summary generation."""

    def test_simple_summary(self):
        summary = _build_summary("Fixed the bug in auth module.")
        assert summary is not None
        assert len(summary) <= L1_MAX_CHARS

    def test_summary_preserves_identifiers(self):
        summary = _build_summary("The _load_max_checkpoint function failed.")
        assert "_load_max_checkpoint" in summary

    def test_summary_empty_content(self):
        assert _build_summary("") is None

    def test_summary_bounded(self):
        long_content = "This is important. " * 100
        summary = _build_summary(long_content)
        assert summary is not None
        assert len(summary) <= L1_MAX_CHARS

    def test_summary_preserves_key_clauses(self):
        content = (
            "Agent session summary:\n"
            "Fixed agent-session checkpoint regression.\n"
            "AgentSessionService could regress its checkpoint.\n"
            "Checkpoints now advance monotonically."
        )
        summary = _build_summary(content)
        assert summary is not None
        assert "AgentSessionService" in summary or "checkpoint" in summary.lower()


class TestGenerateRepresentations:
    """Tests for the full representation generation."""

    def test_basic_generation(self):
        result = generate_representations("Fixed the checkpoint regression.")
        assert result.generated is True
        assert result.gist is not None
        assert result.summary is not None
        assert result.provider == "deterministic"

    def test_empty_content_returns_not_generated(self):
        result = generate_representations("")
        assert result.generated is False
        assert result.gist is None
        assert result.summary is None

    def test_whitespace_content_returns_not_generated(self):
        result = generate_representations("   ")
        assert result.generated is False

    def test_identifiers_preserved_in_both_levels(self):
        content = "The _load_max_checkpoint function in app/capture/service.py failed."
        result = generate_representations(content)
        assert result.generated is True
        assert "_load_max_checkpoint" in result.gist or "_load_max_checkpoint" in result.summary
        assert "app/capture/service.py" in result.gist or "app/capture/service.py" in result.summary


# ---------------------------------------------------------------------------
# Service tests
# ---------------------------------------------------------------------------


class TestRepresentationService:
    """Tests for RepresentationService."""

    def test_generate_for_memory(self, db_session: Session, sample_memories):
        service = RepresentationService(db_session)
        memory = sample_memories[0]
        result = service.generate_for_memory(memory)
        assert result.generated is True
        assert memory.gist is not None
        assert memory.summary is not None

    def test_generate_is_deterministic(self, db_session: Session, sample_memories):
        service = RepresentationService(db_session)
        memory = sample_memories[1]
        result1 = service.generate_for_memory(memory)
        gist1 = memory.gist
        summary1 = memory.summary
        # Re-generate should produce same result
        result2 = service.generate_for_memory(memory)
        assert memory.gist == gist1
        assert memory.summary == summary1

    def test_generate_for_empty_memory(self, db_session: Session):
        service = RepresentationService(db_session)
        memory = Memory(
            namespace="test",
            content="",
            memory_type=MemoryType.other,
            importance=0.5,
            confidence=1.0,
            status=MemoryStatus.active,
        )
        db_session.add(memory)
        db_session.flush()
        result = service.generate_for_memory(memory)
        assert result.generated is False
        assert memory.gist is None
        assert memory.summary is None

    def test_l2_content_unchanged(self, db_session: Session, sample_memories):
        service = RepresentationService(db_session)
        memory = sample_memories[1]
        original_content = memory.content
        service.generate_for_memory(memory)
        assert memory.content == original_content

    def test_all_sample_memories_get_representations(self, db_session: Session, sample_memories):
        service = RepresentationService(db_session)
        for memory in sample_memories:
            result = service.generate_for_memory(memory)
            assert result.generated is True, f"Failed for: {memory.content[:50]}"
            assert memory.gist is not None
            assert memory.summary is not None


# ---------------------------------------------------------------------------
# Selection tests
# ---------------------------------------------------------------------------


class TestRepresentationSelection:
    """Tests for representation selection logic."""

    def _make_memory(self, content: str, gist: str | None = None, summary: str | None = None,
                     importance: float = 0.5) -> Memory:
        """Create a test Memory object (detached from session)."""
        return Memory(
            namespace="test",
            content=content,
            gist=gist,
            summary=summary,
            memory_type=MemoryType.fact,
            importance=importance,
            confidence=0.9,
            status=MemoryStatus.active,
        )

    def _make_context_state(self, remaining_budget: int = 1000,
                            token_budget: int = 1500) -> ContextState:
        return ContextState(
            token_budget=token_budget,
            remaining_budget=remaining_budget,
            memories_selected=0,
            max_memories=20,
            query="test query",
        )

    def test_l2_selected_with_sufficient_budget(self):
        memory = self._make_memory(
            "Fixed the bug.",
            gist="Fixed bug.",
            summary="Fixed the bug in auth module.",
            importance=0.8,
        )
        state = self._make_context_state(remaining_budget=1000)
        selection = RepresentationService.select_representation(memory, state)
        assert selection.level == RepresentationLevel.L2_FULL

    def test_l0_selected_with_tight_budget_low_importance(self):
        long_content = "This is a very detailed memory about the bug fix. " * 20
        memory = self._make_memory(
            long_content,
            gist="Fixed bug.",
            summary="Fixed the bug in auth module.",
            importance=0.3,  # Low importance
        )
        # Tight budget: less than 3x the L2 cost
        state = self._make_context_state(remaining_budget=50, token_budget=1500)
        selection = RepresentationService.select_representation(memory, state)
        assert selection.level == RepresentationLevel.L0_GIST
        assert "Fixed bug." in selection.text

    def test_l1_selected_with_medium_budget(self):
        long_content = "This is a detailed memory about the authentication system. " * 10
        memory = self._make_memory(
            long_content,
            gist="Auth system bug.",
            summary="Fixed authentication system bug.",
            importance=0.4,  # Medium importance
        )
        state = self._make_context_state(remaining_budget=100, token_budget=1500)
        selection = RepresentationService.select_representation(memory, state)
        # With medium budget and medium importance, should use L1
        assert selection.level in (RepresentationLevel.L1_SUMMARY, RepresentationLevel.L0_GIST)

    def test_no_gist_falls_back_to_l2(self):
        memory = self._make_memory("Fixed the bug.", gist=None, summary=None)
        state = self._make_context_state(remaining_budget=1000)
        selection = RepresentationService.select_representation(memory, state)
        assert selection.level == RepresentationLevel.L2_FULL

    def test_no_summary_falls_back_to_l2(self):
        memory = self._make_memory("Fixed the bug.", gist="Fixed.", summary=None)
        state = self._make_context_state(remaining_budget=1000)
        selection = RepresentationService.select_representation(memory, state)
        assert selection.level == RepresentationLevel.L2_FULL

    def test_selection_result_has_token_cost(self):
        memory = self._make_memory(
            "Fixed the bug.",
            gist="Fixed.",
            summary="Fixed bug.",
        )
        state = self._make_context_state(remaining_budget=1000)
        selection = RepresentationService.select_representation(memory, state)
        assert selection.token_cost > 0

    def test_selection_has_reason(self):
        memory = self._make_memory(
            "Fixed the bug.",
            gist="Fixed.",
            summary="Fixed bug.",
        )
        state = self._make_context_state(remaining_budget=1000)
        selection = RepresentationService.select_representation(memory, state)
        assert selection.selection_reason is not None
        assert len(selection.selection_reason) > 0


# ---------------------------------------------------------------------------
# Backfill tests
# ---------------------------------------------------------------------------


class TestBackfill:
    """Tests for backfill functionality."""

    def test_backfill_populates_empty_memories(self, db_session: Session, sample_memories):
        service = RepresentationService(db_session)
        stats = service.backfill(batch_size=5)
        assert stats["scanned"] == len(sample_memories)
        assert stats["updated"] == len(sample_memories)
        assert stats["failed"] == 0

    def test_backfill_is_idempotent(self, db_session: Session, sample_memories):
        service = RepresentationService(db_session)
        # First backfill
        stats1 = service.backfill(batch_size=5)
        # Second backfill should skip
        stats2 = service.backfill(batch_size=5)
        assert stats2["skipped"] == len(sample_memories)
        assert stats2["updated"] == 0

    def test_backfill_dry_run_does_not_modify(self, db_session: Session, sample_memories):
        service = RepresentationService(db_session)
        stats = service.backfill(batch_size=5, dry_run=True)
        assert stats["updated"] == len(sample_memories)
        # Verify memories were NOT actually modified
        db_session.expire_all()
        for memory in sample_memories:
            refreshed = db_session.get(Memory, memory.id)
            assert refreshed.gist is None
            assert refreshed.summary is None

    def test_backfill_with_force_regenerates(self, db_session: Session, sample_memories):
        service = RepresentationService(db_session)
        # First backfill
        service.backfill(batch_size=5)
        # Force re-backfill
        stats = service.backfill(batch_size=5, skip_existing=False)
        assert stats["updated"] == len(sample_memories)
        assert stats["skipped"] == 0

    def test_backfill_does_not_duplicate_memories(self, db_session: Session, sample_memories):
        initial_count = db_session.query(Memory).count()
        service = RepresentationService(db_session)
        service.backfill(batch_size=5)
        final_count = db_session.query(Memory).count()
        assert final_count == initial_count


# ---------------------------------------------------------------------------
# Backward compatibility tests
# ---------------------------------------------------------------------------


class TestBackwardCompatibility:
    """Tests for backward compatibility with NULL gist/summary rows."""

    def test_memory_without_representations_is_valid(self, db_session: Session):
        """Existing memories with NULL gist/summary should work."""
        memory = Memory(
            namespace="test:compat",
            content="Old memory without representations.",
            memory_type=MemoryType.fact,
            importance=0.5,
            confidence=0.9,
            status=MemoryStatus.active,
        )
        db_session.add(memory)
        db_session.commit()

        # Should be retrievable
        fetched = db_session.get(Memory, memory.id)
        assert fetched is not None
        assert fetched.content == "Old memory without representations."
        assert fetched.gist is None
        assert fetched.summary is None

    def test_l2_fallback_when_no_representations(self, db_session: Session):
        """Context should fall back to L2 when no representations exist."""
        from app.context.tokenization.simple import SimpleTokenEstimator

        memory = Memory(
            namespace="test:compat",
            content="Old memory without representations.",
            gist=None,
            summary=None,
            memory_type=MemoryType.fact,
            importance=0.5,
            confidence=0.9,
            status=MemoryStatus.active,
        )
        db_session.add(memory)
        db_session.commit()

        state = ContextState(
            token_budget=1500,
            remaining_budget=1000,
            memories_selected=0,
            max_memories=20,
            query="test",
        )
        estimator = SimpleTokenEstimator()
        selection = RepresentationService.select_representation(memory, state, estimator)
        assert selection.level == RepresentationLevel.L2_FULL
        assert "Old memory" in selection.text


# ---------------------------------------------------------------------------
# Failure safety tests
# ---------------------------------------------------------------------------


class TestFailureSafety:
    """Tests that representation failures don't lose memory."""

    def test_empty_content_generation_does_not_crash(self):
        result = generate_representations("")
        assert result.generated is False
        assert result.gist is None

    def test_whitespace_content_generation_does_not_crash(self):
        result = generate_representations("   \n  \n  ")
        assert result.generated is False

    def test_very_long_content_generation_does_not_crash(self):
        content = "x" * 1_000_000
        result = generate_representations(content)
        assert result.generated is True
        assert result.gist is not None
        assert len(result.gist) <= L0_MAX_CHARS

    def test_special_characters_content_generation_does_not_crash(self):
        content = "Keys: <ctrl>+<alt>+<del>, @#$%^&*(), 你好世界"
        result = generate_representations(content)
        assert result.generated is True


# ---------------------------------------------------------------------------
# Semantic invariant tests
# ---------------------------------------------------------------------------


class TestSemanticInvariants:
    """Verify L0/L1 are representations, NOT separate memories."""

    def test_representations_are_not_memories(self, db_session: Session):
        """Generating representations should not create new Memory rows."""
        memory = Memory(
            namespace="test:invariants",
            content="Fixed the bug.",
            memory_type=MemoryType.fact,
            importance=0.5,
            confidence=0.9,
            status=MemoryStatus.active,
        )
        db_session.add(memory)
        db_session.commit()

        initial_count = db_session.query(Memory).filter(
            Memory.namespace == "test:invariants"
        ).count()

        service = RepresentationService(db_session)
        service.generate_for_memory(memory)
        db_session.commit()

        final_count = db_session.query(Memory).filter(
            Memory.namespace == "test:invariants"
        ).count()
        assert final_count == initial_count

    def test_representations_are_attributes_not_separate(self, db_session: Session):
        """Gist and summary are attributes of the same Memory row."""
        memory = Memory(
            namespace="test:invariants",
            content="Fixed the bug in auth module.",
            memory_type=MemoryType.fact,
            importance=0.5,
            confidence=0.9,
            status=MemoryStatus.active,
        )
        db_session.add(memory)
        db_session.commit()

        service = RepresentationService(db_session)
        service.generate_for_memory(memory)
        db_session.commit()

        # Same memory ID has both gist and summary
        fetched = db_session.get(Memory, memory.id)
        assert fetched.gist is not None
        assert fetched.summary is not None
        assert fetched.id == memory.id
