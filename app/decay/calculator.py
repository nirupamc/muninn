"""Decay calculations: multiplier and effective importance.

Design principles
-----------------
* Stored ``importance`` is NEVER mutated.
* All calculations are pure functions of (memory_type, created_at, as_of).
* ``as_of`` defaults to current UTC time but accepts a fixed historical value
  so that historical context requests produce deterministic results.
* Reinforcement provides a small bounded boost (same cap as M5 reinforcement).
* Effective importance is clamped to [0, 1].
"""

from __future__ import annotations

import math
from datetime import UTC, datetime

from app.decay.profiles import DecayProfile, decay_lambda, profile_for_type
from app.models.memory import MemoryType


def _to_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def compute_decay_multiplier(
    *,
    memory_type: MemoryType,
    created_at: datetime,
    as_of: datetime,
    settings=None,
) -> float:
    """
    Return a decay multiplier in [0, 1].

    multiplier = exp(-lambda * age_days)

    For DecayProfile.NONE the multiplier is always 1.0.
    For very new memories (age ≈ 0) the multiplier is ≈ 1.0.
    """
    profile = profile_for_type(memory_type)
    lam = decay_lambda(profile, settings)

    if lam == 0.0:
        return 1.0

    age_seconds = max(0.0, (_to_utc(as_of) - _to_utc(created_at)).total_seconds())
    age_days = age_seconds / 86_400.0
    return math.exp(-lam * age_days)


def compute_reinforcement_modifier(reinforcement_count: int) -> float:
    """
    Small bounded modifier from M3 reinforcement provenance.

    Range: 1.0 (no reinforcement) to at most 1.1 (heavily reinforced).
    Keeps effective importance from exceeding 1.0 after clamping.
    """
    if reinforcement_count <= 0:
        return 1.0
    # log1p keeps the boost sub-linear; cap total modifier at 1.1
    return min(1.1, 1.0 + 0.05 * math.log1p(reinforcement_count))


def compute_effective_importance(
    *,
    stored_importance: float,
    memory_type: MemoryType,
    created_at: datetime,
    as_of: datetime,
    reinforcement_count: int = 0,
    settings=None,
) -> float:
    """
    Compute effective importance for ranking — does NOT mutate stored importance.

    Formula:
        effective = clamp(stored_importance * decay_multiplier * reinforcement_modifier, 0, 1)

    The reinforcement modifier adds at most +10%, so a fully-reinforced memory
    cannot dominate purely on repetition.
    """
    multiplier = compute_decay_multiplier(
        memory_type=memory_type,
        created_at=created_at,
        as_of=as_of,
        settings=settings,
    )
    reinforcement_mod = compute_reinforcement_modifier(reinforcement_count)
    raw = stored_importance * multiplier * reinforcement_mod
    return max(0.0, min(1.0, raw))
