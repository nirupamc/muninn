"""OpenCode launch adapter for M8.3B.

VERIFIED: OpenCode installed at C:/Users/Tantech LLC/AppData/Roaming/npm/opencode.cmd
Supports: opencode run [message..] - run with initial message
Also supports: opencode [project] - interactive TUI
Also supports: --prompt option
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

logger = logging.getLogger("munin.agents.opencode")


class OpenCodeLaunchAdapter(AgentLaunchAdapter):
    """OpenCode agent launch adapter.

    Integration status: VERIFIED (executable found)
    Context injection: opencode run [message..] with initial message, or --prompt
    """

    agent_type = AgentType.opencode
    name = "OpenCode"
    description = "OpenCode coding agent"
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
        """Check if OpenCode is installed."""
        if not self._detected:
            self._detect_executable()
        return self._executable is not None and self._executable.exists()

    def _detect_executable(self) -> None:
        """Find the OpenCode executable."""
        # Known installation paths
        candidates = [
            # npm global install on Windows
            Path("C:/Users/Tantech LLC/AppData/Roaming/npm/opencode.cmd"),
            Path("C:/Program Files/nodejs/opencode.cmd"),
            # Check common npm prefix paths
            Path(os.environ.get("APPDATA", "")) / "npm" / "opencode.cmd",
        ]

        # Also check PATH
        for path_str in self._get_path_executables("opencode"):
            candidates.append(Path(path_str))

        for candidate in candidates:
            if candidate.exists():
                self._executable = candidate
                self._detected = True
                logger.info("Found OpenCode at: %s", self._executable)
                return

        self._executable = None
        self._detected = True

    def _get_path_executables(self, name: str) -> list[str]:
        """Get executable paths from PATH environment variable."""
        executables = []
        if "PATH" in os.environ:
            for path_dir in os.environ["PATH"].split(os.pathsep):
                for ext in ["", ".cmd", ".bat", ".exe"]:
                    full_path = os.path.join(path_dir, name + ext)
                    if os.path.exists(full_path):
                        executables.append(full_path)
        return executables

    def detect(self) -> AgentInfo:
        """Detect OpenCode installation."""
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
        """Get the OpenCode executable path."""
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
        """Build the OpenCode launch command.

        Uses: opencode run [message..]
        The message is passed as arguments after 'run'.
        Alternative: opencode --prompt "message" [project]
        """
        executable = self.get_executable()
        if not executable:
            raise RuntimeError("OpenCode executable not found")

        # Use the 'run' subcommand with message
        command = [str(executable), "run"]

        # Build the message combining task and context
        if task:
            full_message = f"{task}\n\n{context}"
        else:
            full_message = context

        # Add the message as arguments
        command.append(full_message)

        # Add extra arguments if provided
        if extra_args:
            command.extend(extra_args)

        # If a project path is specified, add it
        if project_path:
            command.append(str(project_path))

        return command

    def get_injection_mechanism(self) -> str:
        """OpenCode context injection mechanism."""
        return "run_command_message"
