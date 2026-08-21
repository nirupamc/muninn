"""Decay profile definitions and memory-type mapping.

Decay profiles control how quickly a memory's effective importance
diminishes with age. They do NOT affect stored importance values.

All lambda values are experimental and configurable via Settings.
"""

from __future__ import annotations

from enum import Enum

from app.models.memory import MemoryType


class DecayProfile(str, Enum):
    """How quickly a memory type ages out of effective relevance."""

    NONE = "none"          # Importance never decays (e.g. pinned system memories)
    SLOW = "slow"          # Long-lived knowledge: projects, goals, preferences
    NORMAL = "normal"      # Medium-lived: decisions, procedures, facts
    FAST = "fast"          # Short-lived: events
    EPHEMERAL = "ephemeral"  # Very transient content (e.g. debugging sessions)


# Default profile per memory type.
# Derived at query time — no DB column needed.
_TYPE_PROFILE: dict[MemoryType, DecayProfile] = {
    MemoryType.project:      DecayProfile.SLOW,
    MemoryType.goal:         DecayProfile.SLOW,
    MemoryType.preference:   DecayProfile.SLOW,
    MemoryType.relationship: DecayProfile.SLOW,
    MemoryType.decision:     DecayProfile.NORMAL,
    MemoryType.procedure:    DecayProfile.NORMAL,
    MemoryType.fact:         DecayProfile.NORMAL,
    MemoryType.other:        DecayProfile.NORMAL,
    MemoryType.event:        DecayProfile.FAST,
}


def profile_for_type(memory_type: MemoryType) -> DecayProfile:
    """Return the default decay profile for a memory type."""
    return _TYPE_PROFILE.get(memory_type, DecayProfile.NORMAL)


def decay_lambda(profile: DecayProfile, settings=None) -> float:
    """
    Return the exponential decay rate (λ) for the given profile.

    Uses Settings values when provided so all lambdas come from one
    configurable source.  Falls back to hardcoded defaults when called
    outside the application context (e.g. tests, evaluation scripts).
    """
    if settings is None:
        # Hardcoded defaults — match .env.example
        _defaults: dict[DecayProfile, float] = {
            DecayProfile.NONE:      0.0,
            DecayProfile.SLOW:      0.002,
            DecayProfile.NORMAL:    0.01,
            DecayProfile.FAST:      0.05,
            DecayProfile.EPHEMERAL: 0.20,
        }
        return _defaults[profile]

    mapping: dict[DecayProfile, float] = {
        DecayProfile.NONE:      settings.decay_lambda_none,
        DecayProfile.SLOW:      settings.decay_lambda_slow,
        DecayProfile.NORMAL:    settings.decay_lambda_normal,
        DecayProfile.FAST:      settings.decay_lambda_fast,
        DecayProfile.EPHEMERAL: settings.decay_lambda_ephemeral,
    }
    return mapping[profile]
