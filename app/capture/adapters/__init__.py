"""Capture adapters package."""

from app.capture.adapters.base import CaptureAdapter, AdapterHealth
from app.capture.adapters.generic import (
    GenericCaptureBridge,
    create_agent_summary_event,
    create_agent_decision_event,
    create_manual_note_event,
)
from app.capture.adapters.git import GitAdapter
from app.capture.adapters.filesystem import FilesystemAdapter

__all__ = [
    "CaptureAdapter",
    "AdapterHealth",
    "GitAdapter",
    "FilesystemAdapter",
    "GenericCaptureBridge",
    "create_agent_summary_event",
    "create_agent_decision_event",
    "create_manual_note_event",
]