"""Deterministic consolidation provider for tests and development.

Produces a consolidated memory by joining source content with a
hand-crafted template. Does NOT call any external service.

Contradiction detection: if two sources share the same subject prefix
but differ in content (detected by temporal/dedup audit data available
to the caller, or by simple heuristics here), refuse consolidation.

Heuristics used:
  - If any two memories have identical first-word subjects AND contradictory
    signals (one contains "not", "prefer X" vs "prefer Y"), return None.
  - Otherwise concatenate into a compound sentence.

This provider is intentionally simple so tests remain offline and fast.
"""

from __future__ import annotations

import re

from app.consolidation.base import ConsolidationProvider
from app.consolidation.models import ConsolidationProposal
from app.models.memory import Memory, MemoryType


_CONTRADICTION_PAIRS = [
    ("prefer", "not prefer"),
    ("use", "not use"),
    ("uses", "not uses"),
    ("is", "is not"),
]


def _detect_contradiction(memories: list[Memory]) -> bool:
    """
    Conservative contradiction heuristic.

    Returns True if any two memories look like they directly contradict.
    Errs on the side of refusing consolidation rather than merging conflicts.
    """
    contents = [m.content.strip().lower() for m in memories]
    for i, a in enumerate(contents):
        for j, b in enumerate(contents):
            if i >= j:
                continue
            # Heuristic: same leading subject, opposite predicate
            words_a = re.findall(r"\w+", a)
            words_b = re.findall(r"\w+", b)
            if not words_a or not words_b:
                continue
            # Same subject word
            if words_a[0] != words_b[0]:
                continue
            # One contains "not" near the same verb as the other (simple check)
            for pos, neg in _CONTRADICTION_PAIRS:
                if pos in a and neg in b:
                    return True
                if pos in b and neg in a:
                    return True
            # Direct preference conflict: "prefers X" vs "prefers Y"
            pref_a = re.search(r"prefers?\s+(\w+)", a)
            pref_b = re.search(r"prefers?\s+(\w+)", b)
            if pref_a and pref_b and pref_a.group(1) != pref_b.group(1):
                return True
    return False


def _derive_type(memories: list[Memory]) -> MemoryType:
    """Pick the most common / highest-priority type from the group."""
    _priority = [
        MemoryType.project,
        MemoryType.goal,
        MemoryType.decision,
        MemoryType.procedure,
        MemoryType.fact,
        MemoryType.preference,
        MemoryType.relationship,
        MemoryType.event,
        MemoryType.other,
    ]
    counts = {t: 0 for t in MemoryType}
    for m in memories:
        counts[m.memory_type] += 1
    # Pick most common, break ties by priority order
    best = max(
        memories,
        key=lambda m: (counts[m.memory_type], -_priority.index(m.memory_type)),
    )
    return best.memory_type


def _derive_importance(memories: list[Memory]) -> float:
    """Average importance, clipped to [0, 1]."""
    if not memories:
        return 0.5
    return max(0.0, min(1.0, sum(m.importance for m in memories) / len(memories)))


class DeterministicConsolidationProvider(ConsolidationProvider):
    """
    Offline, rule-based consolidation provider.

    Used for tests and development — produces predictable output.
    """

    @property
    def provider_name(self) -> str:
        return "deterministic"

    @property
    def model_name(self) -> str:
        return "deterministic-v1"

    def consolidate(
        self,
        memories: list[Memory],
        *,
        namespace: str,
    ) -> ConsolidationProposal | None:
        if not memories:
            return None

        if _detect_contradiction(memories):
            return None

        # Build consolidated content by extracting key phrases from each memory
        phrases = self._extract_phrases(memories)
        if not phrases:
            return None

        # Use the first memory's subject as the anchor sentence
        anchor = memories[0].content.rstrip(". \t")
        if len(phrases) == 1:
            content = f"{anchor}."
        else:
            feature_list = ", ".join(phrases[1:])
            content = f"{anchor}, including {feature_list}."

        return ConsolidationProposal(
            content=content,
            memory_type=_derive_type(memories),
            importance=_derive_importance(memories),
            confidence=0.85,
            source_memory_ids=[m.id for m in memories],
            reason=f"Deterministic consolidation of {len(memories)} related memories.",
            provider=self.provider_name,
            provider_model=self.model_name,
        )

    def _extract_phrases(self, memories: list[Memory]) -> list[str]:
        """
        Extract the most informative phrase from each memory content.

        Strips common sentence starters to get to the key subject/object.
        """
        phrases: list[str] = []
        seen = set()
        for m in memories:
            text = m.content.strip().rstrip(".")
            # Remove leading "User is", "User has", "Munin uses", etc.
            trimmed = re.sub(
                r"^(user (is|has|was|can|will|should)|munin (is|uses|has|supports|provides))\s+",
                "",
                text,
                flags=re.IGNORECASE,
            ).strip()
            if trimmed and trimmed.lower() not in seen:
                seen.add(trimmed.lower())
                phrases.append(trimmed)
        return phrases
