"""Explicit SDK error model (M7A)."""

from __future__ import annotations

from typing import Any


class MuninError(Exception):
    """Base class for all Munin SDK errors."""

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        code: str | None = None,
        body: Any = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code
        self.body = body

    def __str__(self) -> str:
        parts = [self.message]
        if self.status is not None:
            parts.append(f"status={self.status}")
        if self.code is not None:
            parts.append(f"code={self.code}")
        return " | ".join(parts) + f" ({super().__str__()})"


class MuninConnectionError(MuninError):
    """Raised when the client cannot reach the Munin server."""


class MuninTimeoutError(MuninError):
    """Raised when a request exceeds the configured timeout."""


class MuninValidationError(MuninError):
    """Raised for 400/422 responses (invalid request payload)."""


class MuninServerError(MuninError):
    """Raised for 5xx server errors."""


class MuninHTTPError(MuninError):
    """Raised for any non-2xx HTTP response not covered above."""