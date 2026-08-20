"""OpenAI-compatible chat-completions admission provider (local-first)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.admission.base import AdmissionError, AdmissionProvider
from app.admission.models import AdmissionAnalysis

logger = logging.getLogger("munin.admission")

_SYSTEM_PROMPT = """You extract durable memory candidates from a single chat event for Munin.
Return ONLY valid JSON matching this schema:
{
  "candidates": [
    {
      "candidate": {
        "content": "concise standalone statement",
        "memory_type": "fact|preference|project|goal|decision|event|relationship|procedure|other",
        "importance": 0.0-1.0,
        "confidence": 0.0-1.0,
        "future_utility": 0.0-1.0,
        "stability": 0.0-1.0,
        "specificity": 0.0-1.0,
        "explicitness": 0.0-1.0,
        "triviality": 0.0-1.0
      },
      "provider_recommendation": "STORE" | "IGNORE",
      "reason_codes": ["ONGOING_PROJECT", ...],
      "explanation": "short optional string"
    }
  ]
}

Rules:
- Extract only explicit or strongly supported durable information.
- Avoid unsupported inference (do not invent preferences or emotions).
- Prefer concise standalone memories; split unrelated facts into separate candidates.
- Assign memory_type from the allowed enum only.
- Score dimensions honestly; ephemeral/trivial chatter should score high triviality and low future_utility.
- Do not perform deduplication or contradiction resolution.
- If nothing is durable, return {"candidates": []}.
"""


class OpenAICompatibleAdmissionProvider(AdmissionProvider):
    """Calls an OpenAI-compatible /chat/completions endpoint (llama.cpp, LM Studio, etc.)."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
    ) -> None:
        if not base_url or not base_url.strip():
            raise AdmissionError("ADMISSION_BASE_URL is required for openai_compatible provider")
        if not model or not model.strip():
            raise AdmissionError("ADMISSION_MODEL is required for openai_compatible provider")
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

    def analyze_event(
        self,
        *,
        role: str,
        content: str,
        context: dict[str, Any] | None = None,
    ) -> AdmissionAnalysis:
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
                            "role": role,
                            "content": content,
                            "context": context or {},
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
                "Admission provider unavailable provider=%s model=%s",
                self.provider_name,
                self._model,
            )
            raise AdmissionError("Admission provider unavailable") from exc

        try:
            message = data["choices"][0]["message"]["content"]
            parsed = json.loads(message) if isinstance(message, str) else message
            return AdmissionAnalysis.model_validate(parsed)
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "Admission provider returned invalid structured output provider=%s model=%s",
                self.provider_name,
                self._model,
            )
            raise AdmissionError("Admission provider returned invalid output") from exc
