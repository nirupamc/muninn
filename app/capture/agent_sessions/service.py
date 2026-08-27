"""Agent session capture service for M8.3.

Orchestrates discovery, normalization, and capture of agent session events
through the existing Munin capture pipeline.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.capture.agent_sessions.adapters import (
    AgentSessionAdapter,
    AiderAdapter,
    ClineAdapter,
    CodexAdapter,
    KiloAdapter,
    OpenCodeAdapter,
)
from app.capture.agent_sessions.checkpoints import AgentSessionCheckpoint
from app.capture.agent_sessions.models import (
    AgentSession,
    AgentSessionEvent,
    AgentSessionSource,
    AgentSessionStatus,
)
from app.capture.agent_sessions.normalizer import SessionNormalizer
from app.capture.service import CaptureService
from app.models.capture import CaptureEvent, CaptureEventType, CaptureSource
from app.models.project import Project
from app.projects.repository import ProjectRepository

logger = logging.getLogger("munin.capture.agent_sessions.service")


@dataclass
class AgentSessionCaptureResult:
    """Result of processing agent session events."""

    session_id: str
    events_discovered: int
    events_processed: int
    capture_events_created: int
    memories_created: int
    errors: list[str]


class AgentSessionService:
    """Service for capturing agent session events as Munin memories.
    
    This service:
    1. Discovers agent sessions from all available adapters
    2. Normalizes raw session events into meaningful capture candidates
    3. Routes candidates through the existing CaptureService
    4. Maintains checkpoints to prevent replay
    5. Isolates adapter failures
    """

    # All available agent session adapters
    ADAPTER_CLASSES = [
        CodexAdapter,
        KiloAdapter,
        OpenCodeAdapter,
        ClineAdapter,
        AiderAdapter,
    ]

    def __init__(self, db: Session) -> None:
        self.db = db
        self.normalizer = SessionNormalizer()
        self.capture_service = CaptureService(db)
        self._adapters: dict[AgentSessionSource, AgentSessionAdapter] = {}
        self._init_adapters()

    def _init_adapters(self) -> None:
        """Initialize all available adapters."""
        for adapter_class in self.ADAPTER_CLASSES:
            adapter = adapter_class()
            self._adapters[adapter.name] = adapter
            logger.info(
                "Initialized %s adapter (status: %s)",
                adapter.name.value,
                adapter.get_integration_status(),
            )

    def get_available_adapters(self) -> list[AgentSessionSource]:
        """Get list of available adapter sources."""
        available = []
        for source, adapter in self._adapters.items():
            if adapter.available():
                available.append(source)
        return available

    def get_adapter_health(self) -> dict[AgentSessionSource, dict[str, Any]]:
        """Get health status for all adapters."""
        health = {}
        for source, adapter in self._adapters.items():
            health[source] = adapter.health()
        return health

    def discover_sessions(
        self, project: Project | None = None
    ) -> list[AgentSession]:
        """Discover new agent sessions from all available adapters.
        
        Args:
            project: Optional project to scope discovery to. If None, 
                     discovers from all adapters.
        
        Returns:
            List of discovered AgentSession objects.
        """
        sessions = []
        
        for source, adapter in self._adapters.items():
            if not adapter.available():
                logger.debug("Adapter %s not available, skipping", source.value)
                continue
            
            try:
                # Load checkpoint for this adapter
                if project:
                    adapter.load_checkpoint(project)
                
                discovered = adapter.discover_sessions(self.db)
                
                for session in discovered:
                    # Resolve project if not provided
                    if not session.project_id and session.project_path:
                        resolved = self._resolve_project(session.project_path)
                        if resolved:
                            session.project_id = resolved.id
                            session.namespace = resolved.namespace
                    
                    # Associate with the provided project if applicable
                    if project and not session.project_id:
                        session.project_id = project.id
                        session.namespace = project.namespace
                    
                    sessions.append(session)
                    logger.info(
                        "Discovered %s session %s (project: %s)",
                        source.value,
                        session.external_session_id,
                        session.project_path or session.project_id,
                    )
                
            except Exception as e:
                logger.error(
                    "Error discovering sessions from %s adapter: %s",
                    source.value,
                    e,
                    exc_info=True,
                )
        
        return sessions

    def _resolve_project(self, project_path: str) -> Project | None:
        """Resolve a project path to a Project registry entry."""
        from app.capture.project_resolver import ProjectResolver
        
        resolver = ProjectResolver(self.db)
        return resolver.resolve_by_path(project_path)

    def process_session(
        self,
        session: AgentSession,
        project: Project | None = None,
    ) -> AgentSessionCaptureResult:
        """Process a single agent session and its events.
        
        Args:
            session: The agent session to process.
            project: Optional project to associate with. If None, 
                     will try to resolve from session metadata.
        
        Returns:
            AgentSessionCaptureResult with processing statistics.
        """
        errors = []
        events_discovered = 0
        events_processed = 0
        capture_events_created = 0
        memories_created = 0
        
        # Resolve project
        target_project = project
        if not target_project:
            if session.project_id:
                repo = ProjectRepository(self.db)
                target_project = repo.get_by_id(session.project_id)
            elif session.project_path:
                target_project = self._resolve_project(session.project_path)
        
        if not target_project:
            logger.warning(
                "Cannot process session %s: no associated project",
                session.id,
            )
            return AgentSessionCaptureResult(
                session_id=session.id,
                events_discovered=0,
                events_processed=0,
                capture_events_created=0,
                memories_created=0,
                errors=["No project associated with session"],
            )
        
        # Get the appropriate adapter for this session
        adapter = self._adapters.get(session.source)
        if not adapter:
            logger.warning(
                "No adapter for source %s, cannot read events",
                session.source.value,
            )
            return AgentSessionCaptureResult(
                session_id=session.id,
                events_discovered=0,
                events_processed=0,
                capture_events_created=0,
                memories_created=0,
                errors=[f"No adapter for source {session.source.value}"],
            )
        
        try:
            # Set adapter project so checkpoint() can persist
            adapter.project = target_project

            # Load checkpoint
            adapter.load_checkpoint(target_project)
            
            # Read events
            events = adapter.read_new_events(session, self.db)
            events_discovered = len(events)
            
            logger.info(
                "[agent-session] adapter=%s session=%s ns=%s checkpoint_ts=%.1f events_raw=%d new_events=%d",
                session.source.value,
                session.external_session_id[:16],
                target_project.namespace,
                adapter._checkpoint.last_event_timestamp,
                session.metadata.get("event_count", 0),
                events_discovered,
            )

            if not events:
                logger.info("No new events for session %s", session.id)
                # Still update checkpoint to mark as processed
                adapter.checkpoint(session, self.db)
                return AgentSessionCaptureResult(
                    session_id=session.id,
                    events_discovered=0,
                    events_processed=0,
                    capture_events_created=0,
                    memories_created=0,
                    errors=[],
                )
            
            # Process events through normalizer
            for event in events:
                try:
                    capture_data = self.normalizer.build_capture_event(session, event)
                    
                    if capture_data:
                        evt_type = capture_data.get("metadata", {}).get("agent_session_event_type", "?")
                        logger.info(
                            "[normalize] event=%s classification=%s candidate=yes",
                            event.external_event_id or event.id[:8],
                            evt_type,
                        )
                        # Create capture event through the service
                        capture_event = self._create_capture_event(
                            target_project, capture_data
                        )
                        capture_events_created += 1
                        
                        # Check if a memory was created
                        if capture_event.memory_id:
                            memories_created += 1
                            logger.info(
                                "[capture] event_id=%s status=STORE memory_id=%s",
                                capture_event.id[:8],
                                capture_event.memory_id[:8],
                            )
                        else:
                            decision = getattr(capture_event, 'admission_decision', '?')
                            logger.info(
                                "[capture] event_id=%s status=%s",
                                capture_event.id[:8],
                                decision,
                            )
                    else:
                        logger.debug(
                            "[normalize] event=%s trivial/secret — ignored",
                            event.external_event_id or event.id[:8],
                        )
                    
                    events_processed += 1
                    
                except Exception as e:
                    errors.append(f"Error processing event {event.id}: {e}")
                    logger.error(
                        "Error processing event %s: %s",
                        event.id,
                        e,
                        exc_info=True,
                    )
            
            # Update checkpoint after processing all events
            last_event = events[-1] if events else None
            adapter.checkpoint(session, self.db, last_event)
            logger.info(
                "[checkpoint] adapter=%s session=%s saved ts=%.1f",
                session.source.value,
                session.external_session_id[:16],
                adapter._checkpoint.last_event_timestamp,
            )
            
            # Update session status
            if session.ended_at:
                session.status = AgentSessionStatus.finished
            
            logger.info(
                "Processed session %s: %d events -> %d captures -> %d memories",
                session.id,
                events_discovered,
                capture_events_created,
                memories_created,
            )
            
        except Exception as e:
            errors.append(f"Error processing session: {e}")
            logger.error(
                "Error processing session %s: %s",
                session.id,
                e,
                exc_info=True,
            )
        
        return AgentSessionCaptureResult(
            session_id=session.id,
            events_discovered=events_discovered,
            events_processed=events_processed,
            capture_events_created=capture_events_created,
            memories_created=memories_created,
            errors=errors,
        )

    def _create_capture_event(
        self,
        project: Project,
        capture_data: dict[str, Any],
    ) -> CaptureEvent:
        """Create a capture event from normalized session data."""
        event_type = capture_data.get("event_type", CaptureEventType.agent_summary)
        content = capture_data.get("content", "")
        metadata = capture_data.get("metadata", {})
        occurred_at = capture_data.get("occurred_at", datetime.now(UTC))
        fingerprint = capture_data.get("fingerprint")
        agent_id = capture_data.get("agent_id", "agent_session")
        session_id = capture_data.get("session_id")
        working_directory = capture_data.get("working_directory")
        
        # Map source from metadata
        source_str = metadata.get("agent_session_source", "generic")
        try:
            source = CaptureSource(source_str)
        except ValueError:
            source = CaptureSource.generic
        
        return self.capture_service.capture_event(
            project=project,
            source=source,
            source_event_type=event_type,
            content=content,
            agent_id=agent_id,
            session_id=session_id,
            working_directory=working_directory,
            metadata=metadata,
            occurred_at=occurred_at,
            fingerprint=fingerprint,
        )

    def create_session_summary(
        self,
        session: AgentSession,
        events: list[AgentSessionEvent],
        project: Project,
    ) -> CaptureEvent | None:
        """Create a session summary capture event.
        
        This is called when a session is finished to create a 
        comprehensive summary of the session's activity.
        """
        summary_data = self.normalizer.build_session_summary(session, events)
        
        if not summary_data:
            return None
        
        return self._create_capture_event(project, summary_data)

    def process_all_sessions(self) -> dict[str, Any]:
        """Process all discovered sessions from all adapters.
        
        Returns:
            Dictionary with processing statistics.
        """
        stats = {
            "total_sessions": 0,
            "total_events": 0,
            "total_captures": 0,
            "total_memories": 0,
            "errors": 0,
            "by_source": {},
        }
        
        # Discover sessions
        sessions = self.discover_sessions()
        stats["total_sessions"] = len(sessions)
        
        for session in sessions:
            source = session.source.value
            if source not in stats["by_source"]:
                stats["by_source"][source] = {
                    "sessions": 0,
                    "events": 0,
                    "captures": 0,
                    "memories": 0,
                    "errors": 0,
                }
            
            result = self.process_session(session)
            
            stats["by_source"][source]["sessions"] += 1
            stats["by_source"][source]["events"] += result.events_discovered
            stats["by_source"][source]["captures"] += result.capture_events_created
            stats["by_source"][source]["memories"] += result.memories_created
            stats["by_source"][source]["errors"] += len(result.errors)
            
            stats["total_events"] += result.events_discovered
            stats["total_captures"] += result.capture_events_created
            stats["total_memories"] += result.memories_created
            stats["errors"] += len(result.errors)
        
        return stats

    def get_session_stats(self, project_id: str | None = None) -> dict[str, Any]:
        """Get capture statistics for agent sessions.
        
        Args:
            project_id: Optional project ID to filter by.
        
        Returns:
            Dictionary with session capture statistics.
        """
        from app.capture.repository import CaptureEventRepository
        
        repo = CaptureEventRepository(self.db)
        
        # Query capture events from agent sources
        agent_sources = [
            CaptureSource.codex.value,
            CaptureSource.kilo.value,
            CaptureSource.opencode.value,
        ]
        
        query = repo.db.query(CaptureEvent).filter(
            CaptureEvent.source.in_(agent_sources)
        )
        
        if project_id:
            query = query.filter(CaptureEvent.project_id == project_id)
        
        events = query.all()
        
        return {
            "total_events": len(events),
            "pending": len([e for e in events if e.processing_status == "pending"]),
            "completed": len([e for e in events if e.processing_status == "completed"]),
            "failed": len([e for e in events if e.processing_status == "failed"]),
            "with_memories": len([e for e in events if e.memory_id]),
            "sources": {
                s: len([e for e in events if e.source.value == s])
                for s in agent_sources
            },
        }
