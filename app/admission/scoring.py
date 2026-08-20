"""Centralized admission scoring weights and formula."""

from __future__ import annotations

from dataclasses import dataclass

from app.admission.models import AdmissionCandidate


@dataclass(frozen=True)
class AdmissionWeights:
    """Weights for the experimental admission heuristic."""

    future_utility: float = 0.30
    stability: float = 0.15
    specificity: float = 0.15
    explicitness: float = 0.15
    importance: float = 0.20
    triviality: float = 0.25


DEFAULT_WEIGHTS = AdmissionWeights()


def clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def compute_admission_score(
    candidate: AdmissionCandidate,
    weights: AdmissionWeights = DEFAULT_WEIGHTS,
) -> float:
    """
    Compute admission_score separately from importance.

    Experimental heuristic — not a scientifically optimal threshold.
    """
    raw = (
        candidate.future_utility * weights.future_utility
        + candidate.stability * weights.stability
        + candidate.specificity * weights.specificity
        + candidate.explicitness * weights.explicitness
        + candidate.importance * weights.importance
        - candidate.triviality * weights.triviality
    )
    return clamp01(raw)
