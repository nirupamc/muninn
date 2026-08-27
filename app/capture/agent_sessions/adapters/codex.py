"""Codex agent session adapter for M8.3.

VERIFIED_LOG_ADAPTER: Codex stores sessions as JSONL files in ~/.codex/sessions/.
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
from app.capture.agent_sessions.checkpoints import AgentSessionCheckpoint
from app.capture.agent_sessions.models import (
    AgentSession,
    AgentSessionEvent,
    AgentSessionEventType,
    AgentSessionSource,
    AgentSessionStatus,
)
from app.models.project import Project

logger = logging.getLogger("munin.capture.agent_sessions.codex")


class CodexAdapter(AgentSessionAdapter):
    """Codex agent session adapter.
    
    Reads session JSONL files from ~/.codex/sessions/ directory.
    Files are named: rollout-YYYY-MM-DDTHH-MM-SS-<uuid>.jsonl
    
    Integration status: VERIFIED_LOG_ADAPTER
    """

    name = AgentSessionSource.codex
    supports_polling = True
    supports_live_hooks = False
    supports_session_history = True
    integration_status = "VERIFIED_LOG_ADAPTER"

    def __init__(self, project: Project | None = None) -> None:
        super().__init__(project)
        self._sessions_dir = self._find_sessions_dir()

    def _find_sessions_dir(self) -> Path | None:
        """Find the Codex sessions directory."""
        candidates = [
            Path.home() / ".codex" / "sessions",
            Path("/c/Users/Tantech LLC/AppData/Local/OpenAI/Codex/sessions"),
            Path("C:/Users/Tantech LLC/AppData/Local/OpenAI/Codex/sessions"),
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return candidate
        return None

    def available(self) -> bool:
        """Check if Codex sessions directory exists."""
        return self._sessions_dir is not None and self._sessions_dir.exists()

    def _parse_session_file(self, filepath: Path) -> tuple[str, list[dict[str, Any]]]:
        """Parse a Codex session JSONL file.
        
        Returns: (external_session_id, raw_events)
        The external_session_id is derived from the filename.
        """
        external_session_id = filepath.stem  # rollout-YYYY-MM-DDTHH-MM-SS-uuid
        events = []
        
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        
                        # Codex JSONL format: each line is an event
                        # Extract fields
                        event_type = obj.get("type", "unknown")
                        timestamp = obj.get("timestamp")
                        ordinal = obj.get("ordinal")
                        payload = obj.get("payload", {})
                        
                        # Map to our event types
                        if event_type == "message":
                            role = payload.get("role", "unknown")
                            if role == "user":
                                mapped_type = AgentSessionEventType.user_message
                            elif role == "assistant":
                                mapped_type = AgentSessionEventType.assistant_message
                            else:
                                mapped_type = AgentSessionEventType.assistant_message
                        elif event_type == "tool_call":
                            mapped_type = AgentSessionEventType.tool_call
                        elif event_type == "tool_result":
                            mapped_type = AgentSessionEventType.tool_result
                        else:
                            mapped_type = AgentSessionEventType.assistant_message
                        
                        # Extract content - handle list or string
                        content = ""
                        if "content" in payload:
                            raw = payload["content"]
                            if isinstance(raw, list):
                                # Join list of strings
                                content = " ".join(str(item) for item in raw)
                            else:
                                content = str(raw)
                        elif "text" in payload:
                            content = str(payload["text"])
                        
                        # Get timestamp
                        if timestamp:
                            try:
                                occurred_at = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                            except Exception:
                                occurred_at = datetime.now(UTC)
                        else:
                            occurred_at = datetime.now(UTC)
                        
                        events.append({
                            "external_event_id": str(ordinal) if ordinal else None,
                            "event_type": mapped_type,
                            "role": payload.get("role"),
                            "content": content,
                            "occurred_at": occurred_at,
                            "timestamp": timestamp,
                            "ordinal": ordinal,
                            "payload": payload,
                        })
                    except json.JSONDecodeError:
                        continue
        except Exception as e:
            logger.warning("Error reading Codex session file %s: %s", filepath, e)
        
        return external_session_id, events

    def _get_session_info_from_file(self, filepath: Path) -> dict[str, Any]:
        """Extract session metadata from filename and first event."""
        # Filename: rollout-2026-08-26T02-18-04-01a03aae-1d73-79d1-bd38-67dd59fee2f9.jsonl
        stem = filepath.stem
        if stem.startswith("rollout-"):
            # Parse: rollout-YYYY-MM-DDTHH-MM-SS-uuid
            parts = stem.split("-")
            if len(parts) >= 4:
                date_part = "-".join(parts[1:3])  # YYYY-MM-DD
                time_part = parts[3]  # THH-MM-SS
                # Session ID is the remaining parts
                session_id_parts = parts[4:]
                external_session_id = "-".join(session_id_parts)
            else:
                external_session_id = stem
        else:
            external_session_id = stem
        
        # Get project path from directory structure
        # ~/.codex/sessions/YYYY/MM/DD/rollout-...jsonl
        sessions_dir = self._sessions_dir
        year = month = day = None
        project_path = None
        
        if sessions_dir:
            try:
                rel_path = filepath.relative_to(sessions_dir)
                # rel_path: YYYY/MM/DD/filename.jsonl
                parts = list(rel_path.parts)
                if len(parts) >= 3:
                    # The date parts are the directory structure
                    year, month, day = parts[0], parts[1], parts[2]
                else:
                    year = month = day = None
            except Exception:
                year = month = day = None
        
        # Try to extract cwd from the first event in the file
        try:
            with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        payload = obj.get("payload", {})
                        if isinstance(payload, dict):
                            cwd = payload.get("cwd")
                            if cwd:
                                project_path = cwd
                        break  # Only need the first event
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        
        return {
            "external_session_id": external_session_id,
            "project_path": project_path,
            "date": f"{year}-{month}-{day}" if year else None,
        }

    def discover_sessions(self, db: Session) -> list[AgentSession]:
        """Discover Codex sessions from JSONL files."""
        if not self.available():
            return []
        
        sessions = []
        
        try:
            # Walk the sessions directory
            for filepath in self._sessions_dir.rglob("*.jsonl"):
                if not filepath.is_file():
                    continue
                
                # Parse the file to get external session ID
                external_session_id, events = self._parse_session_file(filepath)
                if not external_session_id:
                    continue
                
                # Skip already-processed session (by ID)
                if self._checkpoint.last_session_id == external_session_id:
                    continue

                # Skip sessions whose last event is older than checkpoint
                # (prevents replay of previously-processed sessions)
                if events and self._checkpoint.last_event_timestamp > 0:
                    last_event_ts = events[-1].get("occurred_at")
                    if last_event_ts and last_event_ts.timestamp() <= self._checkpoint.last_event_timestamp:
                        continue
                
                # Get first and last event timestamps
                if events:
                    first_event = events[0]
                    last_event = events[-1]
                    
                    # Get session info
                    session_info = self._get_session_info_from_file(filepath)
                    
                    session = AgentSession(
                        source=AgentSessionSource.codex,
                        external_session_id=external_session_id,
                        project_path=session_info.get("project_path"),
                        title=None,  # Codex doesn't store titles in JSONL
                        started_at=first_event.get("occurred_at", datetime.now(UTC)),
                        ended_at=last_event.get("occurred_at", datetime.now(UTC)),
                        last_seen_at=last_event.get("occurred_at", datetime.now(UTC)),
                        status=AgentSessionStatus.finished,  # JSONL sessions are complete
                        metadata={
                            "file_path": str(filepath),
                            "file_mtime": filepath.stat().st_mtime,
                            "event_count": len(events),
                            "date": session_info.get("date"),
                        },
                    )
                    
                    sessions.append(session)
        except Exception as e:
            logger.error("Error discovering Codex sessions: %s", e)
        
        return sessions

    def read_new_events(self, session: AgentSession, db: Session) -> list[AgentSessionEvent]:
        """Read new events from a Codex session file."""
        if not self.available():
            return []
        
        # First-connect: do NOT process historical backlog.
        # Establish checkpoint at session end; only future events are processed.
        if self.is_first_connect():
            logger.info(
                "First connect for Codex session %s — skipping %d historical events",
                session.external_session_id,
                session.metadata.get("event_count", 0),
            )
            return []
        
        events = []
        
        try:
            # Find the session file
            sessions_dir = self._sessions_dir
            if not sessions_dir:
                return []
            
            # Find file matching this session ID
            for filepath in sessions_dir.rglob("*.jsonl"):
                if session.external_session_id in filepath.stem:
                    # Parse the file
                    _, raw_events = self._parse_session_file(filepath)
                    
                    # Filter to only new events
                    for raw_event in raw_events:
                        event_ts = raw_event.get("occurred_at")
                        if event_ts:
                            event_timestamp = event_ts.timestamp()
                            if event_timestamp <= self._checkpoint.last_event_timestamp:
                                continue
                        
                        # Map to AgentSessionEvent
                        event = AgentSessionEvent(
                            session_id=session.id,
                            source=AgentSessionSource.codex,
                            external_event_id=raw_event.get("external_event_id"),
                            event_type=raw_event.get("event_type", AgentSessionEventType.assistant_message),
                            role=raw_event.get("role"),
                            content=raw_event.get("content", ""),
                            occurred_at=raw_event.get("occurred_at", datetime.now(UTC)),
                            metadata={
                                "ordinal": raw_event.get("ordinal"),
                                "timestamp": raw_event.get("timestamp"),
                                "payload": raw_event.get("payload", {}),
                            },
                        )
                        events.append(event)
                    
                    break  # Found the file
        except Exception as e:
            logger.error("Error reading Codex session events: %s", e)
        
        return events

    def checkpoint(self, session: AgentSession, db: Session, last_event: AgentSessionEvent | None = None) -> None:
        """Update checkpoint after processing — only advances, never regresses."""
        ts = last_event.occurred_at.timestamp() if last_event else session.last_seen_at.timestamp()
        self.advance_checkpoint(ts, session.external_session_id)
        
        # Also track file offset for incremental reads
        # For Codex JSONL files, we can track by file mtime
        if self.project and session.metadata.get("file_path"):
            try:
                filepath = Path(session.metadata["file_path"])
                self._checkpoint.adapter_metadata["last_file_mtime"] = filepath.stat().st_mtime
            except Exception:
                pass
        
        if self.project:
            self.save_checkpoint(self.project, db)
