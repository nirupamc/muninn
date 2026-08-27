"""Aider agent session adapter for M8.3C.

VERIFIED_LOG_ADAPTER: Aider stores chat history as .aider.chat.history.md
in project directories. Each session is a markdown file with user messages
prefixed by #### and assistant responses in code blocks.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.capture.agent_sessions.adapters.base import AgentSessionAdapter
from app.capture.agent_sessions.models import (
    AgentSession,
    AgentSessionEvent,
    AgentSessionEventType,
    AgentSessionSource,
    AgentSessionStatus,
)
from app.models.project import Project

logger = logging.getLogger("munin.capture.agent_sessions.aider")


class AiderAdapter(AgentSessionAdapter):
    """Aider agent session adapter.

    Reads .aider.chat.history.md files from project directories.
    Format:
        # aider chat started at YYYY-MM-DD HH:MM:SS
        #### user message
        assistant response in code blocks
        #### next user message

    Integration status: VERIFIED_LOG_ADAPTER
    """

    name = AgentSessionSource.aider
    supports_polling = True
    supports_live_hooks = False
    supports_session_history = True
    integration_status = "VERIFIED_LOG_ADAPTER"

    def __init__(self, project: Project | None = None) -> None:
        super().__init__(project)
        self._workspace_roots = self._find_workspace_roots()

    def _find_workspace_roots(self) -> list[Path]:
        """Find workspace roots to search for aider history files."""
        roots = []

        # Common workspace roots
        for drive in ["E:", "D:", "C:"]:
            drive_path = Path(drive)
            if drive_path.exists():
                roots.append(drive_path)

        return roots

    def available(self) -> bool:
        """Check if we can find any aider history files."""
        return len(self._workspace_roots) > 0

    def _find_aider_history_files(self) -> list[tuple[Path, Path]]:
        """Find all .aider.chat.history.md files across workspace roots.

        Returns list of (history_file, project_dir) tuples.
        """
        files = []
        seen = set()

        for root in self._workspace_roots:
            try:
                # Only search top-level directories for performance
                if root.is_dir():
                    for project_dir in root.iterdir():
                        if not project_dir.is_dir():
                            continue
                        history_file = project_dir / ".aider.chat.history.md"
                        if history_file.exists() and history_file not in seen:
                            seen.add(history_file)
                            files.append((history_file, project_dir))
            except PermissionError:
                continue
            except Exception:
                continue

        return files

    def _parse_history(self, filepath: Path) -> list[dict[str, Any]]:
        """Parse an aider chat history markdown file into events.

        Returns list of dicts with role, content, line_number.
        """
        events = []

        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()

            current_role = None
            current_content_lines: list[str] = []
            start_time = None

            for i, line in enumerate(lines):
                stripped = line.rstrip("\n")

                # Parse start time
                if stripped.startswith("# aider chat started at"):
                    time_str = stripped.replace("# aider chat started at", "").strip()
                    try:
                        start_time = datetime.strptime(time_str, "%Y-%m-%d %H:%M:%S")
                    except Exception:
                        start_time = None

                # User message header
                elif stripped.startswith("#### "):
                    # Save previous message
                    if current_role and current_content_lines:
                        events.append({
                            "role": current_role,
                            "content": "\n".join(current_content_lines).strip(),
                            "line_number": i - len(current_content_lines),
                        })
                    current_role = "user"
                    current_content_lines = [stripped[5:].strip()]

                # Skip gitignore/setup lines
                elif stripped.startswith("> ") and not current_role:
                    continue

                # Assistant response or continuation
                elif stripped.startswith("> "):
                    content = stripped[2:].strip()
                    if not content:
                        continue

                    if current_role == "user":
                        # Save user message
                        events.append({
                            "role": "user",
                            "content": "\n".join(current_content_lines).strip(),
                            "line_number": i - len(current_content_lines),
                        })
                        current_role = "assistant"
                        current_content_lines = [content]
                    else:
                        current_content_lines.append(content)

                # Empty line in assistant response
                elif not stripped and current_role == "assistant":
                    current_content_lines.append("")

            # Save last message
            if current_role and current_content_lines:
                events.append({
                    "role": current_role,
                    "content": "\n".join(current_content_lines).strip(),
                    "line_number": len(lines) - len(current_content_lines),
                })

        except Exception as e:
            logger.warning("Error reading aider history %s: %s", filepath, e)

        return events, start_time

    def discover_sessions(self, db: Session) -> list[AgentSession]:
        """Discover Aider sessions from .aider.chat.history.md files."""
        if not self.available():
            return []

        sessions = []

        try:
            for history_file, project_dir in self._find_aider_history_files():
                # Use file path hash as session ID
                session_id = f"aider:{history_file.parent.name}:{history_file.stat().st_mtime:.0f}"

                # Skip already-processed session
                if self._checkpoint.last_session_id == session_id:
                    continue

                # Skip sessions older than checkpoint
                if self._checkpoint.last_event_timestamp > 0:
                    file_mtime = history_file.stat().st_mtime
                    if file_mtime <= self._checkpoint.last_event_timestamp:
                        continue

                events, start_time = self._parse_history(history_file)

                if not events:
                    continue

                session = AgentSession(
                    source=AgentSessionSource.aider,
                    external_session_id=session_id,
                    project_path=str(project_dir),
                    title=events[0].get("content", "")[:100] if events else None,
                    started_at=start_time or datetime.fromtimestamp(history_file.stat().st_mtime, tz=UTC),
                    ended_at=datetime.fromtimestamp(history_file.stat().st_mtime, tz=UTC),
                    last_seen_at=datetime.fromtimestamp(history_file.stat().st_mtime, tz=UTC),
                    status=AgentSessionStatus.finished,
                    metadata={
                        "file_path": str(history_file),
                        "event_count": len(events),
                        "project_dir": str(project_dir),
                    },
                )

                sessions.append(session)

        except Exception as e:
            logger.error("Error discovering Aider sessions: %s", e)

        return sessions

    def read_new_events(self, session: AgentSession, db: Session) -> list[AgentSessionEvent]:
        """Read new events from an Aider chat history file."""
        if not self.available():
            return []

        # First-connect: do NOT process historical backlog.
        if self.is_first_connect():
            logger.info(
                "First connect for Aider session %s — skipping %d historical events",
                session.external_session_id,
                session.metadata.get("event_count", 0),
            )
            return []

        events = []

        try:
            history_file = Path(session.metadata.get("file_path", ""))
            if not history_file.exists():
                return []

            raw_events, _ = self._parse_history(history_file)

            for i, raw_event in enumerate(raw_events):
                role = raw_event.get("role", "unknown")
                content = raw_event.get("content", "")

                if not content.strip():
                    continue

                # Map role to event type
                if role == "user":
                    event_type = AgentSessionEventType.user_message
                elif role == "assistant":
                    event_type = AgentSessionEventType.assistant_message
                else:
                    event_type = AgentSessionEventType.assistant_message

                event = AgentSessionEvent(
                    session_id=session.id,
                    source=AgentSessionSource.aider,
                    external_event_id=f"{session.external_session_id}:{i}",
                    event_type=event_type,
                    role=role,
                    content=content,
                    occurred_at=session.started_at,
                    metadata={
                        "index": i,
                        "line_number": raw_event.get("line_number"),
                    },
                )
                events.append(event)

        except Exception as e:
            logger.error("Error reading Aider session events: %s", e)

        return events

    def checkpoint(self, session: AgentSession, db: Session, last_event: AgentSessionEvent | None = None) -> None:
        """Update checkpoint after processing — only advances, never regresses."""
        ts = last_event.occurred_at.timestamp() if last_event else session.last_seen_at.timestamp()
        self.advance_checkpoint(ts, session.external_session_id)

        if self.project:
            self.save_checkpoint(self.project, db)
