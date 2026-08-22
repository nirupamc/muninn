"""Small Munin CLI (integration debugging + agent helpers)."""

from __future__ import annotations

import argparse
import logging
import sys

from app.config import get_settings
from app.database import SessionLocal
from app.main import configure_logging
from app.services.embedding_service import EmbeddingService


def cmd_embed_memories(_args: object | None = None) -> int:
    """Embed memories that do not yet have an embedding row."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("munin.cli")

    db = SessionLocal()
    try:
        service = EmbeddingService(db)
        summary = service.backfill_missing()
        logger.info(
            "Backfill complete scanned_missing=%s embedded=%s failed=%s",
            summary["scanned_missing"],
            summary["embedded"],
            summary["failed"],
        )
        print(
            "Backfill complete: "
            f"scanned_missing={summary['scanned_missing']} "
            f"embedded={summary['embedded']} "
            f"failed={summary['failed']}"
        )
        return 1 if summary["failed"] else 0
    finally:
        db.close()


def _client_from_args(args) -> object:
    from app.sdk import MuninClient

    base_url = getattr(args, "base_url", None) or "http://127.0.0.1:8000"
    return MuninClient(
        base_url=base_url,
        namespace=getattr(args, "namespace", "default") or "default",
        user_id=getattr(args, "user", None),
        agent_id=getattr(args, "agent", None),
        api_key=getattr(args, "api_key", None),
    )


def cmd_health(args) -> int:
    client = _client_from_args(args)
    with client:
        health = client.health()
        print(f"status={health.status} service={health.service or 'n/a'}")
    return 0 if health.status == "ok" else 1


def cmd_context(args) -> int:
    client = _client_from_args(args)
    with client:
        ctx = client.get_context(
            args.query,
            token_budget=args.token_budget,
            max_memories=args.max_memories,
        )
    print(ctx.text)
    print(
        f"\n[estimated_tokens={ctx.estimated_tokens} "
        f"truncated={ctx.truncated} memories_used={len(ctx.memories_used)}]"
    )
    return 0


def cmd_remember(args) -> int:
    client = _client_from_args(args)
    with client:
        result = client.remember(
            args.content,
            role=getattr(args, "role", "assistant") or "assistant",
            session_id=getattr(args, "session", None),
            idempotency_key=getattr(args, "idempotency_key", None),
        )
    print(
        f"event_id={result.event_id} remembered={result.remembered} "
        f"decision={result.decision} memory_id={result.memory_id or '-'} "
        f"dedup={result.dedup_relationship or '-'} "
        f"temporal={result.temporal_relationship or '-'} "
        f"replay={result.idempotent_replay}"
    )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="munin", description="Munin CLI (embed helpers + agent tools)"
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "embed-memories",
        help="Backfill embeddings for memories that do not have one",
    )

    # Shared agent connection flags.
    def _add_agent_args(p: argparse.ArgumentParser) -> None:
        p.add_argument("--base-url", default="http://127.0.0.1:8000")
        p.add_argument("--namespace", default="default")
        p.add_argument("--user", default=None)
        p.add_argument("--agent", default=None)
        p.add_argument("--api-key", default=None)

    he = sub.add_parser("health", help="Check Munin connectivity")
    _add_agent_args(he)

    c = sub.add_parser("context", help="Retrieve agent-ready durable memory context")
    _add_agent_args(c)
    c.add_argument("--query", required=True)
    c.add_argument("--token-budget", type=int, default=1500)
    c.add_argument("--max-memories", type=int, default=20)

    r = sub.add_parser("remember", help="Remember a useful interaction")
    _add_agent_args(r)
    r.add_argument("--content", required=True)
    r.add_argument("--role", default="assistant")
    r.add_argument("--session", default=None)
    r.add_argument("--idempotency-key", default=None)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "embed-memories": cmd_embed_memories,
        "health": cmd_health,
        "context": cmd_context,
        "remember": cmd_remember,
    }
    handler = handlers.get(args.command)
    if handler is None:
        parser.error(f"Unknown command: {args.command}")
    raise SystemExit(handler(args))


if __name__ == "__main__":
    main(sys.argv[1:])
