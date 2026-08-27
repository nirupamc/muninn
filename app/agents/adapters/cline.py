"""Cline launch adapter for M8.3C.

Cline CLI is installed at: C:/Users/Tantech LLC/AppData/Roaming/npm/cline.CMD
Supports: cline [PROMPT] for non-interactive mode
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from app.agents.types import (
    AgentInfo,
    AgentStatus,
    AgentType,
    InjectionCapability,
)
from app.agents.adapters.base import AgentLaunchAdapter

logger = logging.getLogger("munin.agents.cline")


class ClineLaunchAdapter(AgentLaunchAdapter):
    """Cline agent launch adapter.

    Context injection: Initial prompt argument
    """

    agent_type = AgentType.cline
    name = "Cline"
    description = "Cline AI coding assistant (CLI)"
    status = AgentStatus.INSTALLED_SUPPORTED
    capabilities = {
        InjectionCapability.supports_initial_prompt,
        InjectionCapability.supports_stdin,
    }

    def __init__(self) -> None:
        self._executable: str | None = None
        self._version: str | None = None
        self._detected = False

    def available(self) -> bool:
        """Check if Cline is installed."""
        if not self._detected:
            self._detect_executable()
        return self._executable is not None

    def _detect_executable(self) -> None:
        """Find the Cline executable."""
        candidates = ["cline", "cline.cmd", "cline.exe"]

        for exe in candidates:
            path = shutil.which(exe)
            if path:
                self._executable = path
                self._detected = True
                logger.info("Found Cline at: %s", self._executable)
                return

        # Check npm global
        npm_path = Path.home() / "AppData" / "Roaming" / "npm" / "cline.cmd"
        if npm_path.exists():
            self._executable = str(npm_path)
            self._detected = True
            logger.info("Found Cline at: %s", self._executable)
            return

        self._executable = None
        self._detected = True

    def detect(self) -> AgentInfo:
        """Detect Cline installation."""
        self.available()
        return AgentInfo(
            name=self.name,
            agent_type=self.agent_type,
            executable_path=Path(self._executable) if self._executable else None,
            version=self._version,
            status=self.status if self._executable else AgentStatus.NOT_INSTALLED,
            capabilities=self.capabilities,
            launch_command=self._executable,
            description=self.description,
        )

    def get_executable(self) -> str | Path | None:
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
        """Build the Cline launch command."""
        executable = self.get_executable()
        if not executable:
            raise RuntimeError("Cline executable not found")

        if task:
            full_prompt = f"{task}\n\n{context}"
        else:
            full_prompt = context

        command = [str(executable), full_prompt]

        if extra_args:
            command.extend(extra_args)

        return command

    def get_injection_mechanism(self) -> str:
        return "initial_prompt_argument"

    def dry_run(
        self,
        context: str,
        project_path: str | Path | None = None,
        task: str | None = None,
        extra_args: list[str] | None = None,
    ) -> dict[str, Any]:
        result = super().dry_run(context, project_path, task, extra_args)
        result["executable_path"] = self._executable
        return result
