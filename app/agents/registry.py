"""Agent registry and detector for M8.3B.

Discovers installed coding agents and provides status information.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from app.agents.types import (
    AgentInfo,
    AgentStatus,
    AgentType,
    InjectionCapability,
)

logger = logging.getLogger("munin.agents.registry")


class AgentCategory(str, Enum):
    """Category of coding agent."""

    CODING = "coding"
    CHAT = "chat"
    ANALYSIS = "analysis"
    UNKNOWN = "unknown"


@dataclass
class DetectedAgent:
    """Information about a detected agent."""

    name: str
    agent_type: AgentType
    executable_path: Path | None = None
    version: str | None = None
    status: AgentStatus = AgentStatus.NOT_INSTALLED
    capabilities: set[InjectionCapability] = field(default_factory=set)
    launch_command: str | None = None
    description: str = ""
    category: AgentCategory = AgentCategory.CODING


class AgentRegistry:
    """Registry of all supported agents.

    Discovers installed agents and provides status information.
    """

    # All supported agent types with their adapters
    SUPPORTED_AGENTS: dict[AgentType, type] = {}

    @classmethod
    def register_adapter(cls, agent_type: AgentType, adapter_class: type) -> None:
        """Register an adapter class for an agent type."""
        cls.SUPPORTED_AGENTS[agent_type] = adapter_class

    def __init__(self) -> None:
        """Initialize the registry."""
        self._detected_agents: dict[str, DetectedAgent] = {}
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Lazy initialization of adapters."""
        if self._initialized:
            return

        # Import and register all adapters
        try:
            from app.agents.adapters.aider import AiderLaunchAdapter
            from app.agents.adapters.cline import ClineLaunchAdapter
            from app.agents.adapters.codex import CodexLaunchAdapter
            from app.agents.adapters.kilo import KiloLaunchAdapter
            from app.agents.adapters.opencode import OpenCodeLaunchAdapter

            self.register_adapter(AgentType.codex, CodexLaunchAdapter)
            self.register_adapter(AgentType.kilo, KiloLaunchAdapter)
            self.register_adapter(AgentType.opencode, OpenCodeLaunchAdapter)
            self.register_adapter(AgentType.cline, ClineLaunchAdapter)
            self.register_adapter(AgentType.aider, AiderLaunchAdapter)

            self._initialized = True
            logger.info("Agent registry initialized with %d adapters", len(self.SUPPORTED_AGENTS))
        except Exception as e:
            logger.error("Failed to initialize agent registry: %s", e)
            self._initialized = True  # Prevent retry loop

    def detect_all(self) -> dict[str, DetectedAgent]:
        """Detect all supported agents and return their status."""
        self._ensure_initialized()

        if self._detected_agents:
            return self._detected_agents

        results = {}
        for agent_type, adapter_class in self.SUPPORTED_AGENTS.items():
            try:
                adapter = adapter_class()
                info = adapter.detect()

                agent = DetectedAgent(
                    name=info.name,
                    agent_type=info.agent_type,
                    executable_path=info.executable_path,
                    version=info.version,
                    status=info.status,
                    capabilities=info.capabilities,
                    launch_command=info.launch_command,
                    description=info.description,
                )
                results[agent_type.value] = agent
                logger.info(
                    "Detected %s: status=%s executable=%s",
                    agent.name,
                    agent.status.value,
                    agent.executable_path,
                )
            except Exception as e:
                logger.warning("Error detecting agent %s: %s", agent_type.value, e)
                results[agent_type.value] = DetectedAgent(
                    name=agent_type.value,
                    agent_type=agent_type,
                    status=AgentStatus.NOT_INSTALLED,
                    description=f"Error: {e}",
                )

        self._detected_agents = results
        return results

    def get_agent(self, name: str) -> DetectedAgent | None:
        """Get detected agent by name or type."""
        self._ensure_initialized()

        # Try by agent type value
        if name in self._detected_agents:
            return self._detected_agents[name]

        # Try case-insensitive match
        name_lower = name.lower()
        for agent_name, agent in self._detected_agents.items():
            if agent_name.lower() == name_lower:
                return agent

        # Try by agent name
        for agent in self._detected_agents.values():
            if agent.name.lower() == name_lower:
                return agent

        return None

    def get_adapter(self, agent_type: AgentType | str) -> Any | None:
        """Get the adapter class for an agent type."""
        self._ensure_initialized()

        if isinstance(agent_type, str):
            try:
                agent_type = AgentType(agent_type)
            except ValueError:
                logger.warning("Unknown agent type: %s", agent_type)
                return None

        adapter_class = self.SUPPORTED_AGENTS.get(agent_type)
        if adapter_class:
            return adapter_class()
        return None

    def list_installed(self) -> list[DetectedAgent]:
        """List all installed (available) agents."""
        self.detect_all()
        return [
            agent
            for agent in self._detected_agents.values()
            if agent.status in (
                AgentStatus.INSTALLED_SUPPORTED,
                AgentStatus.INSTALLED_BRIDGE_ONLY,
            )
        ]

    def list_all(self) -> list[DetectedAgent]:
        """List all supported agents with their status."""
        self.detect_all()
        return list(self._detected_agents.values())

    def get_status_table(self) -> list[dict[str, Any]]:
        """Get a status table for all agents."""
        self.detect_all()
        table = []

        for agent_type_value, adapter_class in self.SUPPORTED_AGENTS.items():
            agent = self._detected_agents.get(agent_type_value)
            if agent:
                table.append({
                    "name": agent.name,
                    "type": agent.agent_type.value,
                    "installed": agent.status in (
                        AgentStatus.INSTALLED_SUPPORTED,
                        AgentStatus.INSTALLED_BRIDGE_ONLY,
                    ),
                    "status": agent.status.value,
                    "executable": str(agent.executable_path) if agent.executable_path else "N/A",
                    "capabilities": [c.value for c in agent.capabilities],
                    "description": agent.description,
                })

        return table

    def get_supported_types(self) -> list[str]:
        """Get list of supported agent type names."""
        self._ensure_initialized()
        return [agent_type.value for agent_type in self.SUPPORTED_AGENTS.keys()]


# Global registry instance
_registry: AgentRegistry | None = None


def get_registry() -> AgentRegistry:
    """Get the global agent registry."""
    global _registry
    if _registry is None:
        _registry = AgentRegistry()
    return _registry
