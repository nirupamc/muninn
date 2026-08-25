"""Generic agent capture bridge."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from app.capture.adapters.base import CaptureAdapter
from app.models.capture import CaptureSource, CaptureEventType
from app.models.project import Project


class GenericCaptureBridge(CaptureAdapter):
    """Generic capture bridge for external agents to report events via API/CLI."""

    name = CaptureSource.generic

    def __init__(self, project: Project) -> None:
        super().__init__(project)

    def available(self) -> bool:
        """Always available - it's an HTTP endpoint."""
        return True

    def discover_events(self) -> list[dict[str, Any]]:
        """Generic bridge doesn't auto-discover; it receives via API."""
        return []

    def checkpoint(self, event_data: dict[str, Any]) -> None:
        """No checkpoint needed for generic bridge."""
        pass

    def health(self) -> "AdapterHealth":
        from app.capture.adapters.base import AdapterHealth
        return AdapterHealth(
            name=self.name.value,
            available=True,
            last_check=datetime.now(UTC),
        )


# Event creation helpers for the generic bridge

def create_agent_summary_event(
    *,
    project_id: str,
    namespace: str,
    agent_id: str,
    session_id: str | None,
    summary: str,
    working_directory: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a generic capture event for an agent session summary."""
    import hashlib

    fingerprint = hashlib.sha256(
        f"{project_id}|generic|agent_summary|{agent_id}|{summary}".encode()
    ).hexdigest()[:64]

    return {
        "event_type": CaptureEventType.agent_summary,
        "content": f"Agent session summary:\n{summary}",
        "metadata": {
            "summary_type": "session_summary",
            "agent_id": agent_id,
            **(metadata or {}),
        },
        "agent_id": agent_id,
        "session_id": session_id,
        "working_directory": working_directory,
        "occurred_at": datetime.now(UTC),
        "fingerprint": fingerprint,
    }


def create_agent_decision_event(
    *,
    project_id: str,
    namespace: str,
    agent_id: str,
    session_id: str | None,
    decision: str,
    context: str | None = None,
    working_directory: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a generic capture event for an agent decision."""
    import hashlib

    fingerprint = hashlib.sha256(
        f"{project_id}|generic|agent_decision|{agent_id}|{decision}".encode()
    ).hexdigest()[:64]

    content = f"Agent decision: {decision}"
    if context:
        content += f"\nContext: {context}"

    return {
        "event_type": CaptureEventType.agent_decision,
        "content": content,
        "metadata": {
            "decision_type": "agent_decision",
            "agent_id": agent_id,
            **(metadata or {}),
        },
        "agent_id": agent_id,
        "session_id": session_id,
        "working_directory": working_directory,
        "occurred_at": datetime.now(UTC),
        "fingerprint": fingerprint,
    }


def create_manual_note_event(
    *,
    project_id: str,
    namespace: str,
    agent_id: str | None,
    content: str,
    working_directory: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a generic capture event for a manual note."""
    import hashlib

    fingerprint = hashlib.sha256(
        f"{project_id}|manual|manual_note|{content}".encode()
    ).hexdigest()[:64]

    return {
        "event_type": CaptureEventType.manual_note,
        "content": content,
        "metadata": {
            "note_type": "manual",
            **(metadata or {}),
        },
        "agent_id": agent_id,
        "working_directory": working_directory,
        "occurred_at": datetime.now(UTC),
        "fingerprint": fingerprint,
    }