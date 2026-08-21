"""Deterministic local token estimator."""

from __future__ import annotations

import math

from app.context.tokenization.base import TokenEstimator


class SimpleTokenEstimator(TokenEstimator):
    """
    Approximate token count as ceil(len(text) / chars_per_token).

    Documented approximation — room for future model-specific tokenizers.
    """

    def __init__(self, *, chars_per_token: float = 4.0) -> None:
        self.chars_per_token = chars_per_token

    def count(self, text: str) -> int:
        if not text:
            return 0
        return max(1, math.ceil(len(text) / self.chars_per_token))
