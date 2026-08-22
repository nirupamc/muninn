"""Deterministic relationship provider for tests and offline defaults.

Uses conservative lexical rules — not production semantic equivalence.
Exact fixture strings are not required by DeduplicationService itself.
"""

from __future__ import annotations

import re

from app.deduplication.base import RelationshipProvider
from app.deduplication.models import RelationshipAnalysis, RelationshipType
from app.deduplication.normalize import normalize_for_exact_match
from app.deduplication.state_change import contains_state_change_signal
from app.models.memory import MemoryType

_NEGATION = re.compile(
    r"(?i)\b(?:do\s+not|don't|does\s+not|doesn't|no\s+longer|"
    r"not\s+anymore|never)\b"
)

_REINFORCE_CUES = re.compile(
    r"(?i)\b(?:still|remains?|continue(?:s|d)?|as\s+always|"
    r"default|same)\b"
)

# Synonym clusters collapsed for rough proposition matching.
_SYNONYM_GROUPS: list[set[str]] = [
    {"building", "working", "developing", "creating", "making"},
    {"prefer", "prefers", "preferred", "preference", "favorite", "default"},
    {"project", "work"},
    {"backend", "server"},
    {"python", "py"},
    {"parser", "parsing", "parse"},
    {"document", "documents", "pdf"},
    {"uses", "use", "using"},
    {"store", "database", "db"},
]

_STOP = {
    "a",
    "an",
    "the",
    "is",
    "are",
    "was",
    "were",
    "to",
    "of",
    "for",
    "on",
    "in",
    "and",
    "or",
    "user",
    "i",
    "im",
    "my",
    "am",
    "be",
    "been",
    "being",
    "that",
    "this",
    "with",
    "from",
    "as",
    "at",
    "by",
    "it",
    "its",
    "currently",
    "now",
}


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.casefold()))


def _canonical_token(token: str) -> str:
    for group in _SYNONYM_GROUPS:
        if token in group:
            return sorted(group)[0]
    return token


def _core_tokens(text: str) -> set[str]:
    return {_canonical_token(t) for t in _tokens(text) if t not in _STOP}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


class DeterministicRelationshipProvider(RelationshipProvider):
    """
    Rule-based classifier for reproducible offline tests.

    Conservative: when signals conflict or are weak, returns NEW.
    """

    def __init__(self, model_name: str = "deterministic-relationship-v1") -> None:
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
    ) -> RelationshipAnalysis:
        cand_n = normalize_for_exact_match(candidate)
        exist_n = normalize_for_exact_match(existing_memory)

        if cand_n == exist_n:
            return RelationshipAnalysis(
                relationship=RelationshipType.DUPLICATE,
                confidence=1.0,
                explanation="Normalized text identical",
            )

        if contains_state_change_signal(candidate):
            return RelationshipAnalysis(
                relationship=RelationshipType.NEW,
                confidence=0.95,
                explanation=(
                    "Explicit state-change language; deferred to temporal analysis (M4)"
                ),
                defer_temporal=True,
            )

        cand_neg = bool(_NEGATION.search(candidate))
        exist_neg = bool(_NEGATION.search(existing_memory))
        if cand_neg != exist_neg:
            return RelationshipAnalysis(
                relationship=RelationshipType.NEW,
                confidence=0.95,
                explanation="Opposite polarity; preserving as NEW (contradiction deferred to M4)",
            )

        cand_core = _core_tokens(candidate)
        exist_core = _core_tokens(existing_memory)
        core_overlap = _jaccard(cand_core, exist_core)
        shared = cand_core & exist_core
        novel = cand_core - exist_core
        reinforce = bool(_REINFORCE_CUES.search(candidate))

        # Type mismatch: usually NEW unless nearly identical proposition.
        if candidate_type != existing_type and core_overlap < 0.9:
            return RelationshipAnalysis(
                relationship=RelationshipType.NEW,
                confidence=0.9,
                explanation="Different memory types; preserving distinct propositions",
            )

        # Shared proper-ish entities (capitalized-like tokens longer than 3) + action synonym
        # → paraphrase duplicate (e.g. building RagParser vs working on RagParser).
        if len(shared) >= 1 and core_overlap >= 0.4:
            # New technical fact attached to shared entity → NEW
            # e.g. "Munin uses FastAPI" vs "User is building Munin"
            fact_markers = {"uses", "use", "using", "requires", "need", "needs", "with"}
            cand_raw = _tokens(candidate)
            if novel and (cand_raw & fact_markers) and not reinforce:
                return RelationshipAnalysis(
                    relationship=RelationshipType.NEW,
                    confidence=0.88,
                    explanation="Related entity but new proposition",
                )

            if reinforce:
                return RelationshipAnalysis(
                    relationship=RelationshipType.REINFORCES,
                    confidence=0.92,
                    explanation="Confirms existing memory without new durable facts",
                )

            # Substantial novel content beyond shared entity → NEW
            if len(novel) >= 2 and len(shared) == 1 and core_overlap < 0.5:
                return RelationshipAnalysis(
                    relationship=RelationshipType.NEW,
                    confidence=0.85,
                    explanation="Shared entity only; distinct proposition",
                )

            return RelationshipAnalysis(
                relationship=RelationshipType.DUPLICATE,
                confidence=min(0.99, 0.75 + core_overlap * 0.25),
                explanation="High proposition overlap; treated as paraphrase duplicate",
            )

        if reinforce and len(shared) >= 1:
            return RelationshipAnalysis(
                relationship=RelationshipType.REINFORCES,
                confidence=0.85,
                explanation="Reinforcement language with shared core entities",
            )

        return RelationshipAnalysis(
            relationship=RelationshipType.NEW,
            confidence=0.8,
            explanation="Insufficient evidence of equivalence",
        )
