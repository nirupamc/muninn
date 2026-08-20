"""Event request/response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.event import EventRole


class EventCreate(BaseModel):
    """Payload for creating an event."""

    namespace: str = Field(..., min_length=1)
    user_id: str | None = None
    agent_id: str | None = None
    session_id: str | None = None
    role: EventRole
    content: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("content must not be empty or whitespace-only")
        return value

    @field_validator("namespace")
    @classmethod
    def namespace_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("namespace must not be empty or whitespace-only")
        return value.strip()


class EventRead(BaseModel):
    """Event returned by the API."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    namespace: str
    user_id: str | None
    agent_id: str | None
    session_id: str | None
    role: EventRole
    content: str
    created_at: datetime
    metadata: dict[str, Any] = Field(validation_alias="metadata_")

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:  # type: ignore[override]
        data = super().model_dump(**kwargs)
        # Ensure consumers always see "metadata", not "metadata_"
        return data
