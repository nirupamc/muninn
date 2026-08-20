"""Conservative temporal policy.

Philosophy: when uncertain, preserve information (default NEW).
False supersedes destroy current truth — worse than redundant memories.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.temporal.models import (
    TemporalReasonCode,
    TemporalRelationshipAnalysis,
    TemporalRelationshipType,
)


@dataclass(frozen=True)
class TemporalPolicyConfig:
    """Thresholds for accepting UPDATES / CONTRADICTS / SUPERSEDES."""

    min_relationship_confidence: float = 0.75
    candidate_limit: int = 5
    min_similarity: float = 0.50


@dataclass(frozen=True)
class TemporalPolicyOutcome:
    relationship: TemporalRelationshipType
    confidence: float
    reason_codes: list[TemporalReasonCode]
    explanation: str | None = None
    replacement_scope: str | None = None


def apply_temporal_policy(
    analysis: TemporalRelationshipAnalysis | None,
    *,
    config: TemporalPolicyConfig,
    provider_error: bool = False,
) -> TemporalPolicyOutcome:
    """
    Map provider output to an actionable temporal relationship.

    Low confidence / invalid / unavailable → NEW (do not supersede).
    """
    if provider_error or analysis is None:
        return TemporalPolicyOutcome(
            relationship=TemporalRelationshipType.NEW,
            confidence=0.0,
            reason_codes=[TemporalReasonCode.PROVIDER_UNAVAILABLE],
            explanation="Temporal provider unavailable; preserving candidate as NEW",
        )

    if analysis.relationship == TemporalRelationshipType.NEW:
        return TemporalPolicyOutcome(
            relationship=TemporalRelationshipType.NEW,
            confidence=analysis.confidence,
            reason_codes=[TemporalReasonCode.RELATED_BUT_NEW],
            explanation=analysis.explanation,
            replacement_scope=analysis.replacement_scope,
        )

    if analysis.confidence < config.min_relationship_confidence:
        return TemporalPolicyOutcome(
            relationship=TemporalRelationshipType.NEW,
            confidence=analysis.confidence,
            reason_codes=[
                TemporalReasonCode.LOW_CONFIDENCE,
                TemporalReasonCode.RELATIONSHIP_UNCERTAIN,
            ],
            explanation=(
                analysis.explanation
                or "Temporal confidence below threshold; preserving as NEW"
            ),
            replacement_scope=analysis.replacement_scope,
        )

    reason_map = {
        TemporalRelationshipType.SUPERSEDES: TemporalReasonCode.EXPLICIT_REPLACEMENT,
        TemporalRelationshipType.UPDATES: TemporalReasonCode.DETAIL_UPDATE,
        TemporalRelationshipType.CONTRADICTS: TemporalReasonCode.UNRESOLVED_CONFLICT,
    }
    return TemporalPolicyOutcome(
        relationship=analysis.relationship,
        confidence=analysis.confidence,
        reason_codes=[reason_map[analysis.relationship]],
        explanation=analysis.explanation,
        replacement_scope=analysis.replacement_scope,
    )
