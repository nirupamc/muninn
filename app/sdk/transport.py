"""HTTP transport for the Munin SDK (sync, httpx-based).

Handles timeouts and retries. Only safe operations are retried:
- Idempotent reads (GET) and health checks.
- Writes that carry an ``idempotency_key`` (safe to replay server-side).

Non-idempotent writes are never retried.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.sdk.errors import (
    MuninConnectionError,
    MuninHTTPError,
    MuninServerError,
    MuninTimeoutError,
    MuninValidationError,
)

logger = logging.getLogger("munin.sdk.transport")

# Status codes safe to retry for idempotent requests.
RETRYABLE_STATUS = frozenset({502, 503, 504})


def _request_is_retryable(method: str, json_body: dict | None) -> bool:
    if method in ("GET", "HEAD", "OPTIONS"):
        return True
    if json_body and json_body.get("idempotency_key"):
        return True
    return False


class HttpTransport:
    """Thin httpx wrapper with per-request timeouts + safe retries."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout: tuple[float, float] = (5.0, 30.0),
        max_retries: int = 2,
        retry_statuses: frozenset[int] = RETRYABLE_STATUS,
    ) -> None:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            headers=headers,
            timeout=httpx.Timeout(timeout[1], connect=timeout[0]),
            follow_redirects=True,
        )
        self.max_retries = max_retries
        self.retry_statuses = retry_statuses

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        retryable = _request_is_retryable(method.upper(), json_body)
        attempts = (self.max_retries if retryable else 0) + 1
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                resp = self._client.request(
                    method,
                    path,
                    json=json_body,
                    params=params,
                )
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    continue
                raise MuninTimeoutError(
                    "Munin request timed out",
                    status=exc.__class__.__name__,
                ) from exc
            except httpx.HTTPError as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    continue
                raise MuninConnectionError(
                    f"Could not connect to Munin at {self._client.base_url}",
                    code=exc.__class__.__name__,
                ) from exc

            if resp.status_code in self.retry_statuses and attempt < attempts - 1:
                last_exc = None
                continue

            self._raise_for_status(resp)
            return resp

        # Unreachable in practice; defensive.
        raise MuninConnectionError(
            "Munin request failed after retries", body=str(last_exc)
        )

    def _raise_for_status(self, resp: httpx.Response) -> None:
        if 200 <= resp.status_code < 300:
            return
        body: Any = None
        try:
            body = resp.json()
        except Exception:  # noqa: BLE001
            body = resp.text
        message = f"Munin HTTP {resp.status_code}"
        if resp.status_code in (400, 422):
            raise MuninValidationError(
                message, status=resp.status_code, code="validation", body=body
            )
        if resp.status_code >= 500:
            raise MuninServerError(
                message, status=resp.status_code, code="server", body=body
            )
        raise MuninHTTPError(
            message, status=resp.status_code, code="http", body=body
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "HttpTransport":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()