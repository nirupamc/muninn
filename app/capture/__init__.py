"""Capture package for M8 Universal Project Discovery & Memory Capture."""

from app.capture.fingerprints import (
    make_agent_summary_fingerprint,
    make_filesystem_fingerprint,
    make_generic_fingerprint,
    make_git_fingerprint,
    make_time_bucketed_fingerprint,
)
from app.capture.manager import CaptureManager, capture_lifespan, get_capture_manager, set_capture_manager
from app.capture.project_resolver import ProjectResolver
from app.capture.repository import CaptureEventRepository
from app.capture.service import CaptureService

__all__ = [
    "CaptureEventRepository",
    "CaptureService",
    "ProjectResolver",
    "CaptureManager",
    "capture_lifespan",
    "get_capture_manager",
    "set_capture_manager",
    "make_git_fingerprint",
    "make_filesystem_fingerprint",
    "make_agent_summary_fingerprint",
    "make_generic_fingerprint",
    "make_time_bucketed_fingerprint",
]