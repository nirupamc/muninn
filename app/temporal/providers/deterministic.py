"""Deterministic temporal relationship provider for tests and offline defaults."""

from __future__ import annotations

import re
from datetime import datetime

from app.models.memory import MemoryType
from app.temporal.base import TemporalRelationshipProvider
from app.temporal.models import TemporalRelationshipAnalysis, TemporalRelationshipType

_NEGATION = re.compile(
    r"(?i)\b(?:do\s+not|don't|does\s+not|doesn't|no\s+longer|not\s+anymore|never)\b"
)
_NO_LONGER = re.compile(r"(?i)\bno\s+longer\b|\bstopped\s+using\b")
_NOW = re.compile(r"(?i)\b(?:now|currently)\b")
_STILL = re.compile(r"(?i)\bstill\b|\bremains?\b")
_USED_TO = re.compile(r"(?i)\bused\s+to\b")
_SWITCHED = re.compile(
    r"(?i)\b(?:switched|migrated|moved\s+from|replaced)\b"
)
_PREFER = re.compile(r"(?i)\bprefer")
_USE = re.compile(r"(?i)\buse[sd]?\b")

_STOP = {
    "a", "an", "the", "is", "are", "was", "were", "to", "of", "for", "on", "in",
    "and", "or", "user", "i", "im", "my", "am", "be", "with", "from", "as", "at",
    "by", "it", "its", "that", "this",
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _core(text: str) -> set[str]:
    return {t for t in _tokens(text) if t not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class DeterministicTemporalProvider(TemporalRelationshipProvider):
    """
    Phrase-aware temporal classifier for reproducible offline tests.

    Conservative: when signals conflict or are weak, returns NEW.
    """

    def __init__(self, model_name: str = "deterministic-temporal-v1") -> None:
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return "deterministic"

    @property
    def model_name(self) -> str:
        return self._model_name

    def classify(
        self,
        *,
        candidate: str,
        existing_memory: str,
        candidate_type: MemoryType,
        existing_type: MemoryType,
        candidate_event_time: datetime | None = None,  # noqa: ARG002
        existing_valid_from: datetime | None = None,  # noqa: ARG002
        existing_valid_until: datetime | None = None,  # noqa: ARG002
    ) -> TemporalRelationshipAnalysis:
        cand_core = _core(candidate)
        exist_core = _core(existing_memory)
        shared = cand_core & exist_core
        overlap = _jaccard(cand_core, exist_core)

        cand_neg = bool(_NEGATION.search(candidate) or _NO_LONGER.search(candidate))
        exist_neg = bool(_NEGATION.search(existing_memory) or _NO_LONGER.search(existing_memory))
        has_now = bool(_NOW.search(candidate))
        has_switch = bool(_SWITCHED.search(candidate))
        has_used_to = bool(_USED_TO.search(candidate))
        has_still = bool(_STILL.search(candidate))

        # Still / remains → not a temporal change (M3 should have caught reinforcement).
        if has_still and not cand_neg and overlap >= 0.35:
            return TemporalRelationshipAnalysis(
                relationship=TemporalRelationshipType.NEW,
                confidence=0.7,
                explanation="Still/remains language without replacement intent",
            )

        # Explicit switch / migration → SUPERSEDES
        if has_switch and (len(shared) >= 1 or overlap >= 0.2):
            return TemporalRelationshipAnalysis(
                relationship=TemporalRelationshipType.SUPERSEDES,
                confidence=0.95,
                explanation="Explicit switched/migrated replacement",
                replacement_scope="tool_or_stack",
            )

        # No longer uses X vs uses X → SUPERSEDES
        if _NO_LONGER.search(candidate) and _USE.search(existing_memory):
            if len(shared) >= 1 or overlap >= 0.25:
                return TemporalRelationshipAnalysis(
                    relationship=TemporalRelationshipType.SUPERSEDES,
                    confidence=0.94,
                    explanation="Explicit no-longer discontinuation",
                    replacement_scope="usage",
                )

        # Negated preference vs positive preference (same object) → SUPERSEDES
        if _PREFER.search(candidate) and _PREFER.search(existing_memory):
            prefer_objects_overlap = self._preference_object_overlap(candidate, existing_memory)
            if cand_neg and not exist_neg and prefer_objects_overlap:
                return TemporalRelationshipAnalysis(
                    relationship=TemporalRelationshipType.SUPERSEDES,
                    confidence=0.93,
                    explanation="Explicit negated preference replaces prior preference",
                    replacement_scope="preference",
                )

            # "now prefers Y" vs "prefers X" → SUPERSEDES when same preference domain
            if has_now and not cand_neg and candidate_type == existing_type == MemoryType.preference:
                if prefer_objects_overlap:
                    # same object with "now" → soft update/reinforce-like; treat as UPDATES
                    return TemporalRelationshipAnalysis(
                        relationship=TemporalRelationshipType.UPDATES,
                        confidence=0.85,
                        explanation="Temporal preference restatement with same object",
                    )
                # different preference object → SUPERSEDES (explicit now)
                return TemporalRelationshipAnalysis(
                    relationship=TemporalRelationshipType.SUPERSEDES,
                    confidence=0.9,
                    explanation="Explicit now-preference replaces prior preference",
                    replacement_scope="preference",
                )

            # Conflicting preferences without temporal language → CONTRADICTS
            if (
                not cand_neg
                and not exist_neg
                and not has_now
                and not has_used_to
                and candidate_type == existing_type == MemoryType.preference
                and not prefer_objects_overlap
                and overlap < 0.85
            ):
                # Both are preference statements about different things in same domain
                if self._both_look_like_preferences(candidate, existing_memory):
                    return TemporalRelationshipAnalysis(
                        relationship=TemporalRelationshipType.CONTRADICTS,
                        confidence=0.88,
                        explanation="Conflicting preferences without explicit replacement",
                    )

        # Uses X vs uses Y / uses PostgreSQL vs uses SQLite with switch already handled
        if _USE.search(candidate) and _USE.search(existing_memory) and has_now:
            if len(shared) >= 1 and not self._same_usage_object(candidate, existing_memory):
                return TemporalRelationshipAnalysis(
                    relationship=TemporalRelationshipType.UPDATES,
                    confidence=0.86,
                    explanation="Usage detail update with temporal cue",
                )

        # Related entity but new proposition (Munin uses FastAPI vs building Munin)
        if len(shared) >= 1 and overlap < 0.55:
            novel = cand_core - exist_core
            if novel and not cand_neg and not has_switch and not has_now:
                return TemporalRelationshipAnalysis(
                    relationship=TemporalRelationshipType.NEW,
                    confidence=0.88,
                    explanation="Related entity but new proposition",
                )

        # Type mismatch → usually NEW
        if candidate_type != existing_type and overlap < 0.7:
            return TemporalRelationshipAnalysis(
                relationship=TemporalRelationshipType.NEW,
                confidence=0.85,
                explanation="Different memory types; treating as NEW",
            )

        if overlap < 0.25:
            return TemporalRelationshipAnalysis(
                relationship=TemporalRelationshipType.NEW,
                confidence=0.9,
                explanation="Insufficient topical overlap",
            )

        return TemporalRelationshipAnalysis(
            relationship=TemporalRelationshipType.NEW,
            confidence=0.75,
            explanation="No confident temporal transition",
        )

    @staticmethod
    def _preference_object_overlap(a: str, b: str) -> bool:
        """True when preference objects (tokens after prefer*) meaningfully overlap."""
        def objs(text: str) -> set[str]:
            m = re.search(r"(?i)prefer(?:s|red)?\s+(.+)$", text)
            if not m:
                return _core(text)
            return _core(m.group(1))

        oa, ob = objs(a), objs(b)
        if not oa or not ob:
            return False
        return len(oa & ob) >= 1

    @staticmethod
    def _both_look_like_preferences(a: str, b: str) -> bool:
        return bool(_PREFER.search(a) and _PREFER.search(b))

    @staticmethod
    def _same_usage_object(a: str, b: str) -> bool:
        def objs(text: str) -> set[str]:
            m = re.search(r"(?i)use[sd]?\s+(.+)$", text)
            if not m:
                return _core(text)
            return _core(m.group(1))

        return len(objs(a) & objs(b)) >= 1
