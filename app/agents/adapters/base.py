"""Base agent launch adapter for M8.3B.

This is a minimal abstraction - do not create a giant plugin framework.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.agents.adapter import AgentLaunchAdapter as BaseAgentLaunchAdapter
from app.agents.types import (
    AgentInfo,
    AgentLaunchResult,
    AgentStatus,
    AgentType,
    InjectionCapability,
)


class AgentLaunchAdapter(BaseAgentLaunchAdapter, ABC):
    """Concrete base class with common functionality.

    Subclasses should only need to implement:
    - agent_type
    - name
    - description
    - available()
    - detect()
    - get_executable()
    - build_command()
    - get_injection_mechanism()
    """

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
        """Build the command to launch the agent with context."""
        ...

    @abstractmethod
    def get_injection_mechanism(self) -> str:
        """Describe the context injection mechanism used."""
        ...
