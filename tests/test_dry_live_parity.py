"""Regression test: dry-run vs live-run context assembly parity.

Verifies that both paths through AgentRunner.run() produce identical
context retrieval — same namespace, same memory IDs, same context count,
same briefing content.

ROOT CAUSE: Previously all production embeddings were stored with
FakeEmbeddingProvider (provider=fake, dim=8), while the active
sentence_transformers provider (dim=384) never matched — causing 0
memories on every retrieval.

This test ensures both dry-run and live-run assemble identical context.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.agents.runner import AgentRunner, RunConfig
from app.agents.types import AgentLaunchResult
from app.embeddings.fake import FakeEmbeddingProvider
from app.embeddings.factory import set_embedding_provider_override
from app.models.memory import Memory, MemoryStatus, MemoryType
from app.schemas.context import ContextResponse, MemoryUsed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_memory(
    db: Session,
    *,
    namespace: str,
    content: str,
    memory_type: MemoryType = MemoryType.fact,
    importance: float = 0.5,
    confidence: float = 1.0,
) -> Memory:
    now = datetime.now(UTC)
    m = Memory(
        namespace=namespace,
        content=content,
        memory_type=memory_type,
        importance=importance,
        confidence=confidence,
        status=MemoryStatus.active,
        created_at=now,
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


def _make_runner(dry_run: bool) -> AgentRunner:
    config = RunConfig(
        agent_name="codex",
        dry_run=dry_run,
        token_budget=1500,
        max_memories=20,
    )
    runner = AgentRunner(config)
    runner._resolved_project_name = "huginn"
    runner._resolved_namespace = "project:huginn"
    runner._resolved_project_path = Path("/fake/huginn")
    return runner


def _setup_huginn_memories(db_session, fake_provider):
    """Create 3 memories for namespace 'project:huginn' and embed them."""
    m1 = _make_memory(
        db_session,
        namespace="project:huginn",
        content="Project huginn uses Python with FastAPI",
        memory_type=MemoryType.project,
    )
    m2 = _make_memory(
        db_session,
        namespace="project:huginn",
        content="Decision: Use SQLite for local development",
        memory_type=MemoryType.decision,
    )
    m3 = _make_memory(
        db_session,
        namespace="project:huginn",
        content="Implemented context injection for agent runner",
        memory_type=MemoryType.event,
    )
    _embed_memory(db_session, m1, fake_provider)
    _embed_memory(db_session, m2, fake_provider)
    _embed_memory(db_session, m3, fake_provider)
    db_session.commit()
    return m1, m2, m3


# ---------------------------------------------------------------------------
# Core parity test — verifies both paths through _assemble_context
# ---------------------------------------------------------------------------

class TestDryLiveParity:
    """Dry-run and live-run must produce identical context assembly."""

    def test_same_context_for_dry_and_live(self, db_session, fake_provider):
        """Both paths call _assemble_context with identical parameters.

        Creates a project namespace 'project:huginn' with 3 memories,
        then verifies both dry-run and live-run produce the same context.
        """
        _setup_huginn_memories(db_session, fake_provider)

        # Patch SessionLocal AND the embedding provider so _assemble_context
        # uses the test DB and fake provider (not production).
        TestingSessionLocal = MagicMock(return_value=db_session)
        set_embedding_provider_override(fake_provider)
        try:
            with patch("app.database.SessionLocal", TestingSessionLocal):
                dry_runner = _make_runner(dry_run=True)
                dry_text, dry_response = dry_runner._assemble_context()

                live_runner = _make_runner(dry_run=False)
                live_text, live_response = live_runner._assemble_context()
        finally:
            set_embedding_provider_override(None)

        # Assert identical results
        dry_ids = sorted(m.memory_id for m in dry_response.memories_used)
        live_ids = sorted(m.memory_id for m in live_response.memories_used)

        assert dry_ids == live_ids, (
            f"Memory IDs differ! dry={dry_ids} live={live_ids}"
        )
        assert len(dry_response.memories_used) == len(live_response.memories_used), (
            f"Memory count differs! dry={len(dry_response.memories_used)} "
            f"live={len(live_response.memories_used)}"
        )
        assert dry_response.estimated_tokens == live_response.estimated_tokens, (
            f"Token count differs! dry={dry_response.estimated_tokens} "
            f"live={live_response.estimated_tokens}"
        )

        # Both should return memories (at least 1 from the 3 stored)
        assert len(dry_response.memories_used) >= 1, (
            "Dry-run returned 0 memories — context assembly broken!"
        )
        assert len(live_response.memories_used) >= 1, (
            "Live-run returned 0 memories — context assembly broken!"
        )

    def test_briefing_identical_for_dry_and_live(self, db_session, fake_provider):
        """Both paths must produce identical briefing text."""
        _setup_huginn_memories(db_session, fake_provider)

        TestingSessionLocal = MagicMock(return_value=db_session)
        set_embedding_provider_override(fake_provider)
        try:
            with patch("app.database.SessionLocal", TestingSessionLocal):
                dry_runner = _make_runner(dry_run=True)
                dry_text, dry_response = dry_runner._assemble_context()
                dry_briefing = dry_runner._build_briefing(dry_text, dry_response)

                live_runner = _make_runner(dry_run=False)
                live_text, live_response = live_runner._assemble_context()
                live_briefing = live_runner._build_briefing(live_text, live_response)
        finally:
            set_embedding_provider_override(None)

        # Briefings must be identical
        assert dry_briefing == live_briefing, (
            "Briefing text differs between dry-run and live-run!\n"
            f"DRY:\n{dry_briefing}\n\nLIVE:\n{live_briefing}"
        )

        # Must contain real memories, not fallback
        assert "No Munin memories found" not in dry_briefing, (
            "Dry-run briefing shows 'No Munin memories found' — context is empty!"
        )
        assert "No Munin memories found" not in live_briefing, (
            "Live-run briefing shows 'No Munin memories found' — context is empty!"
        )
        assert "Python" in dry_briefing or "FastAPI" in dry_briefing, (
            "Dry-run briefing should contain actual memory content"
        )

    def test_full_run_returns_same_context_regardless_of_dry_flag(self, db_session, fake_provider):
        """Full run() pipeline produces identical context assembly for both flags.

        Uses mocks for adapter to avoid spawning Codex.
        Verifies the context assembly step (which is shared) returns identical results.
        """
        _setup_huginn_memories(db_session, fake_provider)

        def _run_with_flag(dry_run: bool) -> tuple[str, list, bool]:
            """Returns (briefing_text, memory_ids, success)."""
            config = RunConfig(
                agent_name="codex",
                dry_run=dry_run,
                token_budget=1500,
                max_memories=20,
            )
            runner = AgentRunner(config)
            runner._resolved_project_name = "huginn"
            runner._resolved_namespace = "project:huginn"
            runner._resolved_project_path = Path("/fake/huginn")

            # Capture the context before adapter touches it
            captured_briefings: list[str] = []
            original_build = runner._build_briefing
            def _capture_build(context_text, context_response):
                result = original_build(context_text, context_response)
                captured_briefings.append(result)
                return result
            runner._build_briefing = _capture_build

            with patch.object(runner, "_resolve_project"):
                with patch.object(runner, "_get_adapter") as mock_get_adapter:
                    mock_adapter = MagicMock()
                    mock_adapter.name = "Codex"
                    mock_adapter.agent_type = MagicMock(value="codex")
                    mock_adapter.available.return_value = True
                    mock_adapter.get_executable.return_value = Path("/usr/bin/codex")
                    mock_adapter.get_injection_mechanism.return_value = "initial_prompt_argument"
                    mock_adapter.build_command.return_value = ["codex", "test"]
                    mock_get_adapter.return_value = mock_adapter
                    mock_adapter.launch.return_value = AgentLaunchResult(
                        success=True,
                        agent_name="Codex",
                        briefing="test",
                        exit_code=0,
                    )

                    result = runner.run()

            briefing = captured_briefings[0] if captured_briefings else ""
            return briefing, result.success

        TestingSessionLocal = MagicMock(return_value=db_session)
        set_embedding_provider_override(fake_provider)
        try:
            with patch("app.database.SessionLocal", TestingSessionLocal):
                dry_briefing, dry_ok = _run_with_flag(dry_run=True)
                live_briefing, live_ok = _run_with_flag(dry_run=False)
        finally:
            set_embedding_provider_override(None)

        assert dry_ok is True
        assert live_ok is True

        # Briefings must be identical
        assert dry_briefing == live_briefing, (
            "Briefing differs between dry-run and live-run!\n"
            f"DRY ({len(dry_briefing)} chars):\n{dry_briefing[:500]}\n\n"
            f"LIVE ({len(live_briefing)} chars):\n{live_briefing[:500]}"
        )

        # Must NOT be the empty fallback
        assert "No Munin memories found" not in live_briefing, (
            "Live-run returned fallback briefing instead of real context!"
        )

    def test_context_assembly_exception_returns_empty_for_both(self, db_session, fake_provider):
        """If context assembly fails, BOTH paths return empty (not just one)."""
        with patch("app.database.SessionLocal", MagicMock(return_value=db_session)):
            with patch("app.context.service.ContextService") as mock_svc:
                mock_svc.side_effect = RuntimeError("DB connection lost")

                dry_runner = _make_runner(dry_run=True)
                live_runner = _make_runner(dry_run=False)

                dry_text, dry_resp = dry_runner._assemble_context()
                live_text, live_resp = live_runner._assemble_context()

                # Both should return empty context on exception
                assert len(dry_resp.memories_used) == 0
                assert len(live_resp.memories_used) == 0
                assert dry_resp.context == ""
                assert live_resp.context == ""
