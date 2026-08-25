"""Fingerprint utilities for capture idempotency."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from app.models.capture import CaptureSource, CaptureEventType
from app.models.project import Project


def make_git_fingerprint(project: Project, commit_sha: str) -> str:
    """Create fingerprint for Git commit."""
    data = f"{project.id}|{CaptureSource.git.value}|{CaptureEventType.git_commit.value}|{commit_sha}".encode()
    return hashlib.sha256(data).hexdigest()[:64]


def make_filesystem_fingerprint(project: Project, changed_files: list[str]) -> str:
    """Create fingerprint for filesystem batch."""
    file_list = "\n".join(sorted(changed_files))
    data = f"{project.id}|{CaptureSource.filesystem.value}|{CaptureEventType.file_batch_changed.value}|{file_list}".encode()
    return hashlib.sha256(data).hexdigest()[:64]


def make_agent_summary_fingerprint(project: Project, agent_id: str, session_id: str, content: str) -> str:
    """Create fingerprint for agent summary."""
    data = f"{project.id}|{CaptureSource.generic.value}|{CaptureEventType.agent_summary.value}|{agent_id}|{session_id}|{content}".encode()
    return hashlib.sha256(data).hexdigest()[:64]


def make_generic_fingerprint(
    project: Project,
    source: CaptureSource,
    event_type: CaptureEventType,
    *parts: str,
) -> str:
    """Create a generic fingerprint."""
    joined = "|".join(parts)
    data = f"{project.id}|{source.value}|{event_type.value}|{joined}".encode()
    return hashlib.sha256(data).hexdigest()[:64]


def make_time_bucketed_fingerprint(
    project: Project,
    source: CaptureSource,
    event_type: CaptureEventType,
    occurred_at: datetime,
    bucket_minutes: int = 30,
    *parts: str,
) -> str:
    """Create a time-bucketed fingerprint for batched events."""
    # Round to bucket
    bucket_ts = int(occurred_at.timestamp() // (bucket_minutes * 60))
    bucket_str = str(bucket_ts)
    joined = "|".join(parts)
    data = f"{project.id}|{source.value}|{event_type.value}|{bucket_str}|{joined}".encode()
    return hashlib.sha256(data).hexdigest()[:64]