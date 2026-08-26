"""Type definitions for agent launch system (M8.3B)."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class InjectionCapability(str, enum.Enum):
    """Capability flags for agent context injection mechanisms."""

    supports_initial_prompt = "supports_initial_prompt"
    supports_system_prompt = "supports_system_prompt"
    supports_prompt_file = "supports_prompt_file"
    supports_stdin = "supports_stdin"
    supports_hooks = "supports_hooks"
    supports_mcp = "supports_mcp"
    supports_wrapper_only = "supports_wrapper_only"


class AgentType(str, enum.Enum):
    """Supported agent types."""

    codex = "codex"
    kilo = "kilo"
    opencode = "opencode"
    claude = "claude"
    aider = "aider"
    cursor = "cursor"
    cline = "cline"
    continue_ = "continue"
    roo = "roo"
    windsurf = "windsurf"
    generic = "generic"


class AgentStatus(str, enum.Enum):
    """Installation/integration status for agents."""

    INSTALLED_SUPPORTED = "INSTALLED_SUPPORTED"
    INSTALLED_BRIDGE_ONLY = "INSTALLED_BRIDGE_ONLY"
    INSTALLED_UNSUPPORTED = "INSTALLED_UNSUPPORTED"
    NOT_INSTALLED = "NOT_INSTALLED"


@dataclass
class AgentLaunchResult:
    """Result of attempting to launch an agent."""

    success: bool
    agent_name: str
    exit_code: int | None = None
    command: str | None = None
    error: str | None = None
    briefing: str | None = None
    project_id: str | None = None
    namespace: str | None = None
    context_tokens: int = 0
    injection_mechanism: str | None = None


@dataclass
class AgentInfo:
    """Information about a detected agent."""

    name: str
    agent_type: AgentType
    executable_path: Path | None = None
    version: str | None = None
    status: AgentStatus = AgentStatus.NOT_INSTALLED
    capabilities: set[InjectionCapability] = field(default_factory=set)
    launch_command: str | None = None
    description: str = ""
