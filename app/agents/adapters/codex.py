"""Codex launch adapter for M8.3B.

VERIFIED: Codex CLI installed at C:/Users/Tantech LLC/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe
Supports: codex [PROMPT] - initial prompt as argument
Also supports: codex exec [PROMPT] for non-interactive
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from app.agents.types import (
    AgentInfo,
    AgentStatus,
    AgentType,
    InjectionCapability,
)
from app.agents.adapters.base import AgentLaunchAdapter

logger = logging.getLogger("munin.agents.codex")


class CodexLaunchAdapter(AgentLaunchAdapter):
    """Codex agent launch adapter.

    Integration status: VERIFIED_LOG_ADAPTER (session capture) + VERIFIED (launch)
    Context injection: Initial prompt argument
    """

    agent_type = AgentType.codex
    name = "Codex"
    description = "OpenAI Codex coding agent"
    status = AgentStatus.INSTALLED_SUPPORTED
    capabilities = {
        InjectionCapability.supports_initial_prompt,
        InjectionCapability.supports_stdin,
    }

    def __init__(self) -> None:
        self._executable: Path | None = None
        self._version: str | None = None
        self._detected = False

    def available(self) -> bool:
        """Check if Codex is installed."""
        if not self._detected:
            self._detect_executable()
        return self._executable is not None and self._executable.exists()

    def _detect_executable(self) -> None:
        """Find the Codex executable."""
        # Known installation paths on Windows
        candidates = [
            Path("C:/Users/Tantech LLC/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe"),
            Path("C:/Program Files/Codex/bin/codex.exe"),
            Path.home() / ".codex" / "bin" / "codex.exe",
        ]

        # Also check PATH
        for path_str in self._get_path_executables("codex"):
            candidates.append(Path(path_str))

        for candidate in candidates:
            if candidate.exists():
                self._executable = candidate
                self._detected = True
                logger.info("Found Codex at: %s", self._executable)
                return

        self._executable = None
        self._detected = True

    def _get_path_executables(self, name: str) -> list[str]:
        """Get executable paths from PATH environment variable."""
        import os

        executables = []
        if "PATH" in os.environ:
            for path_dir in os.environ["PATH"].split(os.pathsep):
                for ext in ["", ".exe", ".cmd", ".bat"]:
                    full_path = os.path.join(path_dir, name + ext)
                    if os.path.exists(full_path):
                        executables.append(full_path)
        return executables

    def detect(self) -> AgentInfo:
        """Detect Codex installation."""
        self.available()  # Ensure detection

        return AgentInfo(
            name=self.name,
            agent_type=self.agent_type,
            executable_path=self._executable,
            version=self._version,
            status=self.status if self._executable else AgentStatus.NOT_INSTALLED,
            capabilities=self.capabilities,
            launch_command=str(self._executable) if self._executable else None,
            description=self.description,
        )

    def get_executable(self) -> str | Path | None:
        """Get the Codex executable path."""
        if not self._detected:
            self._detect_executable()
        return self._executable

    def build_command(
        self,
        context: str,
        project_path: str | Path | None = None,
        task: str | None = None,
        extra_args: list[str] | None = None,
    ) -> list[str]:
        """Build the Codex launch command.

        Uses: codex [PROMPT]
        The prompt is passed as the first positional argument.
        """
        executable = self.get_executable()
        if not executable:
            raise RuntimeError("Codex executable not found")

        # Build the prompt combining task and context
        if task:
            full_prompt = f"{task}\n\n{context}"
        else:
            full_prompt = context

        command = [str(executable), full_prompt]

        # Add extra arguments if provided
        if extra_args:
            command.extend(extra_args)

        # If a project path is specified, we should change to that directory
        # Codex uses the current working directory
        # We'll handle this at launch time, not in the command

        return command

    def get_injection_mechanism(self) -> str:
        """Codex context injection mechanism."""
        return "initial_prompt_argument"

    def dry_run(
        self,
        context: str,
        project_path: str | Path | None = None,
        task: str | None = None,
        extra_args: list[str] | None = None,
    ) -> dict[str, Any]:
        """Dry run for Codex launch."""
        result = super().dry_run(context, project_path, task, extra_args)
        result["executable_path"] = str(self._executable) if self._executable else None
        result["version"] = self._version
        return result
