"""OpenAI-compatible chat-completions relationship provider (local-first)."""

from __future__ import annotations

import json
import logging

import httpx

from app.deduplication.base import RelationshipError, RelationshipProvider
from app.deduplication.models import RelationshipAnalysis
from app.models.memory import MemoryType

logger = logging.getLogger("munin.deduplication")

_SYSTEM_PROMPT = """You classify how a memory candidate relates to one existing memory for Munin.
Return ONLY valid JSON matching this schema:
{
  "relationship": "NEW" | "DUPLICATE" | "REINFORCES",
  "confidence": 0.0-1.0,
  "explanation": "short optional string"
}

Definitions:
- NEW: candidate adds genuinely new durable information (even if related).
- DUPLICATE: candidate expresses essentially the same proposition as the existing memory.
- REINFORCES: candidate independently confirms the existing memory without adding meaningful new information.

Rules:
- Do NOT use surface similarity alone.
- Opposite polarity (prefers vs does not prefer) is NOT DUPLICATE — return NEW.
- Different memory types (e.g. project vs goal) usually require NEW unless propositions are identical.
- Do NOT classify CONTRADICTS / UPDATES / SUPERSEDES — those are out of scope; prefer NEW when unsure.
- Be conservative: when uncertain, prefer NEW with lower confidence.
"""


class OpenAICompatibleRelationshipProvider(RelationshipProvider):
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
            raise RelationshipError("DEDUP_BASE_URL is required for openai_compatible provider")
        if not model or not model.strip():
            raise RelationshipError("DEDUP_MODEL is required for openai_compatible provider")
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
    ) -> RelationshipAnalysis:
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
                "Relationship provider unavailable provider=%s model=%s",
                self.provider_name,
                self._model,
            )
            raise RelationshipError("Relationship provider unavailable") from exc

        try:
            message = data["choices"][0]["message"]["content"]
            parsed = json.loads(message) if isinstance(message, str) else message
            return RelationshipAnalysis.model_validate(parsed)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Relationship provider returned invalid structured output provider=%s model=%s",
                self.provider_name,
                self._model,
            )
            raise RelationshipError("Relationship provider returned invalid output") from exc
