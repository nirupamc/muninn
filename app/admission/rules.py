"""Munin admission policy — final STORE/IGNORE decisions."""

from __future__ import annotations

from dataclasses import dataclass

from app.admission.models import (
    AdmissionCandidate,
    CandidateAnalysis,
    ReasonCode,
)
from app.admission.privacy import contains_secret_like_data
from app.admission.scoring import AdmissionWeights, DEFAULT_WEIGHTS, compute_admission_score


@dataclass(frozen=True)
class PolicyDecision:
    decision: str  # STORE | IGNORE
    candidate: AdmissionCandidate
    admission_score: float
    reason_codes: list[ReasonCode]
    explanation: str | None
    redacted: bool = False


@dataclass(frozen=True)
class AdmissionPolicyConfig:
    store_threshold: float = 0.65
    min_confidence: float = 0.60
    weights: AdmissionWeights = DEFAULT_WEIGHTS


def apply_admission_policy(
    analysis: CandidateAnalysis,
    *,
    source_event_content: str,
    config: AdmissionPolicyConfig,
) -> PolicyDecision:
    """
    Apply Munin policy on top of provider dimensions.

    Privacy overrides win. Confidence minimum and score threshold apply next.
    """
    candidate = analysis.candidate
    score = compute_admission_score(candidate, config.weights)
    reasons = list(analysis.reason_codes)

    # Privacy: event or candidate must not amplify secrets into durable memory.
    event_privacy = contains_secret_like_data(source_event_content)
    candidate_privacy = contains_secret_like_data(candidate.content)
    if event_privacy.is_sensitive or candidate_privacy.is_sensitive:
        if ReasonCode.SECRET_LIKE_DATA not in reasons:
            reasons.append(ReasonCode.SECRET_LIKE_DATA)
        return PolicyDecision(
            decision="IGNORE",
            candidate=candidate,
            admission_score=score,
            reason_codes=_unique(reasons),
            explanation="Secret-like content blocked by privacy filter",
            redacted=True,
        )

    if candidate.confidence < config.min_confidence:
        if ReasonCode.TOO_UNCERTAIN not in reasons:
            reasons.append(ReasonCode.TOO_UNCERTAIN)
        return PolicyDecision(
            decision="IGNORE",
            candidate=candidate,
            admission_score=score,
            reason_codes=_unique(reasons),
            explanation="Confidence below minimum",
            redacted=False,
        )

    # Explicit remember requests with solid confidence get a mild boost path:
    # still require score threshold unless explicitness is very high and score close.
    if score >= config.store_threshold:
        if ReasonCode.HIGH_FUTURE_UTILITY not in reasons and candidate.future_utility >= 0.75:
            reasons.append(ReasonCode.HIGH_FUTURE_UTILITY)
        return PolicyDecision(
            decision="STORE",
            candidate=candidate,
            admission_score=score,
            reason_codes=_unique(reasons),
            explanation=analysis.explanation,
            redacted=False,
        )

    if ReasonCode.BELOW_THRESHOLD not in reasons:
        reasons.append(ReasonCode.BELOW_THRESHOLD)
    if analysis.provider_recommendation == "IGNORE":
        if ReasonCode.PROVIDER_RECOMMEND_IGNORE not in reasons:
            reasons.append(ReasonCode.PROVIDER_RECOMMEND_IGNORE)

    return PolicyDecision(
        decision="IGNORE",
        candidate=candidate,
        admission_score=score,
        reason_codes=_unique(reasons),
        explanation=analysis.explanation or "Admission score below store threshold",
        redacted=False,
    )


def _unique(codes: list[ReasonCode]) -> list[ReasonCode]:
    seen: set[ReasonCode] = set()
    ordered: list[ReasonCode] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return ordered
