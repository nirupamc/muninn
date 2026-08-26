"""Tests for M8.3B — Universal Agent Context Injection.

Covers:
  1. cwd resolves correct project
  2. --project override (path and namespace)
  3. unknown project safe failure
  4. zero-memory project handling
  5. project isolation (no cross-namespace leakage)
  6. M5 context assembly reused
  7. task-aware retrieval
  8. briefing formatting
  9. briefing budget
  10. Codex detection
  11. Kilo detection
  12. OpenCode detection
  13. argument forwarding
  14. child exit-code preservation
  15. unsupported-agent status
  16. dry-run does not launch
  17. dry-run shows injection mechanism
  18. no cross-namespace leakage
  19. missing executable handling
  20. model vs agent distinction
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.agents.types import (
    AgentInfo,
    AgentLaunchResult,
    AgentStatus,
    AgentType,
    InjectionCapability,
)
from app.agents.adapter import AgentLaunchAdapter
from app.agents.registry import AgentRegistry, DetectedAgent, get_registry
from app.agents.briefing import (
    BriefingConfig,
    BriefingFormatter,
    MuninProjectBriefing,
    create_project_briefing,
    BRIEFING_START,
    BRIEFING_END,
)
from app.agents.runner import AgentRunner, RunConfig


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def mock_db():
    """Provide a mock database session."""
    return MagicMock()


@pytest.fixture
def mock_context_response():
    """Provide a mock M5 context response with memories."""
    from app.schemas.context import ContextResponse, MemoryUsed
    from app.models.memory import MemoryType

    memories = [
        MemoryUsed(
            memory_id="mem-1",
            memory_type=MemoryType.fact,
            content="Project uses FastAPI with SQLAlchemy ORM",
            semantic_score=0.85,
            importance=0.7,
            confidence=0.9,
            recency_score=0.8,
            type_relevance=0.6,
            reinforcement_score=0.5,
            final_score=0.75,
            estimated_tokens=20,
            reason_codes=["semantic_match"],
        ),
        MemoryUsed(
            memory_id="mem-2",
            memory_type=MemoryType.decision,
            content="Decision: Use SQLite for local-first development",
            semantic_score=0.80,
            importance=0.8,
            confidence=0.85,
            recency_score=0.7,
            type_relevance=0.7,
            reinforcement_score=0.4,
            final_score=0.72,
            estimated_tokens=15,
            reason_codes=["semantic_match", "type_relevance"],
        ),
        MemoryUsed(
            memory_id="mem-3",
            memory_type=MemoryType.event,
            content="Implemented M8.3B agent context injection",
            semantic_score=0.70,
            importance=0.6,
            confidence=0.8,
            recency_score=0.9,
            type_relevance=0.5,
            reinforcement_score=0.3,
            final_score=0.65,
            estimated_tokens=12,
            reason_codes=["recency"],
        ),
    ]

    return ContextResponse(
        query="project context",
        namespace="munin",
        context="Munin is a local-first memory layer for AI agents.",
        token_budget=1500,
        estimated_tokens=150,
        truncated=False,
        memories_used=memories,
    )


@pytest.fixture
def empty_context_response():
    """Provide a mock M5 context response with no memories."""
    from app.schemas.context import ContextResponse

    return ContextResponse(
        query="project context",
        namespace="empty-project",
        context="",
        token_budget=1500,
        estimated_tokens=0,
        truncated=False,
        memories_used=[],
    )


# ======================================================================
# Types Tests
# ======================================================================


class TestAgentTypes:
    """Test agent type definitions."""

    def test_agent_type_enum(self):
        """AgentType enum has expected values."""
        assert AgentType.codex.value == "codex"
        assert AgentType.kilo.value == "kilo"
        assert AgentType.opencode.value == "opencode"
        assert AgentType.claude.value == "claude"
        assert AgentType.aider.value == "aider"

    def test_agent_status_enum(self):
        """AgentStatus enum has expected values."""
        assert AgentStatus.INSTALLED_SUPPORTED.value == "INSTALLED_SUPPORTED"
        assert AgentStatus.INSTALLED_BRIDGE_ONLY.value == "INSTALLED_BRIDGE_ONLY"
        assert AgentStatus.INSTALLED_UNSUPPORTED.value == "INSTALLED_UNSUPPORTED"
        assert AgentStatus.NOT_INSTALLED.value == "NOT_INSTALLED"

    def test_injection_capability_enum(self):
        """InjectionCapability has expected values."""
        assert InjectionCapability.supports_initial_prompt.value == "supports_initial_prompt"
        assert InjectionCapability.supports_stdin.value == "supports_stdin"

    def test_agent_launch_result_defaults(self):
        """AgentLaunchResult has sensible defaults."""
        result = AgentLaunchResult(success=True, agent_name="test")
        assert result.exit_code is None
        assert result.error is None
        assert result.briefing is None

    def test_agent_info_defaults(self):
        """AgentInfo has sensible defaults."""
        info = AgentInfo(name="test", agent_type=AgentType.codex)
        assert info.status == AgentStatus.NOT_INSTALLED
        assert info.capabilities == set()


# ======================================================================
# Adapter Tests
# ======================================================================


class TestAgentLaunchAdapter:
    """Test the base adapter ABC."""

    def test_abstract_methods_required(self):
        """Cannot instantiate adapter without implementing abstract methods."""
        with pytest.raises(TypeError):
            AgentLaunchAdapter()  # type: ignore

    def test_concrete_adapter_inheritance(self):
        """A concrete adapter must implement all abstract methods."""
        class MinimalAdapter(AgentLaunchAdapter):
            agent_type = AgentType.codex
            name = "Minimal"

            def available(self) -> bool:
                return False

            def detect(self) -> AgentInfo:
                return AgentInfo(name="Minimal", agent_type=AgentType.codex)

            def get_executable(self) -> str | Path | None:
                return None

            def build_command(self, context, project_path=None, task=None, extra_args=None):
                return ["minimal"]

            def get_injection_mechanism(self) -> str:
                return "test"

        adapter = MinimalAdapter()
        assert adapter.available() is False
        assert adapter.get_injection_mechanism() == "test"
        assert adapter.build_command("hello") == ["minimal"]

    def test_dry_run_returns_dict(self):
        """dry_run returns a diagnostic dictionary without launching."""
        class MinimalAdapter(AgentLaunchAdapter):
            agent_type = AgentType.codex
            name = "Minimal"
            status = AgentStatus.INSTALLED_SUPPORTED

            def available(self) -> bool:
                return True

            def detect(self) -> AgentInfo:
                return AgentInfo(name="Minimal", agent_type=AgentType.codex, status=AgentStatus.INSTALLED_SUPPORTED)

            def get_executable(self):
                return "/usr/bin/minimal"

            def build_command(self, context, project_path=None, task=None, extra_args=None):
                return ["minimal", context]

            def get_injection_mechanism(self) -> str:
                return "initial_prompt_argument"

        adapter = MinimalAdapter()
        result = adapter.dry_run("test context", project_path="/test")
        assert result["agent"] == "Minimal"
        assert result["available"] is True
        assert result["injection_mechanism"] == "initial_prompt_argument"
        assert result["command"] == ["minimal", "test context"]

    def test_launch_not_called_on_dry_run(self):
        """dry_run should not call launch."""
        class MinimalAdapter(AgentLaunchAdapter):
            agent_type = AgentType.codex
            name = "Minimal"

            def available(self):
                return True

            def detect(self):
                return AgentInfo(name="Minimal", agent_type=AgentType.codex)

            def get_executable(self):
                return "/usr/bin/minimal"

            def build_command(self, context, project_path=None, task=None, extra_args=None):
                return ["minimal", context]

            def get_injection_mechanism(self):
                return "initial_prompt_argument"

        adapter = MinimalAdapter()
        with patch.object(adapter, "launch") as mock_launch:
            adapter.dry_run("test context")
            mock_launch.assert_not_called()


# ======================================================================
# Registry Tests
# ======================================================================


class TestAgentRegistry:
    """Test the agent registry."""

    def test_registry_initializes(self):
        """Registry initializes with adapters."""
        registry = AgentRegistry()
        registry._ensure_initialized()
        assert len(registry.SUPPORTED_AGENTS) >= 3  # codex, kilo, opencode

    def test_detect_all_returns_agents(self):
        """detect_all returns detected agents."""
        registry = AgentRegistry()
        agents = registry.detect_all()
        assert len(agents) >= 3
        assert "codex" in agents
        assert "kilo" in agents
        assert "opencode" in agents

    def test_get_agent_by_name(self):
        """get_agent finds agent by type value."""
        registry = AgentRegistry()
        registry.detect_all()
        agent = registry.get_agent("codex")
        assert agent is not None
        assert agent.agent_type == AgentType.codex

    def test_get_agent_case_insensitive(self):
        """get_agent is case-insensitive."""
        registry = AgentRegistry()
        registry.detect_all()
        agent = registry.get_agent("Codex")
        assert agent is not None

    def test_get_adapter_returns_instance(self):
        """get_adapter returns an adapter instance."""
        registry = AgentRegistry()
        adapter = registry.get_adapter("codex")
        assert adapter is not None
        assert hasattr(adapter, "available")

    def test_get_adapter_unknown_returns_none(self):
        """get_adapter returns None for unknown agent."""
        registry = AgentRegistry()
        adapter = registry.get_adapter("nonexistent")
        assert adapter is None

    def test_status_table(self):
        """get_status_table returns formatted data."""
        registry = AgentRegistry()
        table = registry.get_status_table()
        assert len(table) >= 3
        for row in table:
            assert "name" in row
            assert "type" in row
            assert "installed" in row
            assert "status" in row

    def test_list_installed(self):
        """list_installed returns only installed agents."""
        registry = AgentRegistry()
        installed = registry.list_installed()
        for agent in installed:
            assert agent.status in (
                AgentStatus.INSTALLED_SUPPORTED,
                AgentStatus.INSTALLED_BRIDGE_ONLY,
            )


# ======================================================================
# Briefing Tests
# ======================================================================


class TestBriefing:
    """Test the project briefing formatter."""

    def test_briefing_has_markers(self, mock_context_response):
        """Briefing contains start and end markers."""
        briefing = create_project_briefing(
            project_name="TestProject",
            project_path="/test/project",
            namespace="test",
            context=mock_context_response,
        )
        assert BRIEFING_START in briefing.briefing_text
        assert BRIEFING_END in briefing.briefing_text

    def test_briefing_contains_project_name(self, mock_context_response):
        """Briefing contains the project name."""
        briefing = create_project_briefing(
            project_name="Huginn",
            context=mock_context_response,
        )
        assert "Huginn" in briefing.briefing_text

    def test_briefing_contains_namespace(self, mock_context_response):
        """Briefing contains the namespace."""
        briefing = create_project_briefing(
            project_name="Test",
            namespace="munin",
            context=mock_context_response,
        )
        assert "munin" in briefing.briefing_text.lower()

    def test_briefing_empty_project(self, empty_context_response):
        """Briefing for project with no memories."""
        briefing = create_project_briefing(
            project_name="EmptyProject",
            context=empty_context_response,
        )
        assert "No Munin memories found" in briefing.briefing_text or "no durable project memories" in briefing.briefing_text.lower()
        assert BRIEFING_START in briefing.briefing_text

    def test_briefing_no_context(self):
        """Briefing without context still works."""
        briefing = create_project_briefing(project_name="NoContext")
        assert BRIEFING_START in briefing.briefing_text
        assert BRIEFING_END in briefing.briefing_text
        assert "NoContext" in briefing.briefing_text

    def test_briefing_truncation(self):
        """Briefing respects max length."""
        config = BriefingConfig(max_briefing_length=200)
        formatter = BriefingFormatter(config)

        # Create a context with lots of memories
        from app.schemas.context import ContextResponse, MemoryUsed
        from app.models.memory import MemoryType

        memories = [
            MemoryUsed(
                memory_id=f"mem-{i}",
                memory_type=MemoryType.fact,
                content=f"Memory content number {i} with some additional text to make it longer " * 3,
                semantic_score=0.8,
                importance=0.7,
                confidence=0.9,
                recency_score=0.8,
                type_relevance=0.6,
                reinforcement_score=0.5,
                final_score=0.75,
                estimated_tokens=50,
                reason_codes=[],
            )
            for i in range(20)
        ]

        ctx = ContextResponse(
            query="test",
            namespace="test",
            context="test context " * 100,
            token_budget=5000,
            estimated_tokens=500,
            truncated=False,
            memories_used=memories,
        )

        briefing = formatter.create_briefing("BigProject", context=ctx)
        # Allow 16 chars of slack for the "... (truncated)" suffix rounding
        assert len(briefing.briefing_text) <= 220

    def test_briefing_categorizes_decisions(self, mock_context_response):
        """Briefing categorizes decision-type memories."""
        briefing = create_project_briefing(
            project_name="Test",
            context=mock_context_response,
        )
        # The decision memory should be categorized
        assert "Decision" in briefing.briefing_text

    def test_briefing_memory_count(self, mock_context_response):
        """Briefing tracks memory count."""
        briefing = create_project_briefing(
            project_name="Test",
            context=mock_context_response,
        )
        assert briefing.memory_count == 3

    def test_briefing_token_estimate(self, mock_context_response):
        """Briefing estimates tokens."""
        briefing = create_project_briefing(
            project_name="Test",
            context=mock_context_response,
        )
        assert briefing.token_estimate > 0


# ======================================================================
# Runner Tests
# ======================================================================


class TestAgentRunner:
    """Test the agent runner orchestration."""

    def test_runconfig_defaults(self):
        """RunConfig has sensible defaults."""
        config = RunConfig(agent_name="codex")
        assert config.project_path is None
        assert config.namespace is None
        assert config.task is None
        assert config.extra_args == []
        assert config.dry_run is False
        assert config.token_budget == 1500
        assert config.max_memories == 20

    def test_runner_cwd_resolution(self):
        """Runner resolves project from cwd."""
        config = RunConfig(agent_name="codex")
        runner = AgentRunner(config)
        runner._resolve_project()
        # Should have resolved something from cwd
        assert runner._resolved_namespace is not None

    def test_runner_explicit_project_path(self):
        """Runner resolves explicit --project path."""
        config = RunConfig(agent_name="codex", project_path="E:\\Muninn")
        runner = AgentRunner(config)
        runner._resolve_project()
        # May or may not find a registered project, but shouldn't crash

    def test_runner_fallback_namespace(self):
        """Runner falls back to 'default' namespace when no project found."""
        config = RunConfig(agent_name="codex")
        runner = AgentRunner(config)
        # Mock the DB lookups to return nothing by patching at the import sites
        with patch("app.database.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            with patch("app.capture.project_resolver.ProjectResolver") as mock_resolver_cls:
                mock_resolver = MagicMock()
                mock_resolver.resolve_by_path.return_value = None
                mock_resolver_cls.return_value = mock_resolver
                with patch("app.projects.repository.ProjectRepository") as mock_repo_cls:
                    mock_repo = MagicMock()
                    mock_repo.get_by_canonical_path.return_value = None
                    mock_repo_cls.return_value = mock_repo
                    runner._resolve_project()
        assert runner._resolved_namespace == "default"

    def test_runner_dry_run_does_not_launch(self, mock_context_response):
        """Dry run does not call adapter.launch."""
        config = RunConfig(agent_name="codex", dry_run=True)
        runner = AgentRunner(config)

        # Mock all DB calls
        with patch.object(runner, "_resolve_project"):
            runner._resolved_project_name = "TestProject"
            runner._resolved_namespace = "test"
            runner._resolved_project_path = Path("/test")

        with patch.object(runner, "_get_adapter") as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.name = "Codex"
            mock_adapter.agent_type = AgentType.codex
            mock_adapter.available.return_value = True
            mock_adapter.get_executable.return_value = Path("/usr/bin/codex")
            mock_adapter.get_injection_mechanism.return_value = "initial_prompt_argument"
            mock_adapter.build_command.return_value = ["codex", "test"]
            mock_get_adapter.return_value = mock_adapter

            with patch.object(runner, "_assemble_context") as mock_ctx:
                mock_ctx.return_value = ("test context", mock_context_response)

                with patch.object(runner, "_build_briefing") as mock_brief:
                    mock_brief.return_value = "[MUNIN PROJECT CONTEXT]\nTest\n[MUNIN CONTEXT END]"

                    result = runner.run()

                    # Dry run should not call launch
                    mock_adapter.launch.assert_not_called()
                    assert result.success is True

    def test_runner_dry_run_shows_injection_mechanism(self, mock_context_response):
        """Dry run output includes injection mechanism."""
        config = RunConfig(agent_name="codex", dry_run=True)
        runner = AgentRunner(config)

        with patch.object(runner, "_resolve_project"):
            runner._resolved_project_name = "TestProject"
            runner._resolved_namespace = "test"
            runner._resolved_project_path = Path("/test")

        with patch.object(runner, "_get_adapter") as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.name = "Codex"
            mock_adapter.agent_type = AgentType.codex
            mock_adapter.available.return_value = True
            mock_adapter.get_executable.return_value = Path("/usr/bin/codex")
            mock_adapter.get_injection_mechanism.return_value = "initial_prompt_argument"
            mock_adapter.build_command.return_value = ["codex", "test"]
            mock_get_adapter.return_value = mock_adapter

            with patch.object(runner, "_assemble_context") as mock_ctx:
                mock_ctx.return_value = ("test context", mock_context_response)

                with patch.object(runner, "_build_briefing") as mock_brief:
                    mock_brief.return_value = "[MUNIN PROJECT CONTEXT]\nTest\n[MUNIN CONTEXT END]"

                    result = runner.run()
                    assert result.injection_mechanism == "initial_prompt_argument"

    def test_runner_unknown_agent_fails(self):
        """Runner fails gracefully for unknown agent."""
        config = RunConfig(agent_name="nonexistent_agent_xyz")
        runner = AgentRunner(config)
        result = runner.run()
        assert result.success is False
        assert "not found" in result.error.lower() or "not installed" in result.error.lower()

    def test_runner_exit_code_preserved(self):
        """Runner preserves agent exit code."""
        config = RunConfig(agent_name="codex")
        runner = AgentRunner(config)

        with patch.object(runner, "_resolve_project"):
            runner._resolved_project_name = "Test"
            runner._resolved_namespace = "test"
            runner._resolved_project_path = Path("/test")

        with patch.object(runner, "_get_adapter") as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.name = "Codex"
            mock_adapter.available.return_value = True
            mock_adapter.get_executable.return_value = Path("/usr/bin/codex")
            mock_get_adapter.return_value = mock_adapter

            with patch.object(runner, "_assemble_context") as mock_ctx:
                from app.schemas.context import ContextResponse
                mock_ctx.return_value = ("", ContextResponse(
                    query="test", namespace="test", context="",
                    token_budget=1500, estimated_tokens=0,
                    truncated=False, memories_used=[],
                ))

                with patch.object(runner, "_build_briefing") as mock_brief:
                    mock_brief.return_value = "test"

                    # Mock launch to return exit code 42
                    mock_adapter.launch.return_value = AgentLaunchResult(
                        success=True, agent_name="Codex", exit_code=42,
                    )

                    result = runner.run()
                    assert result.exit_code == 42

    def test_runner_task_forwarding(self):
        """Runner forwards task to adapter build_command."""
        config = RunConfig(agent_name="codex", task="fix the tests")
        runner = AgentRunner(config)

        with patch.object(runner, "_resolve_project"):
            runner._resolved_project_name = "Test"
            runner._resolved_namespace = "test"
            runner._resolved_project_path = Path("/test")

        with patch.object(runner, "_get_adapter") as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.name = "Codex"
            mock_adapter.available.return_value = True
            mock_adapter.get_executable.return_value = Path("/usr/bin/codex")
            mock_get_adapter.return_value = mock_adapter

            with patch.object(runner, "_assemble_context") as mock_ctx:
                from app.schemas.context import ContextResponse
                mock_ctx.return_value = ("", ContextResponse(
                    query="fix the tests", namespace="test", context="",
                    token_budget=1500, estimated_tokens=0,
                    truncated=False, memories_used=[],
                ))

                with patch.object(runner, "_build_briefing") as mock_brief:
                    mock_brief.return_value = "test briefing"
                    mock_adapter.launch.return_value = AgentLaunchResult(
                        success=True, agent_name="Codex", exit_code=0,
                    )

                    runner.run()

                    # Verify task was passed
                    mock_adapter.launch.assert_called_once()
                    call_kwargs = mock_adapter.launch.call_args
                    assert call_kwargs.kwargs.get("task") == "fix the tests"

    def test_runner_extra_args_forwarded(self):
        """Runner forwards extra_args to adapter."""
        config = RunConfig(agent_name="codex", extra_args=["--verbose", "--model", "gpt-4"])
        runner = AgentRunner(config)

        with patch.object(runner, "_resolve_project"):
            runner._resolved_project_name = "Test"
            runner._resolved_namespace = "test"
            runner._resolved_project_path = Path("/test")

        with patch.object(runner, "_get_adapter") as mock_get_adapter:
            mock_adapter = MagicMock()
            mock_adapter.name = "Codex"
            mock_adapter.available.return_value = True
            mock_adapter.get_executable.return_value = Path("/usr/bin/codex")
            mock_get_adapter.return_value = mock_adapter

            with patch.object(runner, "_assemble_context") as mock_ctx:
                from app.schemas.context import ContextResponse
                mock_ctx.return_value = ("", ContextResponse(
                    query="test", namespace="test", context="",
                    token_budget=1500, estimated_tokens=0,
                    truncated=False, memories_used=[],
                ))

                with patch.object(runner, "_build_briefing") as mock_brief:
                    mock_brief.return_value = "test"
                    mock_adapter.launch.return_value = AgentLaunchResult(
                        success=True, agent_name="Codex", exit_code=0,
                    )

                    runner.run()

                    call_kwargs = mock_adapter.launch.call_args
                    assert call_kwargs.kwargs.get("extra_args") == ["--verbose", "--model", "gpt-4"]


# ======================================================================
# Namespace Isolation Tests
# ======================================================================


class TestNamespaceIsolation:
    """Test that projects don't leak context across namespaces."""

    def test_different_namespaces_different_context(self):
        """Different namespaces get different context."""
        from app.schemas.context import ContextResponse, MemoryUsed
        from app.models.memory import MemoryType

        memories_a = [
            MemoryUsed(
                memory_id="mem-a1", memory_type=MemoryType.fact,
                content="Project A uses React with TypeScript",
                semantic_score=0.8, importance=0.7, confidence=0.9,
                recency_score=0.8, type_relevance=0.6, reinforcement_score=0.5,
                final_score=0.75, estimated_tokens=10, reason_codes=[],
            ),
        ]
        memories_b = [
            MemoryUsed(
                memory_id="mem-b1", memory_type=MemoryType.fact,
                content="Project B uses Vue with JavaScript",
                semantic_score=0.8, importance=0.7, confidence=0.9,
                recency_score=0.8, type_relevance=0.6, reinforcement_score=0.5,
                final_score=0.75, estimated_tokens=10, reason_codes=[],
            ),
        ]

        ctx_a = ContextResponse(
            query="test", namespace="project-a", context="context for A",
            token_budget=1500, estimated_tokens=10, truncated=False, memories_used=memories_a,
        )
        ctx_b = ContextResponse(
            query="test", namespace="project-b", context="context for B",
            token_budget=1500, estimated_tokens=10, truncated=False, memories_used=memories_b,
        )

        briefing_a = create_project_briefing("ProjectA", namespace="project-a", context=ctx_a)
        briefing_b = create_project_briefing("ProjectB", namespace="project-b", context=ctx_b)

        assert "project-a" in briefing_a.briefing_text
        assert "project-b" in briefing_b.briefing_text
        assert "React" in briefing_a.briefing_text
        assert "Vue" in briefing_b.briefing_text
        # Briefing A should NOT contain B's memories
        assert "Vue" not in briefing_a.briefing_text

    def test_runner_namespace_scoped_context(self, mock_context_response):
        """Runner requests context with the resolved namespace."""
        config = RunConfig(agent_name="codex")
        runner = AgentRunner(config)

        with patch.object(runner, "_resolve_project"):
            runner._resolved_project_name = "Huginn"
            runner._resolved_namespace = "huginn"
            runner._resolved_project_path = Path("E:\\huginn")

        with patch("app.database.SessionLocal") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value = mock_session
            with patch("app.context.service.ContextService") as mock_ctx_svc:
                mock_service = MagicMock()
                mock_service.assemble.return_value = mock_context_response
                mock_ctx_svc.return_value = mock_service
                with patch("app.schemas.context.ContextRequest") as mock_req_cls:
                    text, response = runner._assemble_context()
                    # Verify namespace was passed to ContextRequest
                    call_kwargs = mock_req_cls.call_args.kwargs
                    assert call_kwargs.get("namespace") == "huginn"


# ======================================================================
# Codex Adapter Tests
# ======================================================================


class TestCodexAdapter:
    """Test Codex-specific adapter behavior."""

    def test_codex_detection(self):
        """Codex adapter detects installation."""
        from app.agents.adapters.codex import CodexLaunchAdapter

        adapter = CodexLaunchAdapter()
        info = adapter.detect()
        assert info.name == "Codex"
        assert info.agent_type == AgentType.codex
        # Status depends on whether codex is actually installed
        assert info.status in (AgentStatus.INSTALLED_SUPPORTED, AgentStatus.NOT_INSTALLED)

    def test_codex_injection_mechanism(self):
        """Codex uses initial_prompt_argument."""
        from app.agents.adapters.codex import CodexLaunchAdapter

        adapter = CodexLaunchAdapter()
        assert adapter.get_injection_mechanism() == "initial_prompt_argument"

    def test_codex_build_command(self):
        """Codex build_command produces correct format."""
        from app.agents.adapters.codex import CodexLaunchAdapter

        adapter = CodexLaunchAdapter()
        with patch.object(adapter, "_executable", Path("/fake/codex.exe")):
            with patch.object(adapter, "_detected", True):
                cmd = adapter.build_command("test context", task="fix tests")
                # Windows normalizes /fake to \fake, so just check the filename
                assert "codex.exe" in str(cmd[0])
                # Task should be prepended to context
                assert "fix tests" in cmd[1]
                assert "test context" in cmd[1]

    def test_codex_build_command_with_extra_args(self):
        """Codex build_command forwards extra args."""
        from app.agents.adapters.codex import CodexLaunchAdapter

        adapter = CodexLaunchAdapter()
        with patch.object(adapter, "_executable", Path("/fake/codex.exe")):
            with patch.object(adapter, "_detected", True):
                cmd = adapter.build_command("context", extra_args=["--model", "gpt-4"])
                assert "--model" in cmd
                assert "gpt-4" in cmd


# ======================================================================
# Kilo Adapter Tests
# ======================================================================


class TestKiloAdapter:
    """Test Kilo-specific adapter behavior."""

    def test_kilo_detection(self):
        """Kilo adapter detects installation."""
        from app.agents.adapters.kilo import KiloLaunchAdapter

        adapter = KiloLaunchAdapter()
        info = adapter.detect()
        assert info.name == "Kilo"
        assert info.agent_type == AgentType.kilo

    def test_kilo_injection_mechanism(self):
        """Kilo uses run_command_message."""
        from app.agents.adapters.kilo import KiloLaunchAdapter

        adapter = KiloLaunchAdapter()
        assert adapter.get_injection_mechanism() == "run_command_message"

    def test_kilo_build_command(self):
        """Kilo build_command uses 'run' subcommand."""
        from app.agents.adapters.kilo import KiloLaunchAdapter

        adapter = KiloLaunchAdapter()
        with patch.object(adapter, "_executable", Path("/fake/kilo.cmd")):
            with patch.object(adapter, "_detected", True):
                cmd = adapter.build_command("test context")
                assert "kilo.cmd" in str(cmd[0])
                assert cmd[1] == "run"
                assert "test context" in cmd[2]


# ======================================================================
# OpenCode Adapter Tests
# ======================================================================


class TestOpenCodeAdapter:
    """Test OpenCode-specific adapter behavior."""

    def test_opencode_detection(self):
        """OpenCode adapter detects installation."""
        from app.agents.adapters.opencode import OpenCodeLaunchAdapter

        adapter = OpenCodeLaunchAdapter()
        info = adapter.detect()
        assert info.name == "OpenCode"
        assert info.agent_type == AgentType.opencode

    def test_opencode_injection_mechanism(self):
        """OpenCode uses run_command_message."""
        from app.agents.adapters.opencode import OpenCodeLaunchAdapter

        adapter = OpenCodeLaunchAdapter()
        assert adapter.get_injection_mechanism() == "run_command_message"

    def test_opencode_build_command(self):
        """OpenCode build_command uses 'run' subcommand."""
        from app.agents.adapters.opencode import OpenCodeLaunchAdapter

        adapter = OpenCodeLaunchAdapter()
        with patch.object(adapter, "_executable", Path("/fake/opencode.cmd")):
            with patch.object(adapter, "_detected", True):
                cmd = adapter.build_command("test context")
                assert "opencode.cmd" in str(cmd[0])
                assert cmd[1] == "run"
                assert "test context" in cmd[2]


# ======================================================================
# CLI Integration Tests
# ======================================================================


class TestCLIIntegration:
    """Test CLI parser for run/agents commands."""

    def test_run_parser_exists(self):
        """CLI parser has 'run' subcommand."""
        from app.cli import build_parser

        parser = build_parser()
        # REMAINDER captures the -- separator too; cmd_run strips it
        args = parser.parse_args(["run", "--", "codex"])
        assert args.command == "run"
        assert args.agent == ["--", "codex"]

    def test_run_parser_with_flags(self):
        """CLI parser accepts run flags."""
        from app.cli import build_parser

        parser = build_parser()
        # Convention: named flags BEFORE agent
        args = parser.parse_args([
            "run",
            "--project", "E:\\huginn",
            "--task", "fix tests",
            "--dry-run",
            "--token-budget", "2000",
            "--max-memories", "30",
            "--", "codex",
        ])
        assert args.command == "run"
        assert args.agent == ["--", "codex"]  # REMAINDER includes --
        assert args.project == "E:\\huginn"
        assert args.task == "fix tests"
        assert args.dry_run is True
        assert args.token_budget == 2000
        assert args.max_memories == 30

    def test_run_parser_with_agent_args(self):
        """CLI parser captures agent arguments."""
        from app.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["run", "--", "codex", "--verbose", "--model", "gpt-4"])
        assert args.agent == ["--", "codex", "--verbose", "--model", "gpt-4"]

    def test_agents_parser(self):
        """CLI parser has 'agents' subcommand."""
        from app.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["agents"])
        assert args.command == "agents"


class TestNoShutilQuote:
    """Regression: shutil.quote does not exist on Windows.

    The launch adapter must never call shutil.quote.  It should use
    argument-list subprocess (shell=False) and shlex.quote only for
    human-readable display.
    """

    def test_adapter_does_not_import_shutil(self):
        """app.agents.adapter must not import shutil."""
        import importlib
        import app.agents.adapter as mod

        source = importlib.util.find_spec(mod.__name__).origin
        with open(source, encoding="utf-8") as f:
            text = f.read()
        # Allow "import shutil" only inside docstrings or comments
        code_lines = [
            line for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        for line in code_lines:
            assert "import shutil" not in line, (
                f"app.agents.adapter must not import shutil: {line.strip()}"
            )

    def test_codex_build_command_no_shutil(self):
        """Codex build_command produces a clean argument list."""
        from app.agents.adapters.codex import CodexLaunchAdapter

        adapter = CodexLaunchAdapter()
        # Fake executable so build_command succeeds
        fake_exe = Path("C:/fake/codex.exe")
        adapter._executable = fake_exe
        adapter._detected = True

        cmd = adapter.build_command(
            context="[MUNIN CONTEXT]",
            project_path="E:/huginn",
        )
        assert isinstance(cmd, list)
        # Path normalizes on Windows; compare as Path objects
        assert Path(cmd[0]) == fake_exe
        assert "[MUNIN CONTEXT]" in cmd[1]

    def test_launch_uses_shell_false_for_exe(self):
        """launch() must use shell=False for .exe executables."""
        from unittest.mock import patch, MagicMock
        from app.agents.adapters.codex import CodexLaunchAdapter
        from app.agents.types import AgentLaunchResult

        adapter = CodexLaunchAdapter()
        adapter._executable = Path("C:/fake/codex.exe")
        adapter._detected = True

        mock_result = MagicMock()
        mock_result.returncode = 0

        with patch("app.agents.adapter.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            result = adapter.launch(context="test context")

            # subprocess.run called with list, shell=False
            mock_run.assert_called_once()
            call_args = mock_run.call_args
            # shell=False is in kwargs or positional args[1]
            shell_val = call_args.kwargs.get("shell")
            if shell_val is None:
                shell_val = call_args[1].get("shell") if len(call_args) > 1 else None
            assert shell_val is False, f"Expected shell=False, got {shell_val}"

            # command should be a list (first positional arg)
            cmd_arg = call_args[0][0] if call_args[0] else call_args[1].get("args")
            assert isinstance(cmd_arg, list)

        assert isinstance(result, AgentLaunchResult)
        assert result.exit_code == 0


class TestInteractiveLaunch:
    """Regression: interactive agents must inherit the parent console.

    Passing stdin=sys.stdin / stdout=sys.stdout to subprocess.run on
    Windows does NOT properly inherit console handles — the child sees
    a non-TTY pipe.  The fix is to omit these arguments (None = inherit).
    """

    def _make_adapter(self) -> CodexLaunchAdapter:
        from app.agents.adapters.codex import CodexLaunchAdapter

        adapter = CodexLaunchAdapter()
        adapter._executable = Path("C:/fake/codex.exe")
        adapter._detected = True
        return adapter

    def test_no_stdin_pipe(self):
        """launch() must not pass stdin=sys.stdin (causes TTY loss)."""
        from unittest.mock import patch, MagicMock

        adapter = self._make_adapter()
        mock_result = MagicMock(returncode=0)

        with patch("app.agents.adapter.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            adapter.launch(context="test")

            call_kwargs = mock_run.call_args.kwargs
            assert "stdin" not in call_kwargs, (
                f"stdin must not be passed (got {call_kwargs.get('stdin')})"
            )

    def test_no_stdout_pipe(self):
        """launch() must not pass stdout=sys.stdout (causes TTY loss)."""
        from unittest.mock import patch, MagicMock

        adapter = self._make_adapter()
        mock_result = MagicMock(returncode=0)

        with patch("app.agents.adapter.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            adapter.launch(context="test")

            call_kwargs = mock_run.call_args.kwargs
            assert "stdout" not in call_kwargs, (
                f"stdout must not be passed (got {call_kwargs.get('stdout')})"
            )

    def test_no_stderr_pipe(self):
        """launch() must not pass stderr=sys.stderr (causes TTY loss)."""
        from unittest.mock import patch, MagicMock

        adapter = self._make_adapter()
        mock_result = MagicMock(returncode=0)

        with patch("app.agents.adapter.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            adapter.launch(context="test")

            call_kwargs = mock_run.call_args.kwargs
            assert "stderr" not in call_kwargs, (
                f"stderr must not be passed (got {call_kwargs.get('stderr')})"
            )

    def test_context_in_argv(self):
        """Munin briefing is passed as a positional argument, not via input."""
        from unittest.mock import patch, MagicMock

        adapter = self._make_adapter()
        mock_result = MagicMock(returncode=0)

        with patch("app.agents.adapter.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            adapter.launch(context="[MUNIN BRIEFING HERE]")

            cmd_arg = mock_run.call_args[0][0]
            assert isinstance(cmd_arg, list)
            # Briefing should be in the argv, not in stdin/input kwargs
            assert any("[MUNIN BRIEFING HERE]" in a for a in cmd_arg)
            assert "input" not in mock_run.call_args.kwargs

    def test_exit_code_preserved(self):
        """Child exit code is returned in the result."""
        from unittest.mock import patch, MagicMock

        adapter = self._make_adapter()
        mock_result = MagicMock(returncode=42)

        with patch("app.agents.adapter.subprocess.run") as mock_run:
            mock_run.return_value = mock_result
            result = adapter.launch(context="test")

        assert result.exit_code == 42

    def test_keyboard_interrupt_safe(self):
        """KeyboardInterrupt during launch is caught cleanly."""
        from unittest.mock import patch, MagicMock
        from app.agents.types import AgentLaunchResult

        adapter = self._make_adapter()

        with patch("app.agents.adapter.subprocess.run", side_effect=KeyboardInterrupt):
            result = adapter.launch(context="test")

        assert isinstance(result, AgentLaunchResult)
        assert result.success is False
        assert "Interrupted" in result.error

    def test_cmd_uses_shell_true(self):
        """On Windows, .cmd/.bat executables use shell=True."""
        import sys
        from unittest.mock import patch, MagicMock
        from app.agents.adapters.kilo import KiloLaunchAdapter

        adapter = KiloLaunchAdapter()
        # Fake a .cmd executable
        adapter._executable = Path("C:/fake/kilo.cmd")
        adapter._detected = True

        mock_result = MagicMock(returncode=0)

        with patch("app.agents.adapter.subprocess.run") as mock_run, \
             patch("app.agents.adapter.sys.platform", "win32"):
            mock_run.return_value = mock_result
            adapter.launch(context="test")

            call_kwargs = mock_run.call_args.kwargs
            assert call_kwargs.get("shell") is True
