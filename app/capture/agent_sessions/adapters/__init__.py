"""Agent session adapters for M8.3."""

from app.capture.agent_sessions.adapters.base import AgentSessionAdapter
from app.capture.agent_sessions.adapters.aider import AiderAdapter
from app.capture.agent_sessions.adapters.cline import ClineAdapter
from app.capture.agent_sessions.adapters.codex import CodexAdapter
from app.capture.agent_sessions.adapters.kilo import KiloAdapter
from app.capture.agent_sessions.adapters.opencode import OpenCodeAdapter

__all__ = [
    "AgentSessionAdapter",
    "AiderAdapter",
    "ClineAdapter",
    "CodexAdapter",
    "KiloAdapter",
    "OpenCodeAdapter",
]
