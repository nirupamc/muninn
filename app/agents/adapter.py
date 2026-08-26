"""Agent launch adapter contract for M8.3B."""

from __future__ import annotations

import logging
import shlex
import subprocess
import sys
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.agents.types import (
    AgentInfo,
    AgentLaunchResult,
    AgentStatus,
    AgentType,
    InjectionCapability,
)

logger = logging.getLogger("munin.agents.adapter")


class AgentLaunchAdapter(ABC):
    """Base class for agent launch adapters.

    Adapters are responsible for:
    1. Detecting if the agent is installed
    2. Determining the best context injection mechanism
    3. Building the launch command
    4. Launching the agent with context

    Do not create a giant plugin framework. Keep this focused.
    """

    # Agent type identifier
    agent_type: AgentType

    # Human-readable name
    name: str

    # Agent status when detected
    status: AgentStatus = AgentStatus.NOT_INSTALLED

    # Supported injection capabilities
    capabilities: set[InjectionCapability] = set()

    # Description for CLI output
    description: str = ""

    @abstractmethod
    def available(self) -> bool:
        """Check if this adapter's agent is available/installed."""
        ...

    @abstractmethod
    def detect(self) -> AgentInfo:
        """Detect agent installation and return detailed info."""
        ...

    @abstractmethod
    def get_executable(self) -> str | Path | None:
        """Get the executable path for this agent."""
        ...

    @abstractmethod
    def build_command(
        self,
        context: str,
        project_path: str | Path | None = None,
        task: str | None = None,
        extra_args: list[str] | None = None,
    ) -> list[str]:
        """Build the command to launch the agent with context.

        Args:
            context: The Munin briefing/context to inject
            project_path: The resolved project path
            task: Optional task description for context targeting
            extra_args: Additional arguments to pass to the agent

        Returns:
            Command as list of strings for subprocess
        """
        ...

    @abstractmethod
    def get_injection_mechanism(self) -> str:
        """Describe the context injection mechanism used."""
        ...

    def launch(
        self,
        context: str,
        project_path: str | Path | None = None,
        task: str | None = None,
        extra_args: list[str] | None = None,
    ) -> AgentLaunchResult:
        """Launch the agent with context injection.

        Default implementation uses subprocess with the built command.
        Adapters may override for custom launch behavior.
        """
        command = self.build_command(context, project_path, task, extra_args)
        injection = self.get_injection_mechanism()

        # Determine whether we need shell=True (.cmd/.bat on Windows)
        needs_shell = False
        if sys.platform == "win32" and command:
            exe_str = str(command[0]).lower()
            needs_shell = exe_str.endswith(".cmd") or exe_str.endswith(".bat")

        logger.info(
            "Launching %s injection=%s shell=%s cmd_preview=%s",
            self.name,
            injection,
            needs_shell,
            " ".join(shlex.quote(c) for c in command),
        )

        try:
            # Pass stdin/stdout/stderr as None so the child inherits the
            # parent's console handles directly.  This keeps the terminal
            # interactive (no 'stdin is not a terminal' error).
            if needs_shell:
                # .cmd/.bat must go through the shell
                cmd_str = " ".join(shlex.quote(arg) for arg in command)
                result = subprocess.run(
                    cmd_str,
                    shell=True,
                    check=False,
                )
            else:
                # Preferred path: argument list, no shell interpretation
                result = subprocess.run(
                    command,
                    shell=False,
                    check=False,
                )

            return AgentLaunchResult(
                success=True,
                agent_name=self.name,
                exit_code=result.returncode,
                command=" ".join(command) if isinstance(command, list) else command,
                injection_mechanism=injection,
                briefing=context,
            )

        except KeyboardInterrupt:
            logger.info("Launch of %s interrupted by user", self.name)
            return AgentLaunchResult(
                success=False,
                agent_name=self.name,
                exit_code=None,
                error="Interrupted by user",
                injection_mechanism=injection,
            )

        except Exception as e:
            logger.error("Failed to launch %s: %s", self.name, e)
            return AgentLaunchResult(
                success=False,
                agent_name=self.name,
                exit_code=None,
                error=str(e),
                injection_mechanism=injection,
            )

    # _quote_command_for_windows removed — use shlex.quote for display only

    def dry_run(
        self,
        context: str,
        project_path: str | Path | None = None,
        task: str | None = None,
        extra_args: list[str] | None = None,
    ) -> dict[str, Any]:
        """Perform a dry run and return diagnostics without launching."""
        executable = self.get_executable()
        command = self.build_command(context, project_path, task, extra_args)
        injection = self.get_injection_mechanism()

        return {
            "agent": self.name,
            "agent_type": self.agent_type.value,
            "status": self.status.value,
            "executable": str(executable) if executable else None,
            "available": self.available(),
            "capabilities": [c.value for c in self.capabilities],
            "injection_mechanism": injection,
            "command": command,
            "command_string": " ".join(command) if isinstance(command, list) else command,
            "briefing_length": len(context),
            "briefing_preview": context[:200] + "..." if len(context) > 200 else context,
        }
