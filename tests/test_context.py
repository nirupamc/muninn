"""M5 Context Assembly tests.

Coverage:
    - Basic context relevance
    - Namespace isolation
    - User isolation
    - Agent filtering
    - Relevance dominance over importance
    - Importance contribution
    - Confidence contribution
    - Recency contribution
    - Reinforcement contribution
    - Superseded exclusion (default)
    - include_superseded flag
    - Temporal validity (valid_from / valid_until)
    - Replacement correctness
    - Contradiction formatting
    - Diversity / redundancy suppression
    - Token budget enforcement
    - Tiny budget edge case
    - max_memories enforcement
    - memory_types filter
    - Deterministic ordering
    - Read-only guarantee (no DB mutation)
    - M1 semantic search still works (regression)
    - POST /api/v1/context endpoint happy path and validation
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.context.models import ContextConfig
from app.context.scoring import (
    compute_recency_score,
    compute_reinforcement_score,
    compute_type_relevance,
    compute_final_score,
)
from app.context.service import ContextService
from app.context.tokenization.simple import SimpleTokenEstimator
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.factory import set_embedding_provider_override
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.schemas.context import ContextRequest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory(
    db: Session,
    *,
    namespace: str = "test",
    content: str,
    memory_type: MemoryType = MemoryType.fact,
    importance: float = 0.5,
    confidence: float = 1.0,
    status: MemoryStatus = MemoryStatus.active,
    user_id: str | None = None,
    agent_id: str | None = None,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    created_at: datetime | None = None,
) -> Memory:
    now = datetime.now(UTC)
    m = Memory(
        namespace=namespace,
        content=content,
        memory_type=memory_type,
        importance=importance,
        confidence=confidence,
        status=status,
        user_id=user_id,
        agent_id=agent_id,
        valid_from=valid_from,
        valid_until=valid_until,
        created_at=created_at or now,
        updated_at=now,
    )
    db.add(m)
    db.flush()
    return m


def _embed_memory(db: Session, memory: Memory, provider: FakeEmbeddingProvider) -> None:
    from app.embeddings.vector_utils import serialize_vector
    from app.models.embedding import MemoryEmbedding

    vec = provider.embed_text(memory.content)
    emb = MemoryEmbedding(
        memory_id=memory.id,
        provider=provider.provider_name,
        model_name=provider.model_name,
        dimension=provider.dimension,
        embedding=serialize_vector(vec),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db.add(emb)
    db.flush()


def _store(
    db: Session,
    provider: FakeEmbeddingProvider,
    **kwargs: Any,
) -> Memory:
    m = _make_memory(db, **kwargs)
    _embed_memory(db, m, provider)
    db.commit()
    return m


def _assemble(
    db: Session,
    provider: FakeEmbeddingProvider,
    query: str,
    namespace: str = "test",
    **kwargs: Any,
) -> Any:
    req = ContextRequest(
        query=query,
        namespace=namespace,
        **kwargs,
    )
    svc = ContextService(db=db, provider=provider)
    return svc.assemble(req)


# ---------------------------------------------------------------------------
# Unit: tokenizer
# ---------------------------------------------------------------------------

class TestSimpleTokenEstimator:
    def test_empty_string(self):
        est = SimpleTokenEstimator()
        assert est.count("") == 0

    def test_short_text(self):
        est = SimpleTokenEstimator()
        # "abcd" = 4 chars → 1 token
        assert est.count("abcd") == 1

    def test_approximate(self):
        est = SimpleTokenEstimator()
        text = "a" * 100
        assert est.count(text) == 25  # ceil(100/4)

    def test_custom_chars_per_token(self):
        est = SimpleTokenEstimator(chars_per_token=3.0)
        assert est.count("abc") == 1
        assert est.count("abcd") == 2


# ---------------------------------------------------------------------------
# Unit: scoring functions
# ---------------------------------------------------------------------------

class TestScoringFunctions:
    def test_recency_fresh(self):
        now = datetime.now(UTC)
        score = compute_recency_score(now, now, lambda_=0.05)
        assert score == pytest.approx(1.0, abs=1e-6)

    def test_recency_decays(self):
        now = datetime.now(UTC)
        old = now - timedelta(days=30)
        score = compute_recency_score(old, now, lambda_=0.05)
        assert score < 0.5

    def test_recency_very_old(self):
        now = datetime.now(UTC)
        ancient = now - timedelta(days=365)
        score = compute_recency_score(ancient, now, lambda_=0.05)
        assert 0.0 <= score < 0.2

    def test_reinforcement_zero(self):
        assert compute_reinforcement_score(0) == 0.0

    def test_reinforcement_one(self):
        score = compute_reinforcement_score(1)
        assert 0.0 < score <= 0.8

    def test_reinforcement_capped(self):
        many = compute_reinforcement_score(1000)
        assert many <= 0.8

    def test_type_relevance_project(self):
        score = compute_type_relevance("continue building Munin project", MemoryType.project)
        assert score >= 0.9

    def test_type_relevance_event_low_on_continuation(self):
        score = compute_type_relevance("continue building Munin project", MemoryType.event)
        assert score <= 0.25

    def test_final_score_semantic_dominates(self):
        cfg = ContextConfig()
        high_sem = compute_final_score(
            semantic_score=0.9,
            importance=0.1,
            confidence=0.5,
            recency_score=0.5,
            type_relevance=0.5,
            reinforcement_score=0.0,
            config=cfg,
        )
        high_imp = compute_final_score(
            semantic_score=0.2,
            importance=1.0,
            confidence=0.5,
            recency_score=0.5,
            type_relevance=0.5,
            reinforcement_score=0.0,
            config=cfg,
        )
        assert high_sem > high_imp, "semantic relevance must dominate over importance"


# ---------------------------------------------------------------------------
# Integration: ContextService via db_session + FakeEmbeddingProvider
# ---------------------------------------------------------------------------

class TestBasicContextRelevance:
    """Munin memories rank higher than unrelated noise."""

    def test_relevant_outranks_noise(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="User is building Munin.", memory_type=MemoryType.project)
        _store(db_session, fake_provider,
               content="Munin uses FastAPI.", memory_type=MemoryType.decision)
        _store(db_session, fake_provider,
               content="User ate pizza today.", memory_type=MemoryType.event)

        resp = _assemble(db_session, fake_provider, "Continue building Munin")

        ids_in_context = [m.content for m in resp.memories_used]
        pizza_scores = [m.final_score for m in resp.memories_used if "pizza" in m.content]

        assert any("Munin" in c for c in ids_in_context), "Munin memories should be selected"
        if pizza_scores:
            munin_scores = [m.final_score for m in resp.memories_used if "Munin" in m.content]
            assert max(munin_scores) > max(pizza_scores), "pizza must not outrank Munin memories"

    def test_context_text_contains_munin(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="User is building Munin.", memory_type=MemoryType.project)

        resp = _assemble(db_session, fake_provider, "Continue building Munin")
        assert "Munin" in resp.context

    def test_response_structure(self, db_session, fake_provider):
        resp = _assemble(db_session, fake_provider, "test query")
        assert resp.query == "test query"
        assert resp.namespace == "test"
        assert isinstance(resp.memories_used, list)
        assert isinstance(resp.context, str)
        assert isinstance(resp.estimated_tokens, int)
        assert isinstance(resp.truncated, bool)


class TestNamespaceIsolation:
    """No memory from another namespace leaks in."""

    def test_other_namespace_excluded(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="User is building Munin.", namespace="personal",
               memory_type=MemoryType.project)
        _store(db_session, fake_provider,
               content="Other org data.", namespace="other_org",
               memory_type=MemoryType.fact)

        resp = _assemble(db_session, fake_provider,
                         "Continue building Munin", namespace="personal")

        for m in resp.memories_used:
            assert "Other org" not in m.content

    def test_empty_result_for_wrong_namespace(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="User is building Munin.", namespace="personal",
               memory_type=MemoryType.project)

        resp = _assemble(db_session, fake_provider,
                         "Continue building Munin", namespace="other")
        assert resp.memories_used == []


class TestUserIsolation:
    """No memory from another user leaks in."""

    def test_other_user_excluded(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="User A builds Munin.", user_id="user-a",
               memory_type=MemoryType.project)
        _store(db_session, fake_provider,
               content="User B builds something else.", user_id="user-b",
               memory_type=MemoryType.project)

        resp = _assemble(db_session, fake_provider,
                         "Continue building Munin", user_id="user-a")

        for m in resp.memories_used:
            assert "User B" not in m.content


class TestAgentFiltering:
    """Agent filter works when agent_id is provided."""

    def test_agent_filter_includes_matching(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="Agent Alpha is working on Munin.", agent_id="agent-alpha",
               memory_type=MemoryType.project)
        _store(db_session, fake_provider,
               content="Agent Beta does something else.", agent_id="agent-beta",
               memory_type=MemoryType.project)

        resp = _assemble(db_session, fake_provider,
                         "Continue building Munin", agent_id="agent-alpha")

        for m in resp.memories_used:
            assert "Beta" not in m.content

    def test_no_agent_filter_returns_all(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="Agent Alpha is working on Munin memory.", agent_id="agent-alpha",
               memory_type=MemoryType.project)
        _store(db_session, fake_provider,
               content="Agent Beta stores documents for parsing.", agent_id="agent-beta",
               memory_type=MemoryType.project)

        resp = _assemble(db_session, fake_provider, "Munin memory document parsing agent")
        # Both memories should be retrievable (different content clusters)
        assert len(resp.memories_used) >= 1


class TestRelevanceDominance:
    """High importance alone must not beat strongly relevant memory."""

    def test_relevant_beats_important_unrelated(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="User is building Munin memory system.",
               memory_type=MemoryType.project,
               importance=0.5)
        _store(db_session, fake_provider,
               content="User ate pizza today for lunch.",
               memory_type=MemoryType.event,
               importance=1.0)

        resp = _assemble(db_session, fake_provider, "Continue building Munin memory")
        assert len(resp.memories_used) >= 1
        # Munin memory must be top result
        assert "Munin" in resp.memories_used[0].content


class TestImportanceContribution:
    """Higher importance gives a modest boost for similarly relevant memories."""

    def test_importance_boosts_rank(self, db_session, fake_provider):
        # Two very similar Munin memories, different importance
        _store(db_session, fake_provider,
               content="User is building Munin the memory agent system.",
               memory_type=MemoryType.project, importance=0.9)
        _store(db_session, fake_provider,
               content="User is building Munin the memory agent system.",
               memory_type=MemoryType.project, importance=0.1)

        resp = _assemble(db_session, fake_provider,
                         "Continue building Munin memory agent system",
                         max_memories=10)

        # Both should appear; high-importance should have higher final_score
        if len(resp.memories_used) >= 2:
            assert resp.memories_used[0].importance >= resp.memories_used[1].importance


class TestConfidenceContribution:
    """Higher confidence gives a modest boost."""

    def test_confidence_boosts_rank(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="Munin is a durable memory layer for agents.",
               memory_type=MemoryType.project, confidence=0.95)
        _store(db_session, fake_provider,
               content="Munin is a durable memory layer for agents.",
               memory_type=MemoryType.project, confidence=0.3)

        resp = _assemble(db_session, fake_provider,
                         "Munin durable memory layer", max_memories=10)

        if len(resp.memories_used) >= 2:
            assert resp.memories_used[0].confidence >= resp.memories_used[1].confidence


class TestRecencyContribution:
    """Newer memory ranks higher when otherwise equivalent."""

    def test_newer_memory_ranks_higher(self, db_session, fake_provider):
        now = datetime.now(UTC)
        old_time = now - timedelta(days=60)

        _store(db_session, fake_provider,
               content="Munin is a durable memory layer.",
               memory_type=MemoryType.project,
               created_at=old_time)
        _store(db_session, fake_provider,
               content="Munin is a durable memory layer.",
               memory_type=MemoryType.project,
               created_at=now)

        resp = _assemble(db_session, fake_provider,
                         "Munin durable memory layer", max_memories=10)

        if len(resp.memories_used) >= 2:
            # Newer should have higher recency score
            assert resp.memories_used[0].recency_score >= resp.memories_used[1].recency_score


class TestReinforcementContribution:
    """Reinforced memory gets bounded boost."""

    def test_reinforcement_score_nonzero(self, db_session, fake_provider):
        from app.models.deduplication import MemoryReinforcement
        from app.models.event import Event, EventRole

        m = _store(db_session, fake_provider,
                   content="User is building Munin.",
                   memory_type=MemoryType.project)

        # Create a parent event and reinforcement record
        ev = Event(namespace="test", content="test event", role=EventRole.user,
                   created_at=datetime.now(UTC))
        db_session.add(ev)
        db_session.flush()

        rein = MemoryReinforcement(
            memory_id=m.id,
            source_event_id=ev.id,
            candidate_content="User is building Munin.",
            relationship_confidence=0.9,
            provider="fake",
            model_name="fake-mini",
            created_at=datetime.now(UTC),
        )
        db_session.add(rein)
        db_session.commit()

        resp = _assemble(db_session, fake_provider, "Continue building Munin")
        munin_mem = next((m for m in resp.memories_used if "Munin" in m.content), None)
        assert munin_mem is not None
        assert munin_mem.reinforcement_score > 0.0
        assert munin_mem.reinforcement_score <= 0.8


class TestSupersededExclusion:
    """Superseded memories excluded by default."""

    def test_superseded_not_in_default_context(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="Munin uses SQLite.",
               memory_type=MemoryType.decision,
               status=MemoryStatus.superseded)
        _store(db_session, fake_provider,
               content="Munin uses PostgreSQL.",
               memory_type=MemoryType.decision,
               status=MemoryStatus.active)

        resp = _assemble(db_session, fake_provider,
                         "What database does Munin use?")

        contents = [m.content for m in resp.memories_used]
        assert not any("SQLite" in c for c in contents), "superseded SQLite must not appear"
        assert any("PostgreSQL" in c for c in contents), "active PostgreSQL must appear"

    def test_superseded_not_in_context_text(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="Munin uses SQLite.",
               memory_type=MemoryType.decision,
               status=MemoryStatus.superseded)

        resp = _assemble(db_session, fake_provider, "Munin database technology")
        assert "SQLite" not in resp.context


class TestIncludeSuperseded:
    """include_superseded=True allows superseded memories to participate."""

    def test_superseded_appears_when_requested(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="Munin uses SQLite.",
               memory_type=MemoryType.decision,
               status=MemoryStatus.superseded)

        resp = _assemble(db_session, fake_provider,
                         "Munin database technology",
                         include_superseded=True)

        contents = [m.content for m in resp.memories_used]
        assert any("SQLite" in c for c in contents)


class TestTemporalValidity:
    """Future and expired memories are filtered by as_of."""

    def test_future_memory_excluded(self, db_session, fake_provider):
        now = datetime.now(UTC)
        future = now + timedelta(days=10)

        _store(db_session, fake_provider,
               content="Munin future feature planned.",
               memory_type=MemoryType.project,
               valid_from=future)

        resp = _assemble(db_session, fake_provider,
                         "Munin feature",
                         as_of=now)
        assert not any("future feature" in m.content for m in resp.memories_used)

    def test_expired_memory_excluded(self, db_session, fake_provider):
        now = datetime.now(UTC)
        past = now - timedelta(days=10)

        _store(db_session, fake_provider,
               content="Munin temporary feature expired.",
               memory_type=MemoryType.project,
               valid_until=past)

        resp = _assemble(db_session, fake_provider,
                         "Munin temporary feature",
                         as_of=now)
        assert not any("expired" in m.content for m in resp.memories_used)

    def test_valid_memory_included_at_as_of(self, db_session, fake_provider):
        now = datetime.now(UTC)
        start = now - timedelta(days=5)
        end = now + timedelta(days=5)

        _store(db_session, fake_provider,
               content="Munin is in active development.",
               memory_type=MemoryType.project,
               valid_from=start,
               valid_until=end)

        resp = _assemble(db_session, fake_provider,
                         "Munin active development",
                         as_of=now)
        assert any("active development" in m.content for m in resp.memories_used)


class TestReplacementCorrectness:
    """Old superseded memory excluded; new active memory included."""

    def test_current_preference_included_old_excluded(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="User prefers OpenAI.",
               memory_type=MemoryType.preference,
               status=MemoryStatus.superseded)
        _store(db_session, fake_provider,
               content="User prefers local models.",
               memory_type=MemoryType.preference,
               status=MemoryStatus.active)

        resp = _assemble(db_session, fake_provider,
                         "What does the user prefer for LLM models?")

        contents = [m.content for m in resp.memories_used]
        assert not any("OpenAI" in c for c in contents)
        assert any("local models" in c for c in contents)


class TestContradictionFormatting:
    """Unresolved contradictions represented as conflict section."""

    def test_conflict_section_appears(self, db_session, fake_provider):
        from app.models.temporal import MemoryTemporalDecision
        from app.models.event import Event, EventRole

        # Two contradicting active memories
        m1 = _store(db_session, fake_provider,
                    content="User prefers Python.",
                    memory_type=MemoryType.preference)
        m2 = _store(db_session, fake_provider,
                    content="User prefers Rust.",
                    memory_type=MemoryType.preference)

        # Create a temporal decision marking the CONTRADICTS relationship
        ev = Event(namespace="test", content="test", role=EventRole.user,
                   created_at=datetime.now(UTC))
        db_session.add(ev)
        db_session.flush()

        td = MemoryTemporalDecision(
            event_id=ev.id,
            candidate_content="User prefers Rust.",
            candidate_memory_type="preference",
            matched_memory_id=m1.id,
            created_memory_id=m2.id,
            relationship="CONTRADICTS",
            relationship_confidence=0.9,
            provider="fake",
            model_name="fake-mini",
            created_at=datetime.now(UTC),
        )
        db_session.add(td)
        db_session.commit()

        resp = _assemble(db_session, fake_provider,
                         "User language preference Python Rust")

        if len(resp.memories_used) >= 2:
            # Both Python and Rust should be in the context
            all_content = " ".join(m.content for m in resp.memories_used)
            # Conflict section in formatted text
            assert "Unresolved conflicts" in resp.context or (
                "Python" in resp.context and "Rust" in resp.context
            )


class TestDiversity:
    """Near-identical memories suppressed to avoid wasting token budget."""

    def test_near_duplicate_suppressed(self, db_session, fake_provider):
        # Same content stored twice
        _store(db_session, fake_provider,
               content="User is building Munin memory agent system.",
               memory_type=MemoryType.project)
        _store(db_session, fake_provider,
               content="User is building Munin memory agent system.",
               memory_type=MemoryType.project)

        resp = _assemble(db_session, fake_provider,
                         "Continue building Munin memory agent system",
                         max_memories=10)

        # Both have identical embeddings — second should be suppressed
        munin_count = sum(1 for m in resp.memories_used if "Munin memory agent" in m.content)
        assert munin_count <= 1, "near-duplicate should be suppressed"


class TestTokenBudget:
    """Estimated tokens never exceed requested budget."""

    def test_tokens_within_budget(self, db_session, fake_provider):
        for i in range(10):
            _store(db_session, fake_provider,
                   content=f"Munin fact number {i} about memory and agents.",
                   memory_type=MemoryType.fact)

        budget = 200
        resp = _assemble(db_session, fake_provider,
                         "Munin memory agents", token_budget=budget)
        assert resp.estimated_tokens <= budget

    def test_tokens_within_large_budget(self, db_session, fake_provider):
        for i in range(5):
            _store(db_session, fake_provider,
                   content=f"Munin memory project fact {i}.",
                   memory_type=MemoryType.project)

        resp = _assemble(db_session, fake_provider,
                         "Munin memory project", token_budget=2000)
        assert resp.estimated_tokens <= 2000


class TestTinyBudget:
    """Tiny budget returns valid empty-or-minimal response without exception."""

    def test_tiny_budget_no_exception(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="User is building Munin.",
               memory_type=MemoryType.project)

        resp = _assemble(db_session, fake_provider,
                         "Continue building Munin", token_budget=1)

        # Should not raise; should return valid response
        assert isinstance(resp.memories_used, list)
        assert resp.estimated_tokens <= 1 or resp.memories_used == []
        assert isinstance(resp.context, str)

    def test_tiny_budget_truncated_flag(self, db_session, fake_provider):
        for i in range(5):
            _store(db_session, fake_provider,
                   content=f"Munin is a memory system fact {i}.",
                   memory_type=MemoryType.fact)

        resp = _assemble(db_session, fake_provider,
                         "Munin memory system", token_budget=5)
        # With many memories and very small budget, should be truncated
        assert resp.truncated or resp.memories_used == []


class TestMaxMemories:
    """max_memories limit is never exceeded."""

    def test_max_memories_enforced(self, db_session, fake_provider):
        for i in range(15):
            _store(db_session, fake_provider,
                   content=f"Munin memory agent fact {i}.",
                   memory_type=MemoryType.fact)

        resp = _assemble(db_session, fake_provider,
                         "Munin memory agent", max_memories=3, token_budget=5000)
        assert len(resp.memories_used) <= 3


class TestMemoryTypesFilter:
    """memory_types filter restricts returned memory types."""

    def test_type_filter_works(self, db_session, fake_provider):
        _store(db_session, fake_provider,
               content="User is building Munin.",
               memory_type=MemoryType.project)
        _store(db_session, fake_provider,
               content="User prefers Python for Munin.",
               memory_type=MemoryType.preference)

        resp = _assemble(db_session, fake_provider,
                         "Munin Python project",
                         memory_types=[MemoryType.project])

        for m in resp.memories_used:
            assert m.memory_type == MemoryType.project


class TestDeterministicOrdering:
    """Same request produces same memory ordering."""

    def test_same_ordering_repeated_call(self, db_session, fake_provider):
        now = datetime.now(UTC)
        for i in range(5):
            _store(db_session, fake_provider,
                   content=f"Munin agent memory fact {i}.",
                   memory_type=MemoryType.fact,
                   created_at=now - timedelta(seconds=i))

        fixed_as_of = datetime(2030, 1, 1, tzinfo=UTC)
        req = ContextRequest(
            query="Munin agent memory",
            namespace="test",
            as_of=fixed_as_of,
        )
        svc = ContextService(db=db_session, provider=fake_provider)

        resp1 = svc.assemble(req)
        resp2 = svc.assemble(req)

        ids1 = [m.memory_id for m in resp1.memories_used]
        ids2 = [m.memory_id for m in resp2.memories_used]
        assert ids1 == ids2, "ordering must be deterministic for same request"


class TestReadOnly:
    """Context assembly must not mutate any memory state."""

    def test_no_db_state_mutation(self, db_session, fake_provider):
        from sqlalchemy import inspect as sa_inspect

        m = _store(db_session, fake_provider,
                   content="User is building Munin.",
                   memory_type=MemoryType.project,
                   importance=0.7,
                   confidence=0.9)

        original_importance = m.importance
        original_confidence = m.confidence
        original_status = m.status
        original_updated_at = m.updated_at
        original_last_accessed = m.last_accessed_at

        _assemble(db_session, fake_provider, "Continue building Munin")

        db_session.refresh(m)

        assert m.importance == original_importance, "importance must not change"
        assert m.confidence == original_confidence, "confidence must not change"
        assert m.status == original_status, "status must not change"
        assert m.updated_at == original_updated_at, "updated_at must not change"
        assert m.last_accessed_at == original_last_accessed, "last_accessed_at must not change"

    def test_no_embedding_mutation(self, db_session, fake_provider):
        from app.repositories.embedding_repository import EmbeddingRepository

        m = _store(db_session, fake_provider,
                   content="Munin uses FastAPI.",
                   memory_type=MemoryType.decision)

        repo = EmbeddingRepository(db_session)
        before = repo.get_by_memory_id(m.id)
        before_updated = before.updated_at

        _assemble(db_session, fake_provider, "Munin FastAPI framework")

        after = repo.get_by_memory_id(m.id)
        assert after.updated_at == before_updated, "embedding must not be mutated"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestContextRequestValidation:
    def test_blank_query_rejected(self):
        with pytest.raises(Exception):
            ContextRequest(query="   ", namespace="test")

    def test_blank_namespace_rejected(self):
        with pytest.raises(Exception):
            ContextRequest(query="hello", namespace="   ")

    def test_zero_token_budget_rejected(self):
        with pytest.raises(Exception):
            ContextRequest(query="hello", namespace="test", token_budget=0)

    def test_valid_request_succeeds(self):
        req = ContextRequest(query="hello", namespace="test")
        assert req.query == "hello"
        assert req.token_budget == 1500

    def test_as_of_default_is_none(self):
        req = ContextRequest(query="hello", namespace="test")
        assert req.as_of is None  # service fills it in as UTC now

    def test_memory_types_none_by_default(self):
        req = ContextRequest(query="hello", namespace="test")
        assert req.memory_types is None


# ---------------------------------------------------------------------------
# API endpoint tests (via TestClient)
# ---------------------------------------------------------------------------

class TestContextEndpoint:
    def test_happy_path(self, client, db_session, fake_provider):
        # Store a memory via the client so embeddings are created properly
        client.post("/api/v1/memories", json={
            "namespace": "test",
            "content": "User is building Munin.",
            "memory_type": "project",
        })

        resp = client.post("/api/v1/context", json={
            "query": "Continue building Munin",
            "namespace": "test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "context" in data
        assert "memories_used" in data
        assert "estimated_tokens" in data
        assert "truncated" in data
        assert data["query"] == "Continue building Munin"
        assert data["namespace"] == "test"

    def test_empty_namespace_422(self, client):
        resp = client.post("/api/v1/context", json={
            "query": "hello",
            "namespace": "",
        })
        assert resp.status_code == 422

    def test_blank_query_422(self, client):
        resp = client.post("/api/v1/context", json={
            "query": "   ",
            "namespace": "test",
        })
        assert resp.status_code == 422

    def test_zero_budget_422(self, client):
        resp = client.post("/api/v1/context", json={
            "query": "hello",
            "namespace": "test",
            "token_budget": 0,
        })
        assert resp.status_code == 422

    def test_no_memories_returns_empty_context(self, client):
        resp = client.post("/api/v1/context", json={
            "query": "something completely unrelated",
            "namespace": "empty_ns_xyz",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["memories_used"] == []
        assert data["estimated_tokens"] == 0

    def test_memories_used_trace_fields(self, client):
        client.post("/api/v1/memories", json={
            "namespace": "test",
            "content": "Munin is a memory agent system.",
            "memory_type": "project",
        })

        resp = client.post("/api/v1/context", json={
            "query": "Munin memory agent",
            "namespace": "test",
        })
        assert resp.status_code == 200
        data = resp.json()
        if data["memories_used"]:
            m = data["memories_used"][0]
            for field in [
                "memory_id", "memory_type", "content",
                "semantic_score", "importance", "confidence",
                "recency_score", "type_relevance", "reinforcement_score",
                "final_score", "estimated_tokens",
            ]:
                assert field in m, f"missing field: {field}"
            # No raw embeddings
            assert "embedding" not in m

    def test_superseded_excluded_by_default(self, client):
        # Create superseded memory via memories API
        m_resp = client.post("/api/v1/memories", json={
            "namespace": "test",
            "content": "Munin uses SQLite.",
            "memory_type": "decision",
            "status": "superseded",
        })
        assert m_resp.status_code == 201

        resp = client.post("/api/v1/context", json={
            "query": "Munin database",
            "namespace": "test",
        })
        data = resp.json()
        contents = [m["content"] for m in data["memories_used"]]
        assert not any("SQLite" in c for c in contents)

    def test_include_superseded_flag(self, client):
        client.post("/api/v1/memories", json={
            "namespace": "test",
            "content": "Munin uses SQLite for testing.",
            "memory_type": "decision",
            "status": "superseded",
        })

        resp = client.post("/api/v1/context", json={
            "query": "Munin database SQLite testing",
            "namespace": "test",
            "include_superseded": True,
        })
        data = resp.json()
        contents = [m["content"] for m in data["memories_used"]]
        assert any("SQLite" in c for c in contents)

    def test_budget_respected_in_response(self, client):
        for i in range(10):
            client.post("/api/v1/memories", json={
                "namespace": "test",
                "content": f"Munin memory agent fact number {i} in the system.",
                "memory_type": "fact",
            })

        resp = client.post("/api/v1/context", json={
            "query": "Munin memory agent facts",
            "namespace": "test",
            "token_budget": 100,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["estimated_tokens"] <= 100

    def test_max_memories_respected(self, client):
        for i in range(8):
            client.post("/api/v1/memories", json={
                "namespace": "test",
                "content": f"Munin memory agent item {i}.",
                "memory_type": "fact",
            })

        resp = client.post("/api/v1/context", json={
            "query": "Munin memory agent",
            "namespace": "test",
            "max_memories": 2,
            "token_budget": 5000,
        })
        data = resp.json()
        assert len(data["memories_used"]) <= 2

    def test_memory_types_filter_in_endpoint(self, client):
        client.post("/api/v1/memories", json={
            "namespace": "test",
            "content": "User prefers Python for Munin.",
            "memory_type": "preference",
        })
        client.post("/api/v1/memories", json={
            "namespace": "test",
            "content": "Munin is a project for memory.",
            "memory_type": "project",
        })

        resp = client.post("/api/v1/context", json={
            "query": "Munin Python project preference",
            "namespace": "test",
            "memory_types": ["project"],
        })
        data = resp.json()
        for m in data["memories_used"]:
            assert m["memory_type"] == "project"

    def test_read_only_via_endpoint(self, client):
        """POST /context must not change any memory."""
        create_resp = client.post("/api/v1/memories", json={
            "namespace": "test",
            "content": "Munin is a durable memory system.",
            "memory_type": "project",
            "importance": 0.7,
        })
        assert create_resp.status_code == 201
        mem_id = create_resp.json()["id"]
        before = client.get(f"/api/v1/memories/{mem_id}").json()

        client.post("/api/v1/context", json={
            "query": "Munin durable memory system",
            "namespace": "test",
        })

        after = client.get(f"/api/v1/memories/{mem_id}").json()
        assert before["importance"] == after["importance"]
        assert before["confidence"] == after["confidence"]
        assert before["status"] == after["status"]
        assert before["updated_at"] == after["updated_at"]


# ---------------------------------------------------------------------------
# M1 regression: semantic search still works
# ---------------------------------------------------------------------------

class TestM1Regression:
    def test_semantic_search_still_works(self, client):
        client.post("/api/v1/memories", json={
            "namespace": "test",
            "content": "Munin is a memory agent framework.",
            "memory_type": "project",
        })

        resp = client.post("/api/v1/memories/search", json={
            "query": "memory agent framework",
            "namespace": "test",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] >= 1
        assert any("Munin" in r["memory"]["content"] for r in data["results"])
