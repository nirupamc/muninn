"""Session event normalizer for M8.3.

Extracts meaningful events from raw agent session messages.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.capture.agent_sessions.models import (
    AgentSession,
    AgentSessionEvent,
    AgentSessionEventType,
    AgentSessionSource,
)
from app.models.capture import CaptureEventType, CaptureSource

logger = logging.getLogger("munin.capture.agent_sessions.normalizer")


class SessionNormalizer:
    """Normalizes raw agent session events into meaningful capture candidates."""

    # Patterns for detecting meaningful content
    DECISION_PATTERNS = [
        r"we will use\b",
        r"we should use\b",
        r"switch to\b",
        r"replace\b",
        r"change to\b",
        r"decide to\b",
        r"decision:\s",
        r"going with\b",
    ]

    FIX_PATTERNS = [
        r"fix(ed|ing)?\b",
        r"fixed\b",
        r"resolv(ed|e|ing)?\b",
        r"patch(ed|ing)?\b",
        r"repair(ed|ing)?\b",
    ]

    BUG_PATTERNS = [
        r"bug\b",
        r"issue\b",
        r"problem\b",
        r"defect\b",
        r"error\b",
        r"exception\b",
        r"failing\b",
        r"broken\b",
    ]

    MILESTONE_PATTERNS = [
        r"done\b",
        r"complete(d|d)?\b",
        r"finished\b",
        r"passed\b",
        r"passing\b",
        r"succeeded\b",
        r"success\b",
        r"verified\b",
    ]

    BLOCKER_PATTERNS = [
        r"block(ed|ing)?\b",
        r"stuck\b",
        r"cannot\b",
        r"can't\b",
        r"unable\b",
        r"waiting on\b",
        r"depends on\b",
    ]

    CONSTRAINT_PATTERNS = [
        r"must\b",
        r"should\b",
        r"require(ment|s)?\b",
        r"need to\b",
        r"constraint:\s",
        r"policy:\s",
    ]

    # Patterns that should be ignored
    TRIVIAL_PATTERNS = [
        r"^continue\b",
        r"^ok(ay)?\b",
        r"^yes\b",
        r"^no\b",
        r"^thanks?\b",
        r"^thx\b",
        r"^run (the )?tests?\b",
        r"^test\b",
        r"^try (it )?again\b",
        r"^what now\b",
        r"^fix this\b",
        r"^help\b",
        r"^how do\b",
        r"^what is\b",
    ]

    # Secret/credential patterns — reject before durable memory
    # NOTE: (?i) flags removed from patterns; use re.IGNORECASE at compile time
    SECRET_PATTERNS = [
        r"(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[=:]\s*\S+",
        r"(password|passwd|pwd)\s*[=:]\s*\S+",
        r"sk-[a-zA-Z0-9_-]{20,}",
        r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----",
        r"-----BEGIN\s+EC\s+PRIVATE\s+KEY-----",
        r"(OPENAI|ANTHROPIC|GITHUB|AWS)_API_KEY\s*=\s*\S+",
        r"DATABASE_URL\s*=\s*\S+",
        r"(private[_-]?key|client[_-]?secret)\s*[=:]\s*\S+",
    ]

    # Tool result patterns
    TOOL_SUCCESS_PATTERNS = [
        r"passed\b",
        r"succeeded\b",
        r"ok\b",
        r"success\b",
        r"tests? passed\b",
        r"build succeeded\b",
    ]

    TOOL_FAILURE_PATTERNS = [
        r"failed\b",
        r"error\b",
        r"exception\b",
        r"tests? failed\b",
        r"build failed\b",
    ]

    # M12: Map AgentSessionEventType → CaptureEventType for new types
    _EVENT_TYPE_MAP: dict[AgentSessionEventType, CaptureEventType] = {
        AgentSessionEventType.tool_call: CaptureEventType.agent_tool_result,
        AgentSessionEventType.tool_result: CaptureEventType.agent_tool_result,
        AgentSessionEventType.decision: CaptureEventType.decision_event,
        AgentSessionEventType.bug: CaptureEventType.error_event,
        AgentSessionEventType.fix: CaptureEventType.agent_decision,
        AgentSessionEventType.milestone: CaptureEventType.agent_summary,
        AgentSessionEventType.blocker: CaptureEventType.blocker_event,
        AgentSessionEventType.constraint: CaptureEventType.manual_note,
    }

    # M12: Map observation type string → CaptureEventType
    _OBS_TYPE_MAP: dict[str, CaptureEventType] = {
        "command_run": CaptureEventType.command_run,
        "command_result": CaptureEventType.command_result,
        "test_run": CaptureEventType.test_run,
        "test_result": CaptureEventType.test_result,
        "file_edit": CaptureEventType.file_edit,
        "file_create": CaptureEventType.file_create,
        "file_delete": CaptureEventType.file_delete,
        "error": CaptureEventType.error_event,
        "warning": CaptureEventType.warning_event,
        "blocker": CaptureEventType.blocker_event,
        "decision": CaptureEventType.decision_event,
        "verification": CaptureEventType.verification,
        "build_result": CaptureEventType.build_result,
        "api_result": CaptureEventType.api_result,
        "git_commit": CaptureEventType.git_commit,
    }

    def __init__(self) -> None:
        self._decision_re = re.compile("|".join(self.DECISION_PATTERNS), re.IGNORECASE)
        self._fix_re = re.compile("|".join(self.FIX_PATTERNS), re.IGNORECASE)
        self._bug_re = re.compile("|".join(self.BUG_PATTERNS), re.IGNORECASE)
        self._milestone_re = re.compile("|".join(self.MILESTONE_PATTERNS), re.IGNORECASE)
        self._blocker_re = re.compile("|".join(self.BLOCKER_PATTERNS), re.IGNORECASE)
        self._constraint_re = re.compile("|".join(self.CONSTRAINT_PATTERNS), re.IGNORECASE)
        self._trivial_re = re.compile("|".join(self.TRIVIAL_PATTERNS), re.IGNORECASE)
        self._secret_re = re.compile("|".join(self.SECRET_PATTERNS), re.IGNORECASE)
        self._tool_success_re = re.compile("|".join(self.TOOL_SUCCESS_PATTERNS), re.IGNORECASE)
        self._tool_failure_re = re.compile("|".join(self.TOOL_FAILURE_PATTERNS), re.IGNORECASE)
        # M12: Structured observation normalizer (lazy init to avoid circular import)
        self._obs_normalizer = None

    def contains_secret(self, content: str | list | dict | None) -> bool:
        """Check if content contains secrets or credentials.

        Returns True if the content looks like it contains API keys,
        passwords, private keys, or other sensitive data that should
        NOT be stored as durable memory.
        """
        if content is None:
            return False

        if isinstance(content, list):
            content = " ".join(str(item) for item in content)

        if isinstance(content, dict):
            content = str(content)

        if not isinstance(content, str):
            content = str(content)

        if not content:
            return False

        return bool(self._secret_re.search(content))

    def is_trivial(self, content: str | list | dict | None) -> bool:
        """Check if content is trivial and should be ignored."""
        # Normalize content to string
        if content is None:
            return True
        
        if isinstance(content, list):
            content = " ".join(str(item) for item in content)
        
        if isinstance(content, dict):
            content = str(content)
        
        if not isinstance(content, str):
            content = str(content)
        
        if not content or len(content.strip()) < 3:
            return True
        
        content_lower = content.lower()
        
        # Check for trivial patterns
        if self._trivial_re.search(content_lower):
            return True
        
        # Check for very short content
        if len(content.strip().split()) < 2:
            return True
        
        return False

    def classify_event_type(self, content: str | list | dict | None, role: str | None = None, event_type: AgentSessionEventType | None = None) -> AgentSessionEventType:
        """Classify the semantic event type based on content."""
        # Normalize content to string
        if content is None:
            return AgentSessionEventType.assistant_message
        if isinstance(content, list):
            content = " ".join(str(item) for item in content)
        if isinstance(content, dict):
            content = str(content)
        if not isinstance(content, str):
            content = str(content)
        
        content_lower = content.lower()
        
        # If already classified as tool_call/tool_result, keep it
        if event_type in (AgentSessionEventType.tool_call, AgentSessionEventType.tool_result):
            return event_type
        
        # Check for decisions
        if self._decision_re.search(content_lower):
            return AgentSessionEventType.decision
        
        # Check for fixes
        if self._fix_re.search(content_lower):
            return AgentSessionEventType.fix
        
        # Check for bugs
        if self._bug_re.search(content_lower):
            return AgentSessionEventType.bug
        
        # Check for milestones
        if self._milestone_re.search(content_lower):
            return AgentSessionEventType.milestone
        
        # Check for blockers
        if self._blocker_re.search(content_lower):
            return AgentSessionEventType.blocker
        
        # Check for constraints
        if self._constraint_re.search(content_lower):
            return AgentSessionEventType.constraint
        
        # Default based on role
        if role == "user":
            return AgentSessionEventType.user_message
        elif role == "assistant":
            return AgentSessionEventType.assistant_message
        
        return AgentSessionEventType.assistant_message

    def extract_tool_summary(self, content: str, metadata: dict[str, Any]) -> str | None:
        """Extract a summary from tool results (e.g., pytest output)."""
        diffs = metadata.get("diffs", [])
        
        if diffs:
            # Count files changed
            file_count = len(diffs)
            additions = sum(d.get("additions", 0) for d in diffs)
            deletions = sum(d.get("deletions", 0) for d in diffs)
            
            # Get modified files
            files = [d.get("file", "") for d in diffs if d.get("status") == "modified"]
            added = [d.get("file", "") for d in diffs if d.get("status") == "added"]
            deleted = [d.get("file", "") for d in diffs if d.get("status") == "deleted"]
            
            summary_parts = []
            
            if added:
                summary_parts.append(f"Created {len(added)} file(s)")
            if deleted:
                summary_parts.append(f"Deleted {len(deleted)} file(s)")
            if files:
                summary_parts.append(f"Modified {len(files)} file(s)")
            
            if additions or deletions:
                summary_parts.append(f"({additions} additions, {deletions} deletions)")
            
            if summary_parts:
                return "; ".join(summary_parts)
        
        # Check for test results in content
        if self._tool_success_re.search(content.lower()):
            return "Tool execution succeeded"
        
        if self._tool_failure_re.search(content.lower()):
            return "Tool execution failed"
        
        return None

    def build_capture_event(
        self,
        session: AgentSession,
        event: AgentSessionEvent,
    ) -> dict[str, Any] | None:
        """Build a normalized capture event from a session event.
        
        Returns None if the event should be ignored.
        """
        # Ensure content is normalized to string for processing
        content = event.content
        if isinstance(content, list):
            content = " ".join(str(item) for item in content)
        elif isinstance(content, dict):
            content = str(content)
        elif not isinstance(content, str):
            content = str(content) if content else ""
        
        # Create a copy of the event with normalized content
        normalized_event = AgentSessionEvent(
            id=event.id,
            session_id=event.session_id,
            source=event.source,
            external_event_id=event.external_event_id,
            event_type=event.event_type,
            role=event.role,
            content=content,
            occurred_at=event.occurred_at,
            metadata=event.metadata,
            fingerprint=event.fingerprint,
        )
        
        # Skip trivial events
        if self.is_trivial(normalized_event.content):
            return None

        # Skip secret/credential content
        if self.contains_secret(normalized_event.content):
            logger.info(
                "Rejected event with secret content from session %s",
                session.id,
            )
            return None
        
        # Classify the event
        classified_type = self.classify_event_type(
            normalized_event.content,
            normalized_event.role,
            normalized_event.event_type,
        )
        
        # Extract tool summary if available
        tool_summary = None
        if normalized_event.event_type == AgentSessionEventType.tool_result:
            tool_summary = self.extract_tool_summary(normalized_event.content, normalized_event.metadata)
        
        # Build content
        content_parts = []
        
        # Add role prefix
        if normalized_event.role:
            content_parts.append(f"[{normalized_event.role.upper()}]")
        
        # Add the actual content
        content_parts.append(normalized_event.content)
        
        # Add tool summary if extracted
        if tool_summary:
            content_parts.append(f"\nResult: {tool_summary}")
        
        content = "\n".join(content_parts)
        
        # M12: Use structured observation normalizer for richer extraction
        observation = None
        try:
            from app.observations.normalizer import ObservationNormalizer as _ObsNorm
            if self._obs_normalizer is None:
                self._obs_normalizer = _ObsNorm()
            observation = self._obs_normalizer.normalize_event(
                normalized_event,
                agent_host=session.source.value if isinstance(session.source, AgentSessionSource) else str(session.source),
                model=session.metadata.get("model") if isinstance(session.metadata.get("model"), str) else (
                    session.metadata.get("model", {}).get("id") if isinstance(session.metadata.get("model"), dict) else None
                ),
                project_id=session.project_id,
                namespace=session.namespace,
            )
        except Exception:
            observation = None

        # Map to capture event type (prefer observation-based mapping)
        if observation and observation.type.value in self._OBS_TYPE_MAP:
            capture_type = self._OBS_TYPE_MAP[observation.type.value]
        elif classified_type in self._EVENT_TYPE_MAP:
            capture_type = self._EVENT_TYPE_MAP[classified_type]
        elif classified_type == AgentSessionEventType.user_message:
            # Only capture meaningful user messages
            if not self.is_trivial(event.content):
                capture_type = CaptureEventType.manual_note
            else:
                return None
        else:
            capture_type = CaptureEventType.agent_summary        # Build fingerprint
        import hashlib
        fingerprint = hashlib.sha256(
            f"{session.id}|{event.session_id}|{classified_type.value}|{content}".encode()
        ).hexdigest()[:64]

        # M12: Enrich metadata with observation data
        metadata = {
            "agent_session_id": event.session_id,
            "agent_session_source": session.source.value,
            "agent_session_event_type": classified_type.value,
            "role": event.role,
            "external_event_id": event.external_event_id,
            "tool_summary": tool_summary,
            **event.metadata,
        }

        # Add observation-specific metadata if available
        if observation:
            metadata["observation_type"] = observation.type.value
            metadata["observation_id"] = observation.id
            if observation.structured_data:
                metadata["structured_data"] = observation.structured_data
            if observation.actor:
                metadata["actor"] = observation.actor
            if observation.model:
                metadata["model"] = observation.model
            if observation.agent_host:
                metadata["agent_host"] = observation.agent_host

        return {
            "event_type": capture_type,
            "content": content,
            "metadata": metadata,
            "occurred_at": event.occurred_at,
            "fingerprint": fingerprint,
            "agent_id": session.metadata.get("agent") or session.source.value,
            "session_id": event.session_id,
            "working_directory": session.project_path,
        }

    def build_session_summary(self, session: AgentSession, events: list[AgentSessionEvent]) -> dict[str, Any] | None:
        """Build a session summary capture event.
        
        Creates a summary of the entire session's meaningful activity.
        """
        if not events:
            return None
        
        # Filter to non-trivial events
        meaningful_events = [e for e in events if not self.is_trivial(e.content)]
        
        if not meaningful_events:
            return None
        
        # Categorize events
        decisions = [e for e in meaningful_events if self.classify_event_type(e.content, e.role, e.event_type) == AgentSessionEventType.decision]
        fixes = [e for e in meaningful_events if self.classify_event_type(e.content, e.role, e.event_type) == AgentSessionEventType.fix]
        bugs = [e for e in meaningful_events if self.classify_event_type(e.content, e.role, e.event_type) == AgentSessionEventType.bug]
        milestones = [e for e in meaningful_events if self.classify_event_type(e.content, e.role, e.event_type) == AgentSessionEventType.milestone]
        blockers = [e for e in meaningful_events if self.classify_event_type(e.content, e.role, e.event_type) == AgentSessionEventType.blocker]
        constraints = [e for e in meaningful_events if self.classify_event_type(e.content, e.role, e.event_type) == AgentSessionEventType.constraint]
        
        # Build summary
        summary_parts = []
        
        if session.title:
            summary_parts.append(f"Session: {session.title}")
        
        if session.project_path:
            summary_parts.append(f"Project: {session.project_path}")
        
        # Add counts
        counts = []
        if decisions:
            counts.append(f"{len(decisions)} decision(s)")
        if fixes:
            counts.append(f"{len(fixes)} fix(es)")
        if bugs:
            counts.append(f"{len(bugs)} bug(s)")
        if milestones:
            counts.append(f"{len(milestones)} milestone(s)")
        if blockers:
            counts.append(f"{len(blockers)} blocker(s)")
        if constraints:
            counts.append(f"{len(constraints)} constraint(s)")
        
        if counts:
            summary_parts.append(f"Activity: {', '.join(counts)}")
        
        # Add session metadata
        if session.metadata.get("model"):
            model_info = session.metadata["model"]
            if isinstance(model_info, dict):
                model_name = model_info.get("id", "unknown")
            else:
                model_name = str(model_info)
            summary_parts.append(f"Model: {model_name}")
        
        if session.metadata.get("tokens"):
            tokens = session.metadata["tokens"]
            if isinstance(tokens, dict):
                input_tokens = tokens.get("input", 0)
                output_tokens = tokens.get("output", 0)
                summary_parts.append(f"Tokens: {input_tokens} in, {output_tokens} out")
        
        content = "\n".join(summary_parts)
        
        # Build fingerprint
        import hashlib
        fingerprint = hashlib.sha256(
            f"{session.id}|session_summary|{len(meaningful_events)}".encode()
        ).hexdigest()[:64]
        
        return {
            "event_type": CaptureEventType.agent_summary,
            "content": content,
            "metadata": {
                "agent_session_id": session.id,
                "agent_session_source": session.source.value,
                "event_count": len(meaningful_events),
                "decision_count": len(decisions),
                "fix_count": len(fixes),
                "bug_count": len(bugs),
                "milestone_count": len(milestones),
                "blocker_count": len(blockers),
                "constraint_count": len(constraints),
                "session_title": session.title,
                "session_started": session.started_at.isoformat() if session.started_at else None,
                "session_ended": session.ended_at.isoformat() if session.ended_at else None,
            },
            "occurred_at": session.ended_at or session.started_at or datetime.now(UTC),
            "fingerprint": fingerprint,
            "agent_id": session.metadata.get("agent") or session.source.value,
            "session_id": session.id,
            "working_directory": session.project_path,
        }
