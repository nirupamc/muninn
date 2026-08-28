"""M12 — Observation normalizer.

Converts raw agent session events, tool outputs, and structured data
into canonical Observation objects.

Design principles:
- Normalizes event type, timestamps, project identity, agent/model provenance
- Removes transport noise
- Extracts structured fields
- Preserves technical identifiers
- Does NOT decide admission — that remains Admission's job
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime
from typing import Any

from app.capture.agent_sessions.models import (
    AgentSessionEvent,
    AgentSessionEventType,
    AgentSessionSource,
)
from app.observations.models import Observation, ObservationType

logger = logging.getLogger("munin.observations.normalizer")

# Command detection patterns
_COMMAND_PATTERNS = [
    (re.compile(r"^(pytest|python -m pytest)\b", re.IGNORECASE), "pytest"),
    (re.compile(r"^(npm test|npx vitest|npx jest)\b", re.IGNORECASE), "npm_test"),
    (re.compile(r"^(cargo test)\b", re.IGNORECASE), "cargo_test"),
    (re.compile(r"^(go test)\b", re.IGNORECASE), "go_test"),
    (re.compile(r"^(git)\b", re.IGNORECASE), "git"),
    (re.compile(r"^(pip install|npm install|cargo build)\b", re.IGNORECASE), "install"),
    (re.compile(r"^(alembic)\b", re.IGNORECASE), "alembic"),
    (re.compile(r"^(uvicorn|python -m)\b", re.IGNORECASE), "run"),
]

# Test result parsing patterns
_TEST_PASSED_RE = re.compile(r"(\d+)\s+(?:passed|tests? passed)", re.IGNORECASE)
_TEST_FAILED_RE = re.compile(r"(\d+)\s+(?:failed|tests? failed)", re.IGNORECASE)
_TEST_SKIPPED_RE = re.compile(r"(\d+)\s+skipped", re.IGNORECASE)
_TEST_ERROR_RE = re.compile(r"(\d+)\s+error", re.IGNORECASE)
_TEST_DURATION_RE = re.compile(r"finished in\s+([\d.]+)s", re.IGNORECASE)
_TEST_EXIT_CODE_RE = re.compile(r"exit code[:\s]+(\d+)", re.IGNORECASE)

# File edit detection
_FILE_EDIT_RE = re.compile(
    r"(?:modified|edited|updated|changed|wrote|created|rewritten):\s*(.+)",
    re.IGNORECASE,
)
_FILE_CREATE_RE = re.compile(r"(?:created|new file):\s*(.+)", re.IGNORECASE)
_FILE_DELETE_RE = re.compile(r"(?:deleted|removed):\s*(.+)", re.IGNORECASE)

# Error detection
_ERROR_TYPE_RE = re.compile(
    r"(\w+(?:\.\w+)*(?:Error|Exception|Fault))\b"
)
_EXIT_CODE_ERROR_RE = re.compile(r"exit code[:\s]+([1-9]\d*)", re.IGNORECASE)

# Decision detection
_DECISION_RE = re.compile(
    r"(?:decision|decided|will use|should use|switching to|going with|chose)\b",
    re.IGNORECASE,
)

# Verification detection
_VERIFICATION_RE = re.compile(
    r"(?:verified|confirmation|confirmed|all.*pass|checks?\s+pass|diff.*clean)",
    re.IGNORECASE,
)


class ObservationNormalizer:
    """Normalizes raw agent/tool events into canonical Observations.

    This is a stateless normalizer — it classifies and extracts structure
    but does not persist or decide admission.
    """

    def normalize_event(
        self,
        event: AgentSessionEvent,
        *,
        agent_host: str | None = None,
        model: str | None = None,
        project_id: str | None = None,
        namespace: str | None = None,
    ) -> Observation | None:
        """Normalize a single agent session event into an Observation.

        Returns None if the event should be ignored (trivial/noise).
        """
        content = self._normalize_content(event.content)
        if not content:
            return None

        # Trivial filtering
        if self._is_trivial(content):
            return None

        # Secret filtering
        if self._contains_secret(content):
            logger.debug("Rejected observation with secret content")
            return None

        # Classify observation type
        obs_type = self._classify_type(content, event)

        # Extract structured data based on type
        structured = self._extract_structured(content, obs_type, event)

        # Determine actor
        actor = self._determine_actor(event, agent_host)

        return Observation(
            type=obs_type,
            project_id=project_id,
            namespace=namespace,
            agent_host=agent_host,
            model=model,
            session_id=event.session_id,
            actor=actor,
            action=obs_type.value,
            target=self._extract_target(content, structured),
            content=content,
            structured_data=structured,
            source=event.source.value if isinstance(event.source, AgentSessionSource) else str(event.source),
            source_event_id=event.external_event_id,
            timestamp=event.occurred_at,
            metadata={
                "original_event_type": event.event_type.value if isinstance(event.event_type, AgentSessionEventType) else str(event.event_type),
                "role": event.role,
                "fingerprint": event.fingerprint,
            },
        )

    def normalize_command(
        self,
        command: str,
        *,
        cwd: str | None = None,
        exit_code: int | None = None,
        stdout: str | None = None,
        stderr: str | None = None,
        agent_host: str | None = None,
        model: str | None = None,
        project_id: str | None = None,
        namespace: str | None = None,
        session_id: str | None = None,
    ) -> Observation:
        """Create a COMMAND_RUN observation from a shell command."""
        structured: dict[str, Any] = {"command": command}
        if cwd:
            structured["cwd"] = cwd
        if exit_code is not None:
            structured["exit_code"] = exit_code

        obs_type = ObservationType.COMMAND_RUN

        # Check if this is a test command
        if any(pat.match(command) for pat, _ in _COMMAND_PATTERNS if _ == "pytest"):
            obs_type = ObservationType.TEST_RUN

        # If we have output, check for test results
        output = stdout or stderr or ""
        if output and obs_type == ObservationType.TEST_RUN:
            test_data = self._parse_test_output(output)
            if test_data:
                structured.update(test_data)
                obs_type = ObservationType.TEST_RESULT

        return Observation(
            type=obs_type,
            project_id=project_id,
            namespace=namespace,
            agent_host=agent_host,
            model=model,
            session_id=session_id,
            actor=agent_host or "system",
            action="execute_command",
            target=command.split()[0] if command else None,
            content=command,
            structured_data=structured,
            source=agent_host or "unknown",
        )

    def normalize_test_result(
        self,
        framework: str,
        passed: int,
        failed: int,
        *,
        skipped: int = 0,
        errors: int = 0,
        duration_seconds: float | None = None,
        command: str | None = None,
        agent_host: str | None = None,
        model: str | None = None,
        project_id: str | None = None,
        namespace: str | None = None,
        session_id: str | None = None,
    ) -> Observation:
        """Create a TEST_RESULT observation from structured test data."""
        total = passed + failed + skipped + errors
        content_parts = [f"{framework}: {passed}/{total} tests passed"]
        if failed:
            content_parts.append(f"{failed} failed")
        if skipped:
            content_parts.append(f"{skipped} skipped")
        if errors:
            content_parts.append(f"{errors} errors")
        if duration_seconds is not None:
            content_parts.append(f"in {duration_seconds:.2f}s")

        structured: dict[str, Any] = {
            "framework": framework,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
            "errors": errors,
            "total": total,
        }
        if duration_seconds is not None:
            structured["duration_seconds"] = duration_seconds
        if command:
            structured["command"] = command

        return Observation(
            type=ObservationType.TEST_RESULT,
            project_id=project_id,
            namespace=namespace,
            agent_host=agent_host,
            model=model,
            session_id=session_id,
            actor=agent_host or "system",
            action="test",
            target=framework,
            content=", ".join(content_parts),
            structured_data=structured,
            source=agent_host or "unknown",
        )

    def normalize_file_change(
        self,
        path: str,
        operation: str,
        *,
        additions: int = 0,
        deletions: int = 0,
        agent_host: str | None = None,
        model: str | None = None,
        project_id: str | None = None,
        namespace: str | None = None,
        session_id: str | None = None,
    ) -> Observation:
        """Create a FILE_EDIT/CREATE/DELETE observation."""
        if operation == "create":
            obs_type = ObservationType.FILE_CREATE
        elif operation == "delete":
            obs_type = ObservationType.FILE_DELETE
        else:
            obs_type = ObservationType.FILE_EDIT

        content_parts = [f"{operation.capitalize()}d {path}"]
        if additions or deletions:
            content_parts.append(f"(+{additions}/-{deletions})")

        structured: dict[str, Any] = {
            "path": path,
            "operation": operation,
        }
        if additions:
            structured["additions"] = additions
        if deletions:
            structured["deletions"] = deletions

        return Observation(
            type=obs_type,
            project_id=project_id,
            namespace=namespace,
            agent_host=agent_host,
            model=model,
            session_id=session_id,
            actor=agent_host or "system",
            action=f"file_{operation}",
            target=path,
            content=" ".join(content_parts),
            structured_data=structured,
            source=agent_host or "unknown",
        )

    def normalize_error(
        self,
        error_type: str,
        message: str,
        *,
        component: str | None = None,
        agent_host: str | None = None,
        model: str | None = None,
        project_id: str | None = None,
        namespace: str | None = None,
        session_id: str | None = None,
    ) -> Observation:
        """Create an ERROR observation."""
        structured: dict[str, Any] = {
            "error_type": error_type,
        }
        if component:
            structured["component"] = component

        return Observation(
            type=ObservationType.ERROR,
            project_id=project_id,
            namespace=namespace,
            agent_host=agent_host,
            model=model,
            session_id=session_id,
            actor=agent_host or "system",
            action="error",
            target=component,
            content=f"{error_type}: {message}",
            structured_data=structured,
            source=agent_host or "unknown",
        )

    def normalize_decision(
        self,
        content: str,
        *,
        agent_host: str | None = None,
        model: str | None = None,
        project_id: str | None = None,
        namespace: str | None = None,
        session_id: str | None = None,
    ) -> Observation:
        """Create a DECISION observation."""
        return Observation(
            type=ObservationType.DECISION,
            project_id=project_id,
            namespace=namespace,
            agent_host=agent_host,
            model=model,
            session_id=session_id,
            actor=agent_host or "assistant",
            action="decide",
            content=content,
            source=agent_host or "unknown",
        )

    def normalize_verification(
        self,
        what: str,
        result: str,
        *,
        agent_host: str | None = None,
        model: str | None = None,
        project_id: str | None = None,
        namespace: str | None = None,
        session_id: str | None = None,
    ) -> Observation:
        """Create a VERIFICATION observation."""
        return Observation(
            type=ObservationType.VERIFICATION,
            project_id=project_id,
            namespace=namespace,
            agent_host=agent_host,
            model=model,
            session_id=session_id,
            actor=agent_host or "system",
            action="verify",
            content=f"Verified: {what} — {result}",
            structured_data={"what": what, "result": result},
            source=agent_host or "unknown",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _normalize_content(self, content: Any) -> str:
        """Normalize content to a clean string."""
        if content is None:
            return ""
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    # Handle tool_use / tool_result blocks
                    if item.get("type") == "tool_use":
                        parts.append(f"[tool_use: {item.get('name', '?')}]")
                    elif item.get("type") == "tool_result":
                        rc = item.get("content", "")
                        if isinstance(rc, list):
                            for sub in rc:
                                if isinstance(sub, dict) and sub.get("type") == "text":
                                    parts.append(sub.get("text", ""))
                        elif isinstance(rc, str):
                            parts.append(rc)
                    elif item.get("type") == "text":
                        parts.append(item.get("text", ""))
                    # Skip thinking blocks
                elif isinstance(item, str):
                    parts.append(item)
            content = " ".join(parts)
        elif isinstance(content, dict):
            content = str(content)
        elif not isinstance(content, str):
            content = str(content)
        return content.strip()

    def _is_trivial(self, content: str) -> bool:
        """Check if content is trivial and should be ignored."""
        if not content or len(content.strip()) < 3:
            return True

        lower = content.lower().strip()
        trivial = {
            "continue", "ok", "okay", "yes", "no", "thanks", "thx",
            "done", "sure", "right", "got it", "understood",
        }
        if lower in trivial:
            return True

        # Single word
        if len(content.split()) < 2:
            return True

        return False

    def _contains_secret(self, content: str) -> bool:
        """Check if content contains secrets/credentials."""
        secret_patterns = [
            r"(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token)\s*[=:]",
            r"(password|passwd|pwd)\s*[=:]",
            r"sk-[a-zA-Z0-9_-]{20,}",
            r"-----BEGIN\s+(RSA\s+)?PRIVATE\s+KEY-----",
            r"(OPENAI|ANTHROPIC|GITHUB|AWS)_API_KEY\s*=",
            r"DATABASE_URL\s*=",
        ]
        for pattern in secret_patterns:
            if re.search(pattern, content, re.IGNORECASE):
                return True
        return False

    def _classify_type(self, content: str, event: AgentSessionEvent) -> ObservationType:
        """Classify the observation type based on content and event metadata."""
        content_lower = content.lower()

        # Check for test results FIRST (even if event type is tool_result)
        if _TEST_PASSED_RE.search(content) or _TEST_FAILED_RE.search(content):
            return ObservationType.TEST_RESULT

        # Check for error patterns FIRST
        if _ERROR_TYPE_RE.search(content) or _EXIT_CODE_ERROR_RE.search(content):
            return ObservationType.ERROR

        # If already a tool_call or tool_result, preserve that
        if isinstance(event.event_type, AgentSessionEventType):
            if event.event_type == AgentSessionEventType.tool_call:
                return ObservationType.TOOL_CALL
            if event.event_type == AgentSessionEventType.tool_result:
                return ObservationType.TOOL_RESULT

        # Decision
        if _DECISION_RE.search(content):
            return ObservationType.DECISION

        # Verification
        if _VERIFICATION_RE.search(content):
            return ObservationType.VERIFICATION

        # Error
        if _ERROR_TYPE_RE.search(content) or _EXIT_CODE_ERROR_RE.search(content):
            return ObservationType.ERROR

        # Test result indicators
        if _TEST_PASSED_RE.search(content) or _TEST_FAILED_RE.search(content):
            return ObservationType.TEST_RESULT

        # File changes
        if _FILE_CREATE_RE.search(content):
            return ObservationType.FILE_CREATE
        if _FILE_DELETE_RE.search(content):
            return ObservationType.FILE_DELETE
        if _FILE_EDIT_RE.search(content):
            return ObservationType.FILE_EDIT

        # Blocker
        if re.search(r"\b(block(?:ed|ing)?|stuck|cannot|can't|unable)\b", content_lower):
            return ObservationType.BLOCKER

        # Command detection
        for pattern, name in _COMMAND_PATTERNS:
            if pattern.match(content):
                return ObservationType.COMMAND_RUN

        # Default based on role
        if isinstance(event.role, str):
            if event.role == "user":
                return ObservationType.USER_MESSAGE
            if event.role == "assistant":
                return ObservationType.AGENT_MESSAGE

        return ObservationType.OTHER

    def _extract_structured(
        self, content: str, obs_type: ObservationType, event: AgentSessionEvent
    ) -> dict[str, Any]:
        """Extract structured data based on observation type."""
        structured: dict[str, Any] = {}

        if obs_type == ObservationType.TEST_RESULT:
            test_data = self._parse_test_output(content)
            if test_data:
                structured.update(test_data)

        elif obs_type == ObservationType.COMMAND_RUN:
            # First line is likely the command
            first_line = content.split("\n")[0].strip()
            structured["command"] = first_line

        elif obs_type == ObservationType.ERROR:
            error_match = _ERROR_TYPE_RE.search(content)
            if error_match:
                structured["error_type"] = error_match.group(1)

        elif obs_type == ObservationType.FILE_EDIT:
            edit_match = _FILE_EDIT_RE.search(content)
            if edit_match:
                structured["path"] = edit_match.group(1).strip()

        elif obs_type == ObservationType.FILE_CREATE:
            create_match = _FILE_CREATE_RE.search(content)
            if create_match:
                structured["path"] = create_match.group(1).strip()

        return structured

    def _parse_test_output(self, output: str) -> dict[str, Any] | None:
        """Parse test output for structured results."""
        passed_m = _TEST_PASSED_RE.search(output)
        failed_m = _TEST_FAILED_RE.search(output)
        skipped_m = _TEST_SKIPPED_RE.search(output)
        error_m = _TEST_ERROR_RE.search(output)
        duration_m = _TEST_DURATION_RE.search(output)

        if not (passed_m or failed_m):
            return None

        data: dict[str, Any] = {}
        if passed_m:
            data["passed"] = int(passed_m.group(1))
        if failed_m:
            data["failed"] = int(failed_m.group(1))
        if skipped_m:
            data["skipped"] = int(skipped_m.group(1))
        if error_m:
            data["errors"] = int(error_m.group(1))
        if duration_m:
            data["duration_seconds"] = float(duration_m.group(1))

        total = sum(v for v in data.values() if isinstance(v, int))
        if total > 0:
            data["total"] = total

        return data if data else None

    def _extract_target(self, content: str, structured: dict[str, Any]) -> str | None:
        """Extract the target of the observation."""
        if "path" in structured:
            return structured["path"]
        if "command" in structured:
            cmd = structured["command"]
            return cmd.split()[0] if cmd else None
        if "error_type" in structured:
            return structured["error_type"]
        return None

    def _determine_actor(self, event: AgentSessionEvent, agent_host: str | None) -> str:
        """Determine who/what performed the action."""
        if isinstance(event.role, str) and event.role:
            return event.role
        if agent_host:
            return agent_host
        return "system"
