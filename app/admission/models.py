"""Structured admission analysis models."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.models.memory import MemoryType


class ReasonCode(str, Enum):
    """Machine-readable admission reason codes."""

    HIGH_FUTURE_UTILITY = "HIGH_FUTURE_UTILITY"
    ONGOING_PROJECT = "ONGOING_PROJECT"
    STABLE_PREFERENCE = "STABLE_PREFERENCE"
    EXPLICIT_USER_STATEMENT = "EXPLICIT_USER_STATEMENT"
    EXPLICIT_REMEMBER_REQUEST = "EXPLICIT_REMEMBER_REQUEST"
    SPECIFIC_FACT = "SPECIFIC_FACT"
    LONG_TERM_GOAL = "LONG_TERM_GOAL"
    EXPLICIT_DECISION = "EXPLICIT_DECISION"
    LOW_FUTURE_UTILITY = "LOW_FUTURE_UTILITY"
    EPHEMERAL = "EPHEMERAL"
    TRIVIAL = "TRIVIAL"
    UNSUPPORTED_INFERENCE = "UNSUPPORTED_INFERENCE"
    SENSITIVE_DATA = "SENSITIVE_DATA"
    SECRET_LIKE_DATA = "SECRET_LIKE_DATA"
    TOO_UNCERTAIN = "TOO_UNCERTAIN"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    PROVIDER_RECOMMEND_IGNORE = "PROVIDER_RECOMMEND_IGNORE"


class AdmissionCandidate(BaseModel):
    """A proposed durable memory derived from an event."""

    content: str
    memory_type: MemoryType

    importance: float = Field(ge=0.0, le=1.0)
    confidence: float = Field(ge=0.0, le=1.0)
    future_utility: float = Field(ge=0.0, le=1.0)
    stability: float = Field(ge=0.0, le=1.0)
    specificity: float = Field(ge=0.0, le=1.0)
    explicitness: float = Field(ge=0.0, le=1.0)
    triviality: float = Field(ge=0.0, le=1.0)

    @field_validator("content")
    @classmethod
    def content_must_not_be_blank(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("candidate content must not be empty")
        return value.strip()


class CandidateAnalysis(BaseModel):
    """One candidate plus the provider's recommendation."""

    candidate: AdmissionCandidate
    provider_recommendation: Literal["STORE", "IGNORE"]
    reason_codes: list[ReasonCode] = Field(default_factory=list)
    explanation: str | None = None


class AdmissionAnalysis(BaseModel):
    """Provider output: zero or more candidate analyses."""

    candidates: list[CandidateAnalysis] = Field(default_factory=list)
