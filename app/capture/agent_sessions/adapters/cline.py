"""Cline CLI agent session adapter for M8.3C.

VERIFIED_LOG_ADAPTER: Cline stores sessions as JSON files in ~/.cline/data/sessions/.
Each session has a metadata JSON and a messages JSON.
"""

from __future__ import annotations

import json
import logging
import os
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

logger = logging.getLogger("munin.capture.agent_sessions.cline")


class ClineAdapter(AgentSessionAdapter):
    """Cline CLI agent session adapter.

    Reads session JSON files from ~/.cline/data/sessions/ directory.
    Each session has:
    - <session_id>.json (metadata)
    - <session_id>.messages.json (messages)

    Integration status: VERIFIED_LOG_ADAPTER
    """

    name = AgentSessionSource.cline
    supports_polling = True
    supports_live_hooks = False
    supports_session_history = True
    integration_status = "VERIFIED_LOG_ADAPTER"

    def __init__(self, project: Project | None = None) -> None:
        super().__init__(project)
        self._sessions_dir = self._find_sessions_dir()

    def _find_sessions_dir(self) -> Path | None:
        """Find the Cline sessions directory."""
        candidates = [
            Path.home() / ".cline" / "data" / "sessions",
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None

    def available(self) -> bool:
        """Check if Cline sessions directory exists."""
        return self._sessions_dir is not None and self._sessions_dir.exists()

    def _parse_session_metadata(self, filepath: Path) -> dict[str, Any]:
        """Parse a Cline session metadata JSON file."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                return json.load(f)
        except Exception as e:
            logger.warning("Error reading Cline session metadata %s: %s", filepath, e)
            return {}

    def _parse_session_messages(self, filepath: Path) -> list[dict[str, Any]]:
        """Parse a Cline session messages JSON file."""
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                data = json.load(f)
                return data.get("messages", [])
        except Exception as e:
            logger.warning("Error reading Cline session messages %s: %s", filepath, e)
            return []

    def _extract_content(self, raw_content: Any) -> str:
        """Extract text content from Cline message content blocks."""
        if isinstance(raw_content, str):
            return raw_content
        if isinstance(raw_content, list):
            parts = []
            for block in raw_content:
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        parts.append(block.get("text", ""))
                    elif block.get("type") == "thinking":
                        pass  # Skip thinking blocks
                    elif block.get("type") == "tool_result":
                        # Extract tool result content
                        result_content = block.get("content", "")
                        if isinstance(result_content, list):
                            for rc in result_content:
                                if isinstance(rc, dict) and rc.get("type") == "text":
                                    parts.append(rc.get("text", ""))
                        elif isinstance(result_content, str):
                            parts.append(result_content)
                    elif block.get("type") == "tool_use":
                        parts.append(f"[tool_use: {block.get('name', '?')}]")
                elif isinstance(block, str):
                    parts.append(block)
            return " ".join(parts)
        return str(raw_content) if raw_content else ""

    def discover_sessions(self, db: Session) -> list[AgentSession]:
        """Discover Cline sessions from JSON files."""
        if not self.available():
            return []

        sessions = []

        try:
            for session_dir in self._sessions_dir.iterdir():
                if not session_dir.is_dir():
                    continue

                session_id = session_dir.name
                meta_file = session_dir / f"{session_id}.json"
                msg_file = session_dir / f"{session_id}.messages.json"

                if not meta_file.exists():
                    continue

                # Skip already-processed session (by ID)
                if self._checkpoint.last_session_id == session_id:
                    continue

                # Skip sessions whose ended_at is older than checkpoint
                if self._checkpoint.last_event_timestamp > 0:
                    meta = self._parse_session_metadata(meta_file)
                    ended_str = meta.get("ended_at", "")
                    if ended_str:
                        try:
                            ended_at = datetime.fromisoformat(ended_str.replace("Z", "+00:00"))
                            if ended_at.timestamp() <= self._checkpoint.last_event_timestamp:
                                continue
                        except Exception:
                            pass

                meta = self._parse_session_metadata(meta_file)
                messages = self._parse_session_messages(msg_file)

                if not messages:
                    continue

                # Parse timestamps
                started_str = meta.get("started_at", "")
                ended_str = meta.get("ended_at", "")

                try:
                    started_at = datetime.fromisoformat(started_str.replace("Z", "+00:00")) if started_str else datetime.now(UTC)
                except Exception:
                    started_at = datetime.now(UTC)

                try:
                    ended_at = datetime.fromisoformat(ended_str.replace("Z", "+00:00")) if ended_str else None
                except Exception:
                    ended_at = None

                # Extract project path from cwd
                project_path = meta.get("cwd") or meta.get("workspace_root")

                session = AgentSession(
                    source=AgentSessionSource.cline,
                    external_session_id=session_id,
                    project_path=project_path,
                    title=meta.get("prompt", "")[:100] if meta.get("prompt") else None,
                    started_at=started_at,
                    ended_at=ended_at,
                    last_seen_at=ended_at or started_at,
                    status=AgentSessionStatus.finished if ended_str else AgentSessionStatus.active,
                    metadata={
                        "file_path": str(meta_file),
                        "messages_path": str(msg_file),
                        "event_count": len(messages),
                        "model": meta.get("model"),
                        "provider": meta.get("provider"),
                        "status": meta.get("status"),
                    },
                )

                sessions.append(session)

        except Exception as e:
            logger.error("Error discovering Cline sessions: %s", e)

        return sessions

    def read_new_events(self, session: AgentSession, db: Session) -> list[AgentSessionEvent]:
        """Read new events from a Cline session file."""
        if not self.available():
            return []

        # First-connect: do NOT process historical backlog.
        if self.is_first_connect():
            logger.info(
                "First connect for Cline session %s — skipping %d historical events",
                session.external_session_id,
                session.metadata.get("event_count", 0),
            )
            return []

        events = []

        try:
            msg_file = Path(session.metadata.get("messages_path", ""))
            if not msg_file.exists():
                return []

            messages = self._parse_session_messages(msg_file)

            for i, msg in enumerate(messages):
                role = msg.get("role", "unknown")
                raw_content = msg.get("content", "")

                # Filter by timestamp if available
                # Cline messages don't have individual timestamps,
                # so we use the session's last_seen_at

                # Map role to event type
                if role == "user":
                    event_type = AgentSessionEventType.user_message
                elif role == "assistant":
                    event_type = AgentSessionEventType.assistant_message
                else:
                    event_type = AgentSessionEventType.assistant_message

                content = self._extract_content(raw_content)
                if not content.strip():
                    continue

                event = AgentSessionEvent(
                    session_id=session.id,
                    source=AgentSessionSource.cline,
                    external_event_id=f"{session.external_session_id}:{i}",
                    event_type=event_type,
                    role=role,
                    content=content,
                    occurred_at=session.started_at,
                    metadata={
                        "index": i,
                        "model": session.metadata.get("model"),
                        "provider": session.metadata.get("provider"),
                    },
                )
                events.append(event)

        except Exception as e:
            logger.error("Error reading Cline session events: %s", e)

        return events

    def checkpoint(self, session: AgentSession, db: Session, last_event: AgentSessionEvent | None = None) -> None:
        """Update checkpoint after processing — only advances, never regresses."""
        ts = last_event.occurred_at.timestamp() if last_event else session.last_seen_at.timestamp()
        self.advance_checkpoint(ts, session.external_session_id)

        if self.project:
            self.save_checkpoint(self.project, db)
