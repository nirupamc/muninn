"""OpenAI-compatible chat-completions temporal relationship provider."""

from __future__ import annotations

import json
import logging
from datetime import datetime

import httpx

from app.models.memory import MemoryType
from app.temporal.base import TemporalRelationshipError, TemporalRelationshipProvider
from app.temporal.models import TemporalRelationshipAnalysis

logger = logging.getLogger("munin.temporal")

_SYSTEM_PROMPT = """You classify how a memory candidate relates temporally to one existing memory for Munin.
Return ONLY valid JSON matching this schema:
{
  "relationship": "NEW" | "UPDATES" | "CONTRADICTS" | "SUPERSEDES",
  "confidence": 0.0-1.0,
  "explanation": "short optional string",
  "replacement_scope": "optional short string or null"
}

Definitions:
- NEW: genuinely additional information (even if related).
- UPDATES: same subject/fact with changed details; old should become historical.
- CONTRADICTS: conflicts with existing memory but replacement is not explicit; keep both active.
- SUPERSEDES: explicit replacement of prior state/preference (now, no longer, switched, used to→now).

Rules:
- Preserve and reason over polarity and temporal phrases: not, no longer, still, used to, now, currently, switched, migrated, stopped, anymore.
- Do NOT use embedding similarity alone.
- When uncertain, prefer NEW with lower confidence.
- Do not invent timestamps.
"""


class OpenAICompatibleTemporalProvider(TemporalRelationshipProvider):
    """Calls an OpenAI-compatible /chat/completions endpoint."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not base_url or not base_url.strip():
            raise TemporalRelationshipError(
                "TEMPORAL_BASE_URL is required for openai_compatible provider"
            )
        if not model or not model.strip():
            raise TemporalRelationshipError(
                "TEMPORAL_MODEL is required for openai_compatible provider"
            )
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key or ""
        self._timeout = timeout_seconds

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    @property
    def model_name(self) -> str:
        return self._model

    def classify(
        self,
        *,
        candidate: str,
        existing_memory: str,
        candidate_type: MemoryType,
        existing_type: MemoryType,
        candidate_event_time: datetime | None = None,
        existing_valid_from: datetime | None = None,
        existing_valid_until: datetime | None = None,
    ) -> TemporalRelationshipAnalysis:
        payload = {
            "model": self._model,
            "temperature": 0.0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "candidate": candidate,
                            "candidate_type": candidate_type.value,
                            "existing_memory": existing_memory,
                            "existing_type": existing_type.value,
                            "candidate_event_time": (
                                candidate_event_time.isoformat()
                                if candidate_event_time
                                else None
                            ),
                            "existing_valid_from": (
                                existing_valid_from.isoformat()
                                if existing_valid_from
                                else None
                            ),
                            "existing_valid_until": (
                                existing_valid_until.isoformat()
                                if existing_valid_until
                                else None
                            ),
                        }
                    ),
                },
            ],
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        url = f"{self._base_url}/chat/completions"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Temporal provider unavailable provider=%s model=%s",
                self.provider_name,
                self._model,
            )
            raise TemporalRelationshipError("Temporal provider unavailable") from exc

        try:
            message = data["choices"][0]["message"]["content"]
            parsed = json.loads(message) if isinstance(message, str) else message
            return TemporalRelationshipAnalysis.model_validate(parsed)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Temporal provider returned invalid structured output provider=%s model=%s",
                self.provider_name,
                self._model,
            )
            raise TemporalRelationshipError(
                "Temporal provider returned invalid output"
            ) from exc
