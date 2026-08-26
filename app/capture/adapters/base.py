"""Capture adapter base class and protocol."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.models.capture import CaptureEventType, CaptureSource
from app.models.project import Project


@dataclass
class AdapterHealth:
    """Health status of a capture adapter."""

    name: str
    available: bool
    last_check: datetime
    error: str | None = None
    metadata: dict[str, Any] | None = None


class CaptureAdapter(ABC):
    """Base class for capture adapters."""

    name: CaptureSource

    # Whether this adapter participates in the polling/background discovery
    # loop. Push-based adapters (e.g. GenericCaptureBridge) receive events
    # via HTTP/CLI and must NOT be polled — their discover_events() has a
    # different contract and calling it from the polling loop is a bug.
    supports_polling: bool = True

    def __init__(self, project: Project) -> None:
        self.project = project

    @abstractmethod
    def available(self) -> bool:
        """Check if this adapter is available for the project."""
        ...

    @abstractmethod
    def discover_events(self) -> list[dict[str, Any]]:
        """Discover new events since last checkpoint.
        
        Returns a list of dicts with keys:
        - event_type: CaptureEventType
        - content: str
        - metadata: dict
        - occurred_at: datetime
        - fingerprint: str (optional, for idempotency)
        """
        ...

    @abstractmethod
    def checkpoint(self, event_data: dict[str, Any]) -> None:
        """Update adapter checkpoint state after processing an event."""
        ...

    def health(self) -> AdapterHealth:
        """Get adapter health status."""
        try:
            avail = self.available()
            return AdapterHealth(
                name=self.name.value,
                available=avail,
                last_check=datetime.now(),
            )
        except Exception as e:
            return AdapterHealth(
                name=self.name.value,
                available=False,
                last_check=datetime.now(),
                error=str(e),
            )