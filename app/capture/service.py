"""Capture service for processing capture events through the memory pipeline."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.agent.service import AgentService
from app.agent.models import AgentRememberRequest
from app.capture.repository import CaptureEventRepository
from app.capture.project_resolver import ProjectResolver
from app.models.capture import (
    CaptureEvent,
    CaptureEventType,
    CaptureProcessingStatus,
    CaptureSource,
    AdmissionDecision,
)
from app.models.project import Project


class CaptureService:
    """Service for processing capture events through the existing memory pipeline."""

    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = CaptureEventRepository(db)
        self.resolver = ProjectResolver(db)
        self.agent_service = AgentService(db)

    def _make_fingerprint(
        self,
        *,
        project_id: str,
        source: CaptureSource,
        source_event_type: CaptureEventType,
        content: str,
        extra: str | None = None,
    ) -> str:
        """Create a stable fingerprint for idempotency."""
        import hashlib

        parts = [project_id, source.value, source_event_type.value, content]
        if extra:
            parts.append(extra)
        data = "|".join(parts).encode()
        return hashlib.sha256(data).hexdigest()[:64]

    def capture_event(
        self,
        *,
        project: Project,
        source: CaptureSource,
        source_event_type: CaptureEventType,
        content: str,
        agent_id: str | None = None,
        session_id: str | None = None,
        working_directory: str | None = None,
        metadata: dict[str, Any] | None = None,
        occurred_at: datetime | None = None,
        fingerprint: str | None = None,
    ) -> CaptureEvent:
        """Create and process a capture event."""
        occurred = occurred_at or datetime.now(UTC)

        # Generate fingerprint if not provided
        if fingerprint is None:
            fingerprint = self._make_fingerprint(
                project_id=project.id,
                source=source,
                source_event_type=source_event_type,
                content=content,
            )

        # Check idempotency
        existing = self.repo.get_by_fingerprint(fingerprint)
        if existing:
            return existing

        # Create capture event
        capture = self.repo.create(
            project_id=project.id,
            namespace=project.namespace,
            source=source,
            source_event_type=source_event_type,
            agent_id=agent_id,
            session_id=session_id,
            working_directory=working_directory,
            content=content,
            metadata=metadata,
            fingerprint=fingerprint,
            occurred_at=occurred,
            processing_status=CaptureProcessingStatus.pending,
        )

        # Process through admission pipeline
        self._process_capture(capture)

        return capture

    def _process_capture(self, capture: CaptureEvent) -> None:
        """Process a capture event through the memory admission pipeline."""
        self.repo.update_status(capture.id, CaptureProcessingStatus.processing)

        try:
            # Create an agent remember request
            request = AgentRememberRequest(
                namespace=capture.namespace,
                agent_id=capture.agent_id or "capture",
                session_id=capture.session_id,
                role="assistant",
                content=capture.content,
                idempotency_key=capture.fingerprint,
            )

            # Run through the existing pipeline
            result = self.agent_service.remember(request)

            # Update capture with results
            if result.remembered and result.memory_id:
                self.repo.update_status(
                    capture.id,
                    CaptureProcessingStatus.completed,
                    memory_event_id=result.event_id,
                    memory_id=result.memory_id,
                    admission_decision=AdmissionDecision.store,
                )
                # Mark project as memorized
                from app.projects.service import ProjectService
                service = ProjectService(self.db)
                service.mark_memorized(capture.project_id)
            else:
                self.repo.update_status(
                    capture.id,
                    CaptureProcessingStatus.completed,
                    memory_event_id=result.event_id,
                    admission_decision=AdmissionDecision.ignore,
                )

            # Update project last activity
            self.resolver.repo.update_last_activity(capture.project_id, capture.occurred_at)

        except Exception as e:
            self.repo.update_status(
                capture.id,
                CaptureProcessingStatus.failed,
                error=str(e),
            )
            raise

    def capture_git_commit(
        self,
        project: Project,
        *,
        commit_sha: str,
        commit_message: str,
        author: str | None = None,
        author_email: str | None = None,
        changed_files: list[str] | None = None,
        branch: str | None = None,
        occurred_at: datetime | None = None,
    ) -> CaptureEvent:
        """Capture a Git commit event."""
        import hashlib

        fingerprint = hashlib.sha256(
            f"{project.id}|git|git_commit|{commit_sha}".encode()
        ).hexdigest()[:64]

        content_lines = [f"Project {project.name} commit:"]
        content_lines.append(f'"{commit_message}"')
        if changed_files:
            content_lines.append("\nFiles changed:")
            content_lines.extend(f"  {f}" for f in changed_files)

        content = "\n".join(content_lines)

        metadata: dict[str, Any] = {
            "commit_sha": commit_sha,
        }
        if author:
            metadata["author"] = author
        if author_email:
            metadata["author_email"] = author_email
        if branch:
            metadata["branch"] = branch

        return self.capture_event(
            project=project,
            source=CaptureSource.git,
            source_event_type=CaptureEventType.git_commit,
            content=content,
            metadata=metadata,
            occurred_at=occurred_at,
            fingerprint=fingerprint,
        )

    def capture_filesystem_batch(
        self,
        project: Project,
        *,
        changed_files: list[str],
        working_directory: str | None = None,
        occurred_at: datetime | None = None,
    ) -> CaptureEvent:
        """Capture a batched filesystem change event."""
        import hashlib

        file_list = "\n".join(sorted(changed_files))
        fingerprint = hashlib.sha256(
            f"{project.id}|filesystem|file_batch_changed|{file_list}".encode()
        ).hexdigest()[:64]

        content_lines = ["Recent project files changed:"]
        content_lines.extend(f"  {f}" for f in sorted(changed_files))

        content = "\n".join(content_lines)

        metadata: dict[str, Any] = {
            "changed_files": changed_files,
            "file_count": len(changed_files),
        }
        if working_directory:
            metadata["working_directory"] = working_directory

        return self.capture_event(
            project=project,
            source=CaptureSource.filesystem,
            source_event_type=CaptureEventType.file_batch_changed,
            content=content,
            working_directory=working_directory,
            metadata=metadata,
            occurred_at=occurred_at,
            fingerprint=fingerprint,
        )

    def capture_agent_summary(
        self,
        project: Project,
        *,
        summary: str,
        agent_id: str,
        session_id: str | None = None,
        working_directory: str | None = None,
        occurred_at: datetime | None = None,
    ) -> CaptureEvent:
        """Capture an agent session summary."""
        import hashlib

        fingerprint = hashlib.sha256(
            f"{project.id}|{agent_id}|agent_summary|{summary}".encode()
        ).hexdigest()[:64]

        content = f"Agent session summary:\n{summary}"

        metadata: dict[str, Any] = {
            "summary_type": "session_summary",
        }
        if working_directory:
            metadata["working_directory"] = working_directory

        return self.capture_event(
            project=project,
            source=CaptureSource.generic,
            source_event_type=CaptureEventType.agent_summary,
            content=content,
            agent_id=agent_id,
            session_id=session_id,
            working_directory=working_directory,
            metadata=metadata,
            occurred_at=occurred_at,
            fingerprint=fingerprint,
        )