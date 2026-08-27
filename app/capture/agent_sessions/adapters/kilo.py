"""Kilo Code agent session adapter for M8.3.

VERIFIED_NATIVE: Kilo provides structured session export via `kilo export` CLI.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
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

logger = logging.getLogger("munin.capture.agent_sessions.kilo")


class KiloAdapter(AgentSessionAdapter):
    """Kilo Code agent session adapter.
    
    Uses `kilo session list` and `kilo export <sessionID>` to discover
    and read session data. Sessions are stored in Kilo's local database.
    
    Integration status: VERIFIED_NATIVE
    """

    name = AgentSessionSource.kilo
    supports_polling = True
    supports_live_hooks = False
    supports_session_history = True
    integration_status = "VERIFIED_NATIVE"

    def __init__(self, project: Project | None = None) -> None:
        super().__init__(project)
        self._kilo_path = self._find_kilo()

    def _find_kilo(self) -> str | None:
        """Find the kilo executable."""
        import sys
        # On Windows, prefer .cmd files over shell scripts
        candidates = [
            "kilo",
            "kilo.cmd",
            os.path.expanduser("~/.local/bin/kilo"),
            os.path.expanduser("~/.local/bin/kilo.cmd"),
            os.path.expanduser("~/.npm-global/bin/kilo"),
            os.path.expanduser("~/.npm-global/bin/kilo.cmd"),
            os.path.expanduser("~/AppData/Roaming/npm/kilo"),
            os.path.expanduser("~/AppData/Roaming/npm/kilo.cmd"),
            "/usr/local/bin/kilo",
            "/usr/local/bin/kilo.cmd",
        ]
        
        # On Windows, prioritize .cmd files
        if sys.platform == "win32":
            # Reorder to check .cmd first
            cmd_candidates = [c for c in candidates if c.endswith(".cmd")]
            other_candidates = [c for c in candidates if not c.endswith(".cmd")]
            candidates = cmd_candidates + other_candidates
        
        for candidate in candidates:
            if os.path.exists(candidate) and os.path.isfile(candidate):
                return candidate
        return None

    def available(self) -> bool:
        """Check if Kilo is available."""
        return self._kilo_path is not None

    def _run_kilo(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        """Run a kilo CLI command."""
        if not self._kilo_path:
            raise RuntimeError("Kilo not found")
        
        # On Windows, .cmd files need special handling
        import sys
        if sys.platform == "win32" and self._kilo_path.endswith(".cmd"):
            # On Windows with .cmd, we need to use shell=True
            # Build command line with proper quoting for the executable path
            cmd_line = f'"{self._kilo_path}" {" ".join(args)}'
            result = subprocess.run(
                cmd_line,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                shell=True,
            )
        else:
            result = subprocess.run(
                [self._kilo_path] + args,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
            )
        return result

    def _parse_session_list(self, output: str) -> list[dict[str, Any]]:
        """Parse `kilo session list` output."""
        sessions = []
        lines = output.strip().split("\n")
        
        # Skip header line (first line)
        for line in lines[1:]:
            if not line.strip():
                continue
            
            # Parse: Session ID  Title  Updated
            parts = line.split()
            if len(parts) >= 3:
                session_id = parts[0]
                # Title may contain spaces, find the last part which is the time/date
                # This is a simplified parser - may need adjustment
                title_parts = parts[1:-2]  # Skip session_id and last 2 parts (time + date)
                title = " ".join(title_parts)
                updated = " ".join(parts[-2:])
                
                sessions.append({
                    "id": session_id,
                    "title": title,
                    "updated": updated,
                })
        
        return sessions

    def _parse_export(self, export_data: dict[str, Any]) -> tuple[AgentSession, list[dict[str, Any]]]:
        """Parse kilo export JSON into AgentSession and raw events."""
        info = export_data.get("info", {})
        
        session = AgentSession(
            source=AgentSessionSource.kilo,
            external_session_id=info.get("id", ""),
            project_path=info.get("directory"),
            title=info.get("title"),
            started_at=datetime.fromtimestamp(info.get("time", {}).get("created", 0) / 1000, tz=UTC),
            ended_at=datetime.fromtimestamp(info.get("time", {}).get("updated", 0) / 1000, tz=UTC) if info.get("time", {}).get("updated") else None,
            metadata={
                "agent": info.get("agent"),
                "model": info.get("model", {}),
                "version": info.get("version"),
                "summary": info.get("summary", {}),
                "cost": info.get("cost"),
                "tokens": info.get("tokens"),
                "projectID": info.get("projectID"),
            },
        )
        
        # Set status based on whether ended_at is set
        if session.ended_at:
            session.status = AgentSessionStatus.finished
        else:
            session.status = AgentSessionStatus.active
        
        # Parse messages into events
        raw_events = []
        messages = export_data.get("messages", [])
        
        for msg in messages:
            msg_info = msg.get("info", {})
            msg_summary = msg.get("summary", {})
            
            # Determine event type
            role = msg_info.get("role", "unknown")
            
            # Check for tool results
            if msg_summary.get("diffs"):
                event_type = AgentSessionEventType.tool_result
            elif role == "assistant":
                event_type = AgentSessionEventType.assistant_message
            elif role == "user":
                event_type = AgentSessionEventType.user_message
            else:
                event_type = AgentSessionEventType.assistant_message
            
            # Get timestamp
            created_ts = msg_info.get("time", {}).get("created", 0)
            occurred_at = datetime.fromtimestamp(created_ts / 1000, tz=UTC) if created_ts else datetime.now(UTC)
            
            content_parts = []
            if "content" in msg:
                content_parts.append(str(msg["content"]))
            if "summary" in msg:
                content_parts.append(f"Summary: {json.dumps(msg_summary, indent=2)}")
            
            content = "\n".join(content_parts) if content_parts else ""
            
            raw_events.append({
                "role": role,
                "event_type": event_type,
                "content": content,
                "occurred_at": occurred_at,
                "metadata": {
                    "agent": msg_info.get("agent"),
                    "model": msg_info.get("model", {}),
                    "diffs": msg_summary.get("diffs", []),
                },
            })
        
        return session, raw_events

    def discover_sessions(self, db: Session) -> list[AgentSession]:
        """Discover Kilo sessions."""
        if not self.available():
            return []
        
        try:
            result = self._run_kilo(["session", "list"])
            if result.returncode != 0:
                logger.warning("Failed to list Kilo sessions: %s", result.stderr)
                return []
            
            sessions_data = self._parse_session_list(result.stdout)
            discovered_sessions = []
            
            for session_info in sessions_data:
                session_id = session_info.get("id", "")
                
                # Skip if we've already processed this session
                if self._checkpoint.last_session_id == session_id:
                    continue
                
                # Try to export the session
                try:
                    export_result = self._run_kilo(["export", session_id])
                    if export_result.returncode != 0:
                        logger.warning("Failed to export session %s: %s", session_id, export_result.stderr)
                        continue
                    
                    export_data = json.loads(export_result.stdout)
                    session, _ = self._parse_export(export_data)
                    discovered_sessions.append(session)
                    
                except json.JSONDecodeError as e:
                    logger.warning("Failed to parse export for session %s: %s", session_id, e)
                    continue
            
            return discovered_sessions
            
        except Exception as e:
            logger.error("Error discovering Kilo sessions: %s", e)
            return []

    def read_new_events(
        self,
        session: AgentSession,
        db: Session,
    ) -> list[AgentSessionEvent]:
        """Read new events from a Kilo session."""
        if not self.available():
            return []
        
        # First-connect: do NOT process historical backlog.
        if self.is_first_connect():
            logger.info(
                "First connect for Kilo session %s — skipping historical events",
                session.external_session_id,
            )
            return []
        
        events = []
        
        try:
            # Export the session
            result = self._run_kilo(["export", session.external_session_id])
            if result.returncode != 0:
                logger.warning("Failed to export session %s: %s", session.external_session_id, result.stderr)
                return []
            
            export_data = json.loads(result.stdout)
            _, raw_events = self._parse_export(export_data)
            
            # Filter to only new events based on checkpoint
            for raw_event in raw_events:
                # Skip if we've already processed this event
                # For Kilo, we use the timestamp as the checkpoint
                event_ts = raw_event.get("occurred_at")
                if event_ts:
                    event_timestamp = event_ts.timestamp()
                    if event_timestamp <= self._checkpoint.last_event_timestamp:
                        continue
                
                # Create AgentSessionEvent
                event = AgentSessionEvent(
                    session_id=session.id,
                    source=AgentSessionSource.kilo,
                    external_event_id=None,  # Kilo doesn't provide stable event IDs
                    event_type=raw_event.get("event_type", AgentSessionEventType.assistant_message),
                    role=raw_event.get("role"),
                    content=raw_event.get("content", ""),
                    occurred_at=raw_event.get("occurred_at", datetime.now(UTC)),
                    metadata=raw_event.get("metadata", {}),
                )
                events.append(event)
            
        except Exception as e:
            logger.error("Error reading Kilo session events: %s", e)
        
        return events

    def checkpoint(
        self,
        session: AgentSession,
        db: Session,
        last_event: AgentSessionEvent | None = None,
    ) -> None:
        """Update checkpoint after processing — only advances, never regresses."""
        ts = last_event.occurred_at.timestamp() if last_event else session.last_seen_at.timestamp()
        self.advance_checkpoint(ts, session.external_session_id)
        
        # Update session status
        if session.ended_at:
            session.status = AgentSessionStatus.finished
        
        # Save to project metadata
        if self.project:
            self.save_checkpoint(self.project, db)
