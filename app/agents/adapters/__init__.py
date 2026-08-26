"""Agent launch adapters for M8.3B."""

from app.agents.adapters.base import AgentLaunchAdapter
from app.agents.adapters.codex import CodexLaunchAdapter
from app.agents.adapters.kilo import KiloLaunchAdapter
from app.agents.adapters.opencode import OpenCodeLaunchAdapter

__all__ = [
    "AgentLaunchAdapter",
    "CodexLaunchAdapter",
    "KiloLaunchAdapter",
    "OpenCodeLaunchAdapter",
]
