"""Conservative deduplication policy.

Philosophy: when uncertain, preserve information (default NEW).
False merges destroy distinct facts; redundant memories are recoverable.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.deduplication.models import DedupReasonCode, RelationshipAnalysis, RelationshipType


@dataclass(frozen=True)
class DedupPolicyConfig:
    """Thresholds for accepting DUPLICATE / REINFORCES decisions."""

    min_relationship_confidence: float = 0.70
    candidate_limit: int = 5
    min_similarity: float = 0.55


@dataclass(frozen=True)
class PolicyOutcome:
    relationship: RelationshipType
    confidence: float
    reason_codes: list[DedupReasonCode]
    explanation: str | None = None


def apply_relationship_policy(
    analysis: RelationshipAnalysis | None,
    *,
    config: DedupPolicyConfig,
    provider_error: bool = False,
) -> PolicyOutcome:
    """
    Map provider output to an actionable relationship.

    Low confidence / invalid / unavailable → NEW (preserve information).
    """
    if provider_error or analysis is None:
        return PolicyOutcome(
            relationship=RelationshipType.NEW,
            confidence=0.0,
            reason_codes=[DedupReasonCode.PROVIDER_UNAVAILABLE],
            explanation="Relationship provider unavailable; preserving candidate as NEW",
        )

    if analysis.relationship == RelationshipType.NEW:
        return PolicyOutcome(
            relationship=RelationshipType.NEW,
            confidence=analysis.confidence,
            reason_codes=[DedupReasonCode.RELATED_BUT_NEW],
            explanation=analysis.explanation,
        )

    if analysis.confidence < config.min_relationship_confidence:
        return PolicyOutcome(
            relationship=RelationshipType.NEW,
            confidence=analysis.confidence,
            reason_codes=[DedupReasonCode.LOW_CONFIDENCE, DedupReasonCode.RELATIONSHIP_UNCERTAIN],
            explanation=(
                analysis.explanation
                or "Relationship confidence below threshold; preserving as NEW"
            ),
        )

    if analysis.relationship == RelationshipType.DUPLICATE:
        return PolicyOutcome(
            relationship=RelationshipType.DUPLICATE,
            confidence=analysis.confidence,
            reason_codes=[DedupReasonCode.SEMANTIC_DUPLICATE],
            explanation=analysis.explanation,
        )

    return PolicyOutcome(
        relationship=RelationshipType.REINFORCES,
        confidence=analysis.confidence,
        reason_codes=[DedupReasonCode.REINFORCEMENT],
        explanation=analysis.explanation,
    )
