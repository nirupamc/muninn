"""Munin project briefing formatter for M8.3B.

Creates compact, deterministic project briefings from retrieved memories.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from app.sdk.models import AgentContext

logger = logging.getLogger("munin.agents.briefing")


# Default configuration
DEFAULT_TOKEN_BUDGET = 1500
DEFAULT_MAX_MEMORY_LENGTH = 2000
MAX_BRIEFING_LENGTH = 8000

# Section headers
BRIEFING_START = "[MUNIN PROJECT CONTEXT]"
BRIEFING_END = "[MUNIN CONTEXT END]"


@dataclass
class BriefingConfig:
    """Configuration for briefing generation."""

    token_budget: int = DEFAULT_TOKEN_BUDGET
    max_memory_length: int = DEFAULT_MAX_MEMORY_LENGTH
    max_briefing_length: int = MAX_BRIEFING_LENGTH
    include_provenance: bool = False
    include_timestamps: bool = False
    include_namespace: bool = True
    section_order: list[str] = field(default_factory=lambda: [
        "project",
        "current_state",
        "recent_work",
        "important_decisions",
        "known_blockers",
        "relevant_constraints",
        "recent_verification",
        "likely_next_work",
    ])


@dataclass
class MuninProjectBriefing:
    """A formatted project briefing from Munin memories."""

    project_name: str
    project_path: str | Path | None = None
    namespace: str | None = None
    context: AgentContext | None = None
    sections: dict[str, list[str]] = field(default_factory=dict)
    memory_count: int = 0
    briefing_text: str = ""
    token_estimate: int = 0

    def __post_init__(self) -> None:
        """Generate briefing text if context is provided."""
        if self.context:
            self._build_briefing()

    def _build_briefing(self) -> None:
        """Build the briefing from context."""
        self.memory_count = len(self.context.memories_used) if self.context else 0
        self.sections = self._categorize_memories()
        self.briefing_text = self._format_briefing()
        self.token_estimate = self._estimate_tokens()

    def _categorize_memories(self) -> dict[str, list[str]]:
        """Categorize memories into sections."""
        if not self.context:
            return {}

        sections: dict[str, list[str]] = {
            "project": [],
            "current_state": [],
            "recent_work": [],
            "important_decisions": [],
            "known_blockers": [],
            "relevant_constraints": [],
            "recent_verification": [],
            "likely_next_work": [],
        }

        for memory in self.context.memories_used:
            content_lower = memory.content.lower()

            # Categorize based on content patterns
            if self._is_project_info(memory.content):
                sections["project"].append(memory.content)
            elif self._is_decision(content_lower):
                sections["important_decisions"].append(memory.content)
            elif self._is_blocker(content_lower):
                sections["known_blockers"].append(memory.content)
            elif self._is_constraint(content_lower):
                sections["relevant_constraints"].append(memory.content)
            elif self._is_verification(content_lower):
                sections["recent_verification"].append(memory.content)
            elif self._is_next_work(content_lower):
                sections["likely_next_work"].append(memory.content)
            else:
                # Default to recent_work
                sections["recent_work"].append(memory.content)

        # Deduplicate within sections
        for section in sections:
            sections[section] = self._deduplicate_memories(sections[section])

        return sections

    def _is_project_info(self, content: str) -> bool:
        """Check if content describes project info."""
        patterns = [
            "project:",
            "repository:",
            "namespace:",
            "working on",
            "this project",
        ]
        content_lower = content.lower()
        return any(p in content_lower for p in patterns)

    def _is_decision(self, content_lower: str) -> bool:
        """Check if content describes a decision."""
        patterns = [
            "decision:",
            "decided to",
            "we will use",
            "switch to",
            "replace with",
            "chose to",
            "going with",
        ]
        return any(p in content_lower for p in patterns)

    def _is_blocker(self, content_lower: str) -> bool:
        """Check if content describes a blocker."""
        patterns = [
            "blocker:",
            "blocked by",
            "cannot",
            "can't",
            "stuck",
            "waiting on",
            "depends on",
            "known limitation",
            "issue:",
            "problem:",
        ]
        return any(p in content_lower for p in patterns)

    def _is_constraint(self, content_lower: str) -> bool:
        """Check if content describes a constraint."""
        patterns = [
            "constraint:",
            "must",
            "should",
            "require",
            "need to",
            "policy:",
            "do not",
            "don't",
        ]
        return any(p in content_lower for p in patterns)

    def _is_verification(self, content_lower: str) -> bool:
        """Check if content describes verification."""
        patterns = [
            "verified",
            "passed",
            "passing",
            "succeeded",
            "success",
            "tests passed",
            "build succeeded",
            "completed",
            "done",
        ]
        return any(p in content_lower for p in patterns)

    def _is_next_work(self, content_lower: str) -> bool:
        """Check if content describes next work."""
        patterns = [
            "next:",
            "next step",
            "next work",
            "todo",
            "remaining",
            "still need",
            "next is",
        ]
        return any(p in content_lower for p in patterns)

    def _deduplicate_memories(self, memories: list[str]) -> list[str]:
        """Remove duplicate or very similar memories."""
        seen: set[str] = set()
        result = []
        for mem in memories:
            # Use first 50 chars as key for deduplication
            key = mem[:50]
            if key not in seen:
                seen.add(key)
                result.append(mem)
        return result

    def _format_briefing(self) -> str:
        """Format the briefing with sections."""
        lines = []

        # Header
        lines.append(BRIEFING_START)
        lines.append("")

        # Project info
        if self.project_name:
            lines.append(f"Project: {self.project_name}")
        if self.project_path:
            lines.append(f"Path: {self.project_path}")
        if self.namespace:
            lines.append(f"Namespace: {self.namespace}")
        lines.append("")

        # Current state (auto-generated from memories)
        current_state = self._get_current_state()
        if current_state:
            lines.append("Current state:")
            lines.append(current_state)
            lines.append("")

        # Sections
        for section_name in self.sections:
            section_memories = self.sections.get(section_name, [])
            if section_memories:
                # Capitalize section name for display
                display_name = section_name.replace("_", " ").title()
                lines.append(f"{display_name}:")
                for mem in section_memories:
                    lines.append(f"- {mem}")
                lines.append("")

        # Memory count
        if self.memory_count > 0:
            lines.append(f"Recent verification: {self.memory_count} memories retrieved.")
        else:
            lines.append("Recent verification: No Munin memories found for this project.")
        lines.append("")

        # Footer
        lines.append(BRIEFING_END)

        return "\n".join(lines)

    def _get_current_state(self) -> str:
        """Generate a current state summary from memories."""
        if not self.context:
            return ""

        # Use the first few memories to summarize
        recent = self.context.memories_used[:5]
        if not recent:
            return "No recent activity recorded."

        states = []
        for mem in recent:
            content = mem.content
            # Extract action words
            if "implemented" in content.lower() or "added" in content.lower():
                states.append(f"Added: {content[:100]}")
            elif "fixed" in content.lower() or "resolved" in content.lower():
                states.append(f"Fixed: {content[:100]}")
            elif "decision" in content.lower() or "decided" in content.lower():
                states.append(f"Decided: {content[:100]}")

        return "; ".join(states) if states else "Working on project."

    def _estimate_tokens(self) -> int:
        """Estimate token count for the briefing."""
        # Simple estimation: ~4 tokens per word
        words = self.briefing_text.split()
        return len(words) * 4

    def truncate(self, max_length: int = MAX_BRIEFING_LENGTH) -> "MuninProjectBriefing":
        """Truncate the briefing to fit within a maximum length."""
        if len(self.briefing_text) <= max_length:
            return self

        suffix = "\n... (truncated)"
        # Leave room for the suffix
        truncated_text = self.briefing_text[: max_length - len(suffix)] + suffix

        # Create a copy without triggering __post_init__ rebuild
        import copy
        truncated = copy.copy(self)
        truncated.briefing_text = truncated_text
        return truncated


class BriefingFormatter:
    """Formatter for creating project briefings from Munin context."""

    def __init__(self, config: BriefingConfig | None = None) -> None:
        """Initialize with optional configuration."""
        self.config = config or BriefingConfig()

    def create_briefing(
        self,
        project_name: str,
        project_path: str | Path | None = None,
        namespace: str | None = None,
        context: AgentContext | None = None,
    ) -> MuninProjectBriefing:
        """Create a project briefing from context."""
        briefing = MuninProjectBriefing(
            project_name=project_name,
            project_path=project_path,
            namespace=namespace,
            context=context,
        )

        # Truncate if needed
        if len(briefing.briefing_text) > self.config.max_briefing_length:
            briefing = briefing.truncate(self.config.max_briefing_length)

        return briefing

    def create_empty_briefing(
        self,
        project_name: str,
        project_path: str | Path | None = None,
        namespace: str | None = None,
    ) -> MuninProjectBriefing:
        """Create a briefing for a project with no memories."""
        # Create a minimal context
        from app.sdk.models import AgentContext
        empty_context = AgentContext(
            query="",
            namespace=namespace or "",
            text="",
            estimated_tokens=0,
            truncated=False,
            memories_used=[],
        )

        briefing = MuninProjectBriefing(
            project_name=project_name,
            project_path=project_path,
            namespace=namespace,
            context=empty_context,
        )

        # Override with empty briefing text
        lines = [
            BRIEFING_START,
            "",
            f"Project: {project_name}",
        ]
        if project_path:
            lines.append(f"Path: {project_path}")
        if namespace:
            lines.append(f"Namespace: {namespace}")
        lines.extend([
            "",
            "Munin currently has no durable project memories.",
            "",
            BRIEFING_END,
        ])

        briefing.briefing_text = "\n".join(lines)
        briefing.memory_count = 0

        return briefing


def create_project_briefing(
    project_name: str,
    project_path: str | Path | None = None,
    namespace: str | None = None,
    context: AgentContext | None = None,
    config: BriefingConfig | None = None,
) -> MuninProjectBriefing:
    """Convenience function to create a project briefing."""
    formatter = BriefingFormatter(config)

    if context is None:
        return formatter.create_empty_briefing(project_name, project_path, namespace)

    return formatter.create_briefing(project_name, project_path, namespace, context)
