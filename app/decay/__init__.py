"""M6 — Decay module: effective importance / relevance decay without mutation."""

from app.decay.profiles import DecayProfile, decay_lambda, profile_for_type
from app.decay.calculator import compute_decay_multiplier, compute_effective_importance

__all__ = [
    "DecayProfile",
    "decay_lambda",
    "profile_for_type",
    "compute_decay_multiplier",
    "compute_effective_importance",
]
