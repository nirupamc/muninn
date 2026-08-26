"""Agent session capture package for M8.3.

Provides native integration with coding agents (Codex, Kilo, OpenCode)
to automatically capture meaningful session events as Munin memories.
"""

from app.capture.agent_sessions.models import (
    AgentSession,
    AgentSessionEvent,
    AgentSessionEventType,
    AgentSessionStatus,
    AgentSessionSource,
)
from app.capture.agent_sessions.adapters import (
    AgentSessionAdapter,
    CodexAdapter,
    KiloAdapter,
    OpenCodeAdapter,
)
from app.capture.agent_sessions.service import AgentSessionService
from app.capture.agent_sessions.normalizer import SessionNormalizer
from app.capture.agent_sessions.checkpoints import AgentSessionCheckpoint

__all__ = [
    "AgentSession",
    "AgentSessionEvent",
    "AgentSessionEventType",
    "AgentSessionStatus",
    "AgentSessionSource",
    "AgentSessionAdapter",
    "CodexAdapter",
    "KiloAdapter",
    "OpenCodeAdapter",
    "AgentSessionService",
    "SessionNormalizer",
    "AgentSessionCheckpoint",
]
