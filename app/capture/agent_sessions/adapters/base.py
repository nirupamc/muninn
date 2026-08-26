"""Base agent session adapter contract for M8.3."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.capture.agent_sessions.checkpoints import AgentSessionCheckpoint
from app.capture.agent_sessions.models import (
    AgentSession,
    AgentSessionEvent,
    AgentSessionSource,
    AgentSessionStatus,
)
from app.models.project import Project


class AgentSessionAdapter(ABC):
    """Base class for agent session adapters.
    
    Adapters are responsible for:
    1. Discovering agent sessions from local storage
    2. Reading new events from those sessions
    3. Maintaining checkpoints to prevent replay
    4. Resolving sessions to projects
    """

    # Name of this adapter
    name: AgentSessionSource
    
    # Whether this adapter can poll for new sessions/events
    supports_polling: bool = True
    
    # Whether this adapter can receive live hooks (e.g., MCP)
    supports_live_hooks: bool = False
    
    # Whether this adapter can read session history
    supports_session_history: bool = True
    
    # Whether this adapter has verified native integration
    integration_status: str = "NOT_IMPLEMENTED"

    def __init__(self, project: Project | None = None) -> None:
        self.project = project
        self._checkpoint = AgentSessionCheckpoint()

    @abstractmethod
    def available(self) -> bool:
        """Check if this adapter is available (e.g., tool installed, config present)."""
        ...

    @abstractmethod
    def discover_sessions(self, db: Session) -> list[AgentSession]:
        """Discover new/updated agent sessions.
        
        Returns sessions that have not been fully processed yet.
        Should respect checkpoint to avoid replaying old sessions.
        """
        ...

    @abstractmethod
    def read_new_events(
        self,
        session: AgentSession,
        db: Session,
    ) -> list[AgentSessionEvent]:
        """Read new events from a session.
        
        Returns only events that occurred after the checkpoint.
        Should not return events that were already processed.
        """
        ...

    @abstractmethod
    def checkpoint(
        self,
        session: AgentSession,
        db: Session,
        last_event: AgentSessionEvent | None = None,
    ) -> None:
        """Update checkpoint after processing a session or event.
        
        Called after events are successfully processed to persist
        the new checkpoint state.
        """
        ...

    def is_first_connect(self) -> bool:
        """Return True if no checkpoint has been established for this adapter.

        First-connect means we have never processed any events for this
        adapter/project pair.  In that case ``read_new_events`` should
        return an empty list so that historical backlog is NOT imported.
        The checkpoint is still established at the session's current end
        so that only genuinely new future events are processed.
        """
        return (
            self._checkpoint.last_event_timestamp == 0.0
            and self._checkpoint.last_session_id is None
        )

    def load_checkpoint(self, project: Project) -> None:
        """Load checkpoint from project metadata."""
        if project.metadata_:
            cp_data = project.metadata_.get(f"{self.name.value}_checkpoint")
            if cp_data:
                self._checkpoint = AgentSessionCheckpoint.from_json(cp_data)

    def save_checkpoint(self, project: Project, db: Session) -> None:
        """Save checkpoint to project metadata."""
        from sqlalchemy.orm.attributes import flag_modified
        
        project.metadata_[f"{self.name.value}_checkpoint"] = self._checkpoint.to_json()
        flag_modified(project, "metadata_")
        db.flush()

    def resolve_project(
        self,
        session: AgentSession,
        resolver: Any,
        db: Session,
    ) -> Project | None:
        """Resolve an agent session to a project.
        
        Uses the session's project_path/directory to find or create
        a matching project in the registry.
        """
        from app.capture.project_resolver import ProjectResolver
        
        if not isinstance(resolver, ProjectResolver):
            resolver = ProjectResolver(db)
        
        # Try to resolve by path
        if session.project_path:
            project = resolver.resolve_by_path(session.project_path)
            if project:
                return project
        
        # Try to resolve by cwd if available in metadata
        if "cwd" in session.metadata:
            project = resolver.resolve_by_path(session.metadata["cwd"])
            if project:
                return project
        
        # Cannot resolve - return None
        return None

    def get_integration_status(self) -> str:
        """Get the integration status of this adapter."""
        return self.integration_status

    def health(self) -> dict[str, Any]:
        """Get adapter health status."""
        return {
            "name": self.name.value,
            "available": self.available(),
            "supports_polling": self.supports_polling,
            "supports_live_hooks": self.supports_live_hooks,
            "supports_session_history": self.supports_session_history,
            "integration_status": self.integration_status,
        }
