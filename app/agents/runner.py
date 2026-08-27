"""Agent runner for M8.3B — Universal Agent Context Injection.

Orchestrates:
  1. Project resolution (cwd / --project / registry)
  2. M5 context assembly (reuse existing ContextService)
  3. Briefing formatting (MuninProjectBriefing)
  4. Agent detection + launch (AgentLaunchAdapter)
  5. Dry-run diagnostics
"""

from __future__ import annotations

import logging
import os
import signal
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.agents.types import AgentLaunchResult

logger = logging.getLogger("munin.agents.runner")


@dataclass
class RunConfig:
    """Configuration for an agent run."""

    agent_name: str
    project_path: str | None = None
    project_id: str | None = None
    namespace: str | None = None
    task: str | None = None
    extra_args: list[str] = field(default_factory=list)
    dry_run: bool = False
    token_budget: int = 1500
    max_memories: int = 20


class AgentRunner:
    """Orchestrates launching a coding agent with Munin context injection."""

    def __init__(self, config: RunConfig) -> None:
        self.config = config
        self._resolved_project_path: Path | None = None
        self._resolved_namespace: str | None = None
        self._resolved_project_name: str | None = None

    def run(self) -> AgentLaunchResult:
        """Execute the full run pipeline: resolve → context → briefing → launch."""
        try:
            # Step 1: Resolve project
            self._resolve_project()

            # Step 2: Get adapter
            adapter = self._get_adapter()
            if adapter is None:
                return AgentLaunchResult(
                    success=False,
                    agent_name=self.config.agent_name,
                    error=f"Agent '{self.config.agent_name}' not found or not installed. "
                    "Run 'munin agents' to see available agents.",
                )

            # Step 3: Assemble context via M5
            context_text, context_response = self._assemble_context()

            # Step 4: Build briefing
            briefing = self._build_briefing(context_text, context_response)

            # Step 5: Dry run or actual launch
            if self.config.dry_run:
                return self._dry_run(adapter, briefing, context_response)

            return self._launch(adapter, briefing)

        except KeyboardInterrupt:
            logger.info("Run interrupted by user")
            return AgentLaunchResult(
                success=False,
                agent_name=self.config.agent_name,
                error="Interrupted by user",
            )
        except Exception as e:
            logger.error("Run failed: %s", e, exc_info=True)
            return AgentLaunchResult(
                success=False,
                agent_name=self.config.agent_name,
                error=str(e),
            )

    # ------------------------------------------------------------------
    # Step 1: Project resolution
    # ------------------------------------------------------------------

    def _resolve_project(self) -> None:
        """Resolve project from --project, cwd, or registry.

        Resolution order:
          1. explicit --project (path or namespace)
          2. current working directory → registry lookup
          3. nearest registered project root
        """
        logger.info(
            "[_resolve_project] START project_path=%r project_id=%r namespace=%r cwd=%s",
            self.config.project_path,
            self.config.project_id,
            self.config.namespace,
            os.getcwd(),
        )
        # 1. Explicit --project argument
        if self.config.project_path:
            resolved = self._resolve_explicit_project(self.config.project_path)
            if resolved:
                logger.info(
                    "[_resolve_project] RESOLVED via explicit path: namespace=%r name=%r path=%r",
                    self._resolved_namespace,
                    self._resolved_project_name,
                    self._resolved_project_path,
                )
                return

        # 2. Try current working directory
        cwd = os.getcwd()
        resolved = self._resolve_from_path(cwd)
        if resolved:
            logger.info(
                "[_resolve_project] RESOLVED via cwd: namespace=%r name=%r",
                self._resolved_namespace,
                self._resolved_project_name,
            )
            return

        # 3. No project resolved — proceed without one (namespace = "default")
        self._resolved_namespace = self.config.namespace or "default"
        self._resolved_project_name = Path(cwd).name
        self._resolved_project_path = Path(cwd)
        logger.info(
            "[_resolve_project] FALLBACK to cwd: namespace=%r name=%r",
            self._resolved_namespace,
            self._resolved_project_name,
        )

    def _resolve_explicit_project(self, project_arg: str) -> bool:
        """Resolve an explicit --project argument (path or namespace)."""
        # Try as filesystem path first
        path = Path(project_arg)
        if path.exists() or project_arg.startswith(("C:", "D:", "E:", "/")):
            return self._resolve_from_path(str(path))

        # Try as namespace
        try:
            from app.database import SessionLocal
            from app.capture.project_resolver import ProjectResolver

            db = SessionLocal()
            try:
                resolver = ProjectResolver(db)
                project = resolver.resolve_by_namespace(project_arg)
                if project:
                    self._resolved_project_path = Path(project.canonical_path)
                    self._resolved_namespace = project.namespace
                    self._resolved_project_name = project.name
                    logger.info(
                        "Resolved project by namespace: %s (path=%s)",
                        project.namespace,
                        project.canonical_path,
                    )
                    return True
            finally:
                db.close()
        except Exception as e:
            logger.debug("Namespace lookup failed for %s: %s", project_arg, e)

        # Try as project ID
        if self.config.project_id:
            return self._resolve_from_id(self.config.project_id)

        return False

    def _resolve_from_path(self, path_str: str) -> bool:
        """Resolve project from a filesystem path."""
        canonical = str(Path(path_str).resolve())
        try:
            from app.database import SessionLocal
            from app.capture.project_resolver import ProjectResolver

            db = SessionLocal()
            try:
                resolver = ProjectResolver(db)
                project = resolver.resolve_by_path(canonical)
                if project:
                    self._resolved_project_path = Path(project.canonical_path)
                    self._resolved_namespace = project.namespace
                    self._resolved_project_name = project.name
                    logger.info(
                        "Resolved project from path %s: namespace=%s name=%s",
                        canonical,
                        project.namespace,
                        project.name,
                    )
                    return True
            finally:
                db.close()
        except Exception as e:
            logger.debug("Path resolution failed for %s: %s", canonical, e)

        # Walk up looking for registered projects
        try:
            from app.database import SessionLocal
            from app.projects.repository import ProjectRepository

            db = SessionLocal()
            try:
                repo = ProjectRepository(db)
                current = Path(canonical)
                while current != current.parent:
                    project = repo.get_by_canonical_path(str(current))
                    if project:
                        self._resolved_project_path = Path(project.canonical_path)
                        self._resolved_namespace = project.namespace
                        self._resolved_project_name = project.name
                        logger.info(
                            "Resolved project by walking up to %s: namespace=%s",
                            current,
                            project.namespace,
                        )
                        return True
                    current = current.parent
            finally:
                db.close()
        except Exception as e:
            logger.debug("Walk-up resolution failed: %s", e)

        return False

    def _resolve_from_id(self, project_id: str) -> bool:
        """Resolve project from a project ID."""
        try:
            from app.database import SessionLocal
            from app.projects.repository import ProjectRepository

            db = SessionLocal()
            try:
                repo = ProjectRepository(db)
                project = repo.get(project_id)
                if project:
                    self._resolved_project_path = Path(project.canonical_path)
                    self._resolved_namespace = project.namespace
                    self._resolved_project_name = project.name
                    return True
            finally:
                db.close()
        except Exception as e:
            logger.debug("ID resolution failed for %s: %s", project_id, e)

        return False

    # ------------------------------------------------------------------
    # Step 2: Agent adapter
    # ------------------------------------------------------------------

    def _get_adapter(self) -> Any:
        """Get the launch adapter for the configured agent."""
        from app.agents.registry import get_registry

        registry = get_registry()
        try:
            adapter = registry.get_adapter(self.config.agent_name)
        except (ValueError, KeyError):
            # Unknown agent name
            supported = registry.get_supported_types()
            logger.error(
                "Unknown agent '%s'. Supported: %s",
                self.config.agent_name,
                ", ".join(supported),
            )
            return None

        if adapter is None:
            return None

        # Check availability
        if not adapter.available():
            logger.warning(
                "Agent '%s' adapter found but not available (not installed?)",
                self.config.agent_name,
            )
            # Still return it — dry_run should work, launch will fail gracefully

        return adapter

    # ------------------------------------------------------------------
    # Step 3: M5 context assembly
    # ------------------------------------------------------------------

    def _assemble_context(self) -> tuple[str, Any]:
        """Assemble context using the existing M5 ContextService.

        Returns (context_text, context_response).
        """
        namespace = self._resolved_namespace or "default"

        # Build a query from task or use a generic one
        query = self.config.task or f"project context for {self._resolved_project_name or 'current project'}"

        logger.info(
            "[_assemble_context] START namespace=%r query=%r token_budget=%d max_memories=%d",
            namespace,
            query,
            self.config.token_budget,
            self.config.max_memories,
        )

        try:
            from app.database import SessionLocal
            from app.context.service import ContextService
            from app.schemas.context import ContextRequest

            db = SessionLocal()
            try:
                service = ContextService(db)
                provider = service.provider
                logger.info(
                    "[_assemble_context] provider=%s model=%s dimension=%s",
                    getattr(provider, "provider_name", "?"),
                    getattr(provider, "model_name", "?"),
                    getattr(provider, "dimension", "?"),
                )
                request = ContextRequest(
                    query=query,
                    namespace=namespace,
                    token_budget=self.config.token_budget,
                    max_memories=self.config.max_memories,
                )
                response = service.assemble(request)
                logger.info(
                    "[_assemble_context] RESULT memories=%d tokens=%d truncated=%s context_len=%d",
                    len(response.memories_used),
                    response.estimated_tokens,
                    response.truncated,
                    len(response.context),
                )
                if response.memories_used:
                    for i, mem in enumerate(response.memories_used):
                        logger.info(
                            "[_assemble_context]   memory[%d] id=%s type=%s score=%.3f content_preview=%.80s",
                            i,
                            mem.memory_id,
                            mem.memory_type,
                            mem.final_score,
                            mem.content,
                        )
                else:
                    # Check if stored embeddings use a different provider
                    from sqlalchemy import func, text as sa_text
                    mismatch_check = db.execute(
                        sa_text(
                            "SELECT provider, model_name, dimension, COUNT(*) "
                            "FROM memory_embeddings "
                            "WHERE memory_id IN "
                            "  (SELECT id FROM memories WHERE namespace = :ns) "
                            "GROUP BY provider, model_name, dimension"
                        ),
                        {"ns": namespace},
                    ).fetchall()
                    if mismatch_check:
                        stored_info = ", ".join(
                            f"provider={r[0]} model={r[1]} dim={r[2]} ({r[3]} embeddings)"
                            for r in mismatch_check
                        )
                        logger.warning(
                            "[_assemble_context] ZERO memories for namespace=%r. "
                            "Provider MISMATCH detected! Active provider=%s/%s/dim=%d, "
                            "but stored embeddings use: %s. "
                            "Run 'munin embed-memories' to re-embed with the active provider.",
                            namespace,
                            provider.provider_name,
                            provider.model_name,
                            provider.dimension,
                            stored_info,
                        )
                    else:
                        logger.warning(
                            "[_assemble_context] ZERO memories returned for namespace=%r — "
                            "no embeddings found. Check DB content.",
                            namespace,
                        )
                return response.context, response
            finally:
                db.close()
        except Exception as e:
            logger.error(
                "[_assemble_context] EXCEPTION (falling back to empty): %s",
                e,
                exc_info=True,
            )
            # Return empty context — don't fail the entire run
            from app.schemas.context import ContextResponse
            empty = ContextResponse(
                query=query,
                namespace=namespace,
                context="",
                token_budget=self.config.token_budget,
                estimated_tokens=0,
                truncated=False,
                memories_used=[],
            )
            return "", empty

    # ------------------------------------------------------------------
    # Step 4: Briefing
    # ------------------------------------------------------------------

    def _build_briefing(
        self, context_text: str, context_response: Any
    ) -> str:
        """Build a MuninProjectBriefing and return its text."""
        from app.agents.briefing import (
            BriefingFormatter,
            create_project_briefing,
        )
        from app.sdk.models import AgentContext, MuninMemory

        logger.info(
            "[_build_briefing] START project=%r namespace=%r context_response.memories_used=%d",
            self._resolved_project_name,
            self._resolved_namespace,
            len(context_response.memories_used),
        )

        # Convert ContextResponse memories to AgentContext for briefing
        memories = []
        for mem in context_response.memories_used:
            memories.append(
                MuninMemory(
                    memory_id=mem.memory_id,
                    memory_type=mem.memory_type.value if hasattr(mem.memory_type, "value") else str(mem.memory_type),
                    content=mem.content,
                    score=mem.final_score,
                )
            )

        agent_context = AgentContext(
            query=context_response.query,
            namespace=context_response.namespace,
            text=context_text,
            estimated_tokens=context_response.estimated_tokens,
            truncated=context_response.truncated,
            memories_used=memories,
        )

        briefing = create_project_briefing(
            project_name=self._resolved_project_name or "Unknown Project",
            project_path=str(self._resolved_project_path) if self._resolved_project_path else None,
            namespace=self._resolved_namespace,
            context=agent_context,
        )

        logger.info(
            "[_build_briefing] RESULT memory_count=%d briefing_len=%d",
            briefing.memory_count,
            len(briefing.briefing_text),
        )

        return briefing.briefing_text

    # ------------------------------------------------------------------
    # Step 5a: Dry run
    # ------------------------------------------------------------------

    def _dry_run(
        self, adapter: Any, briefing: str, context_response: Any
    ) -> AgentLaunchResult:
        """Perform a dry run showing diagnostics without launching."""
        print("\n" + "=" * 70)
        print("MUNIN AGENT RUN — DRY RUN")
        print("=" * 70)

        # Project info
        print(f"\n  Resolved project: {self._resolved_project_name or '(none)'}")
        print(f"  Project path:     {self._resolved_project_path or '(none)'}")
        print(f"  Namespace:        {self._resolved_namespace or 'default'}")

        # Context info
        print(f"\n  Context memories: {len(context_response.memories_used)}")
        print(f"  Context tokens:   {context_response.estimated_tokens}")
        print(f"  Token budget:     {self.config.token_budget}")
        print(f"  Truncated:        {context_response.truncated}")

        if self.config.task:
            print(f"  Task:             {self.config.task}")

        # Agent info
        print(f"\n  Agent:            {adapter.name}")
        print(f"  Agent type:       {adapter.agent_type.value}")
        print(f"  Available:        {adapter.available()}")
        executable = adapter.get_executable()
        print(f"  Executable:       {executable or '(not found)'}")
        print(f"  Injection:        {adapter.get_injection_mechanism()}")
        print(f"  Capabilities:     {[c.value for c in adapter.capabilities]}")

        # Command
        try:
            command = adapter.build_command(
                context=briefing,
                project_path=str(self._resolved_project_path) if self._resolved_project_path else None,
                task=self.config.task,
                extra_args=self.config.extra_args,
            )
            cmd_display = " ".join(str(c) for c in command)
            # Truncate very long commands for display
            if len(cmd_display) > 200:
                cmd_display = cmd_display[:200] + "..."
            print(f"\n  Launch command:   {cmd_display}")
        except Exception as e:
            print(f"\n  Command build error: {e}")

        # Briefing preview
        preview_lines = briefing.split("\n")[:10]
        print(f"\n  Briefing preview ({len(briefing)} chars):")
        for line in preview_lines:
            print(f"    {line}")
        if len(briefing.split("\n")) > 10:
            print(f"    ... ({len(briefing.split(chr(10)))} total lines)")

        print("\n" + "=" * 70)
        print("  (dry run — no agent launched)")
        print("=" * 70 + "\n")

        return AgentLaunchResult(
            success=True,
            agent_name=adapter.name,
            command=" ".join(str(c) for c in command) if command else None,
            briefing=briefing,
            project_id=self.config.project_id,
            namespace=self._resolved_namespace,
            context_tokens=context_response.estimated_tokens,
            injection_mechanism=adapter.get_injection_mechanism(),
        )

    # ------------------------------------------------------------------
    # Step 5b: Actual launch
    # ------------------------------------------------------------------

    def _launch(self, adapter: Any, briefing: str) -> AgentLaunchResult:
        """Launch the agent with context injection."""
        # Set up Ctrl+C handling
        original_handler = signal.getsignal(signal.SIGINT)

        logger.info(
            "[_launch] BRIEFING len=%d preview=%.200s",
            len(briefing),
            briefing,
        )

        def _sigint_handler(signum: int, frame: Any) -> None:
            """Forward SIGINT to child process."""
            logger.info("SIGINT received, forwarding to child...")
            # The adapter's subprocess.run will handle it

        try:
            signal.signal(signal.SIGINT, _sigint_handler)

            print(f"\nLaunching {adapter.name} with Munin context...")
            print(f"  Project: {self._resolved_project_name or '(none)'}")
            print(f"  Namespace: {self._resolved_namespace or 'default'}")
            print(f"  Injection: {adapter.get_injection_mechanism()}")
            print()

            # Change to project directory if resolved
            original_cwd = os.getcwd()
            if self._resolved_project_path and self._resolved_project_path.exists():
                os.chdir(str(self._resolved_project_path))
                logger.info("Changed CWD to: %s", self._resolved_project_path)

            result = adapter.launch(
                context=briefing,
                project_path=str(self._resolved_project_path) if self._resolved_project_path else None,
                task=self.config.task,
                extra_args=self.config.extra_args,
            )

            return result

        except Exception as e:
            logger.error("Launch failed: %s", e)
            return AgentLaunchResult(
                success=False,
                agent_name=adapter.name,
                error=str(e),
            )
        finally:
            # Restore original CWD and signal handler
            try:
                os.chdir(original_cwd)
            except Exception:
                pass
            try:
                signal.signal(signal.SIGINT, original_handler)
            except Exception:
                pass
