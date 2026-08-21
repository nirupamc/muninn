"""OpenAI-compatible consolidation provider.

Calls any OpenAI-style chat completions endpoint.
Works with local endpoints (Ollama, LM Studio, vLLM, etc.) and OpenAI itself.

Safety constraints embedded in the system prompt:
- Summarise ONLY the supplied memories.
- Do NOT add facts not present in the source memories.
- Preserve negation, uncertainty, entity names.
- Do NOT collapse contradictions into one truth.
- If contradictions are detected, output the literal string "REFUSE".
- Return JSON: {"content": "...", "memory_type": "...", "confidence": 0.0-1.0}
"""

from __future__ import annotations

import json
import logging

from app.consolidation.base import ConsolidationProvider
from app.consolidation.models import ConsolidationProposal
from app.consolidation.providers.deterministic import _derive_importance, _derive_type
from app.models.memory import Memory, MemoryType

logger = logging.getLogger("munin.consolidation")

_SYSTEM_PROMPT = """\
You are a memory consolidation assistant for Munin, a durable AI-agent memory system.

Your task: given a list of related durable memories, produce ONE concise consolidated memory.

STRICT RULES:
1. Only use facts explicitly stated in the provided memories.
2. Do NOT add any information, inferences, or assumptions.
3. Preserve negation (e.g. "do not build the frontend yet").
4. Preserve uncertainty (e.g. "might prefer", "considering").
5. Preserve all proper nouns and project/entity names exactly.
6. Do NOT collapse contradictions. If you detect contradictory facts, output the
   single word: REFUSE
7. Use the same language as the source memories.

Output format (JSON only, no markdown fences):
{"content": "<consolidated text>", "memory_type": "<type>", "confidence": <0.0-1.0>}

Valid memory_type values: fact, preference, project, goal, decision, event, relationship, procedure, other
"""

_VALID_TYPES = {t.value for t in MemoryType}


class OpenAICompatibleConsolidationProvider(ConsolidationProvider):
    """
    Consolidation via a local OpenAI-compatible chat endpoint.

    Set CONSOLIDATION_BASE_URL, CONSOLIDATION_MODEL, and optionally
    CONSOLIDATION_API_KEY in your environment.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._api_key = api_key
        self._timeout = timeout

    @property
    def provider_name(self) -> str:
        return "openai_compatible"

    @property
    def model_name(self) -> str:
        return self._model

    def consolidate(
        self,
        memories: list[Memory],
        *,
        namespace: str,
    ) -> ConsolidationProposal | None:
        if not memories:
            return None

        user_content = self._build_user_message(memories)
        try:
            raw = self._call_api(user_content)
        except Exception as exc:
            logger.error(
                "consolidation API call failed provider=%s model=%s error=%s",
                self.provider_name,
                self._model,
                exc,
            )
            return None

        if raw is None:
            return None

        # Parse response
        stripped = raw.strip()
        if stripped.upper() == "REFUSE":
            logger.info(
                "consolidation provider refused (contradiction detected) namespace=%s",
                namespace,
            )
            return None

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            logger.error("consolidation provider returned non-JSON: %r", stripped[:200])
            return None

        content = str(data.get("content", "")).strip()
        if not content:
            return None

        raw_type = str(data.get("memory_type", "fact")).strip().lower()
        if raw_type not in _VALID_TYPES:
            raw_type = "fact"
        memory_type = MemoryType(raw_type)

        confidence = float(data.get("confidence", 0.75))
        confidence = max(0.0, min(1.0, confidence))

        return ConsolidationProposal(
            content=content,
            memory_type=memory_type,
            importance=_derive_importance(memories),
            confidence=confidence,
            source_memory_ids=[m.id for m in memories],
            reason=f"OpenAI-compatible consolidation of {len(memories)} memories via {self._model}.",
            provider=self.provider_name,
            provider_model=self._model,
        )

    def _build_user_message(self, memories: list[Memory]) -> str:
        lines = ["Source memories to consolidate:"]
        for i, m in enumerate(memories, 1):
            lines.append(f"{i}. [{m.memory_type.value}] {m.content}")
        lines.append(
            "\nProduce a single consolidated memory following the system prompt rules."
        )
        return "\n".join(lines)

    def _call_api(self, user_content: str) -> str | None:
        import urllib.request

        url = f"{self._base_url}/chat/completions"
        headers = {
            "Content-Type": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        body = json.dumps(
            {
                "model": self._model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_content},
                ],
                "temperature": 0.1,
                "max_tokens": 300,
            }
        ).encode("utf-8")

        req = urllib.request.Request(url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))

        choices = data.get("choices", [])
        if not choices:
            return None
        return choices[0].get("message", {}).get("content")
