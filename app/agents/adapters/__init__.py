"""Agent launch adapters for M8.3B/C."""

from app.agents.adapters.base import AgentLaunchAdapter
from app.agents.adapters.aider import AiderLaunchAdapter
from app.agents.adapters.cline import ClineLaunchAdapter
from app.agents.adapters.codex import CodexLaunchAdapter
from app.agents.adapters.kilo import KiloLaunchAdapter
from app.agents.adapters.opencode import OpenCodeLaunchAdapter

__all__ = [
    "AgentLaunchAdapter",
    "AiderLaunchAdapter",
    "ClineLaunchAdapter",
    "CodexLaunchAdapter",
    "KiloLaunchAdapter",
    "OpenCodeLaunchAdapter",
]
