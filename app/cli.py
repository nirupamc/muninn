"""Small Munin CLI (backfill helpers)."""

from __future__ import annotations

import argparse
import logging
import sys

from app.config import get_settings
from app.database import SessionLocal
from app.main import configure_logging
from app.services.embedding_service import EmbeddingService


def cmd_embed_memories() -> int:
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


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="munin", description="Munin CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser(
        "embed-memories",
        help="Backfill embeddings for memories that do not have one",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "embed-memories":
        raise SystemExit(cmd_embed_memories())

    parser.error(f"Unknown command: {args.command}")


if __name__ == "__main__":
    main(sys.argv[1:])
