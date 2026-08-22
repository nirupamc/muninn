"""End-to-end SDK verification against a live Munin server.

Requires the server to be running on http://127.0.0.1:8000.

Run:
    python scripts/sdk_verify.py
"""

from __future__ import annotations

import sys

from app.sdk import MuninClient
from app.sdk.errors import (
    MuninValidationError,
    MuninError,
)


def main() -> int:
    base = "http://127.0.0.1:8000"
    ns = "project:munin"
    ok = True

    with MuninClient(
        base_url=base,
        namespace=ns,
        user_id="user-1",
        agent_id="cursor",
        timeout=(5.0, 30.0),
        max_retries=2,
    ) as client:
        # health()
        h = client.health()
        print(f"[health] status={h.status} service={h.service}")
        ok = ok and h.status == "ok"

        # remember() -> STORE
        r = client.remember("Munin M0 through M6 are complete.")
        print(f"[remember] decision={r.decision} remembered={r.remembered} "
              f"mem={r.memory_id is not None}")
        ok = ok and r.decision == "STORE" and r.remembered

        # idempotent remember (same key)
        r2 = client.remember(
            "Munin M0 through M6 are complete.",
            idempotency_key="sdk-ik-1",
        )
        r3 = client.remember(
            "Munin M0 through M6 are complete.",
            idempotency_key="sdk-ik-1",
        )
        print(f"[idempotency] replay={r3.idempotent_replay}")
        ok = ok and r3.idempotent_replay is True

        # get_context()
        ctx = client.get_context("Continue the Munin project.")
        print(f"[context] tokens={ctx.estimated_tokens} "
              f"memories_used={len(ctx.memories_used)} "
              f"has_m6={'m6' in (ctx.text or '').lower() or 'complete' in (ctx.text or '').lower()}")
        ok = ok and len(ctx.memories_used) >= 1

        # structured validation error (blank content)
        try:
            client.remember("   ")
            print("[validation] ERROR: blank content was accepted")
            ok = False
        except MuninValidationError as exc:
            print(f"[validation] correct rejection: {exc.status} {exc.code}")
        except MuninError as exc:
            print(f"[validation] raised MuninError (acceptable): {exc}")
        except Exception as exc:  # noqa: BLE001
            print(f"[validation] unexpected error type: {type(exc).__name__}: {exc}")
            ok = False

    # timeout behavior: connect to a dead port should raise MuninTimeoutError/
    # MuninConnectionError, never hang.
    try:
        with MuninClient(base_url="http://127.0.0.1:9", timeout=(1.0, 1.0),
                         max_retries=1) as bad:
            bad.health()
        print("[timeout] ERROR: no error on dead server")
        ok = False
    except MuninError as exc:
        print(f"[timeout] correct structured error: {type(exc).__name__}")

    print("\nSDK verification:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
