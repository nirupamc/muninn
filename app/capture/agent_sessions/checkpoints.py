"""Agent session checkpointing for preventing replay and duplicate capture."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentSessionCheckpoint:
    """Checkpoint state for agent session adapters.
    
    Tracks the last processed session/event to prevent replay after restart.
    """

    # Last session ID that was fully processed
    last_session_id: str | None = None
    
    # Last event ordinal/external ID that was processed for each session
    last_event_id: str | None = None
    
    # Last event timestamp that was processed
    last_event_timestamp: float = 0.0
    
    # File offset for JSONL-based adapters (Codex)
    file_offset: int = 0
    
    # For SQLite-based adapters, last row ID
    last_row_id: int = 0
    
    # Additional adapter-specific checkpoint data
    adapter_metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        """Serialize checkpoint to JSON string for storage."""
        return json.dumps({
            "last_session_id": self.last_session_id,
            "last_event_id": self.last_event_id,
            "last_event_timestamp": self.last_event_timestamp,
            "file_offset": self.file_offset,
            "last_row_id": self.last_row_id,
            "adapter_metadata": self.adapter_metadata,
        })

    @classmethod
    def from_json(cls, data: str | dict[str, Any]) -> "AgentSessionCheckpoint":
        """Deserialize checkpoint from JSON string or dict."""
        if isinstance(data, str):
            obj = json.loads(data)
        else:
            obj = data
        
        return cls(
            last_session_id=obj.get("last_session_id"),
            last_event_id=obj.get("last_event_id"),
            last_event_timestamp=obj.get("last_event_timestamp", 0.0),
            file_offset=obj.get("file_offset", 0),
            last_row_id=obj.get("last_row_id", 0),
            adapter_metadata=obj.get("adapter_metadata", {}),
        )

    def update(
        self,
        session_id: str | None = None,
        event_id: str | None = None,
        timestamp: float | None = None,
        file_offset: int | None = None,
        row_id: int | None = None,
        adapter_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Update checkpoint with new values."""
        if session_id is not None:
            self.last_session_id = session_id
        if event_id is not None:
            self.last_event_id = event_id
        if timestamp is not None:
            self.last_event_timestamp = timestamp
        if file_offset is not None:
            self.file_offset = file_offset
        if row_id is not None:
            self.last_row_id = row_id
        if adapter_metadata is not None:
            self.adapter_metadata.update(adapter_metadata)
