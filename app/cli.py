"""Small Munin CLI (integration debugging + agent helpers)."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from app.config import get_settings
from app.database import SessionLocal
from app.main import configure_logging
from app.services.embedding_service import EmbeddingService
from app.projects.service import ProjectService
from app.capture.project_resolver import ProjectResolver
from app.capture.service import CaptureService
from app.models.capture import CaptureSource, CaptureEventType


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


# Project commands
def cmd_project_add(args) -> int:
    db = SessionLocal()
    try:
        service = ProjectService(db)
        project = service.register_project(args.path, name=args.name, enable_capture=args.enable_capture)
        print(f"id={project.id} name={project.name} namespace={project.namespace} path={project.canonical_path}")
        return 0
    finally:
        db.close()


def cmd_project_list(args) -> int:
    db = SessionLocal()
    try:
        service = ProjectService(db)
        projects = service.list_projects(limit=args.limit, offset=args.offset)
        if not projects:
            print("No projects found.")
            return 0
        for p in projects:
            print(f"{p.id}  {p.name:<30} {p.namespace:<30} {p.status.value:<12} capture={p.capture_enabled}  {p.canonical_path}")
        return 0
    finally:
        db.close()


def cmd_project_scan(args) -> int:
    db = SessionLocal()
    try:
        service = ProjectService(db)
        discovered = service.scan_workspace_roots()
        if not discovered:
            print("No projects discovered.")
            return 0
        for p in discovered:
            print(f"DISCOVERED: {p.name} ({p.namespace}) at {p.canonical_path}")
        return 0
    finally:
        db.close()


def cmd_project_enable(args) -> int:
    db = SessionLocal()
    try:
        service = ProjectService(db)
        project = service.enable_capture(args.project_id)
        if project:
            print(f"Capture enabled for {project.name} ({project.namespace})")
        else:
            print("Project not found")
            return 1
        return 0
    finally:
        db.close()


def cmd_project_disable(args) -> int:
    db = SessionLocal()
    try:
        service = ProjectService(db)
        project = service.disable_capture(args.project_id)
        if project:
            print(f"Capture disabled for {project.name} ({project.namespace})")
        else:
            print("Project not found")
            return 1
        return 0
    finally:
        db.close()


# Capture commands
def cmd_capture_event(args) -> int:
    db = SessionLocal()
    try:
        resolver = ProjectResolver(db)
        service = CaptureService(db)

        project = resolver.resolve_or_create(
            path=args.path,
            namespace=args.namespace,
            auto_register=not args.no_auto_register,
        )

        if not project:
            print("Project not found. Use --path or --namespace, or register first.")
            return 1

        capture = service.capture_event(
            project=project,
            source=CaptureSource(args.source),
            source_event_type=CaptureEventType(args.type),
            content=args.content,
            agent_id=args.agent,
            session_id=args.session,
            working_directory=args.working_dir,
        )
        print(f"capture_id={capture.id} status={capture.processing_status.value} memory_id={capture.memory_id or '-'}")
        return 0
    finally:
        db.close()


def cmd_capture_summary(args) -> int:
    db = SessionLocal()
    try:
        resolver = ProjectResolver(db)
        service = CaptureService(db)

        project = resolver.resolve_or_create(
            path=args.path,
            namespace=args.namespace,
            auto_register=not args.no_auto_register,
        )

        if not project:
            print("Project not found. Use --path or --namespace, or register first.")
            return 1

        capture = service.capture_agent_summary(
            project=project,
            summary=args.content,
            agent_id=args.agent,
            session_id=args.session,
            working_directory=args.working_dir,
        )
        print(f"capture_id={capture.id} status={capture.processing_status.value} memory_id={capture.memory_id or '-'}")
        return 0
    finally:
        db.close()


def cmd_capture_status(args) -> int:
    db = SessionLocal()
    try:
        from app.projects.repository import ProjectRepository
        from app.capture.repository import CaptureEventRepository
        from app.models.capture import CaptureProcessingStatus
        from app.capture.manager import get_capture_manager

        project_repo = ProjectRepository(db)
        projects = project_repo.list_all(capture_enabled=True, limit=1000)

        capture_repo = CaptureEventRepository(db)
        total_events = 0
        pending_events = 0
        for p in projects:
            total_events += capture_repo.count_by_project(p.id)
            pending_events += capture_repo.count_by_project(p.id, status=CaptureProcessingStatus.pending)

        print(f"Projects with capture: {len(projects)}")
        print(f"Total capture events: {total_events}")
        print(f"Pending events: {pending_events}")

        manager = get_capture_manager()
        if manager:
            for project in projects:
                health = manager.get_adapter_health(project.id)
                print(f"\nProject: {project.name} ({project.namespace})")
                for h in health:
                    print(f"  {h['name']}: available={h['available']} last_check={h['last_check']}")

        return 0
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="munin", description="Munin CLI (embed helpers + agent tools + project capture)"
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

    # Project commands
    proj = sub.add_parser("project", help="Project management")
    proj_sub = proj.add_subparsers(dest="project_command", required=True)

    add_p = proj_sub.add_parser("add", help="Register a project")
    add_p.add_argument("path", help="Project root path")
    add_p.add_argument("--name", help="Project name (defaults to directory name)")
    add_p.add_argument("--enable-capture", action="store_true", help="Enable capture immediately")

    list_p = proj_sub.add_parser("list", help="List registered projects")
    list_p.add_argument("--limit", type=int, default=100)
    list_p.add_argument("--offset", type=int, default=0)

    proj_sub.add_parser("scan", help="Scan workspace roots for projects")

    enable_p = proj_sub.add_parser("enable", help="Enable capture for a project")
    enable_p.add_argument("project_id", help="Project ID or namespace")

    disable_p = proj_sub.add_parser("disable", help="Disable capture for a project")
    disable_p.add_argument("project_id", help="Project ID or namespace")

    # Capture commands
    cap = sub.add_parser("capture", help="Capture management")
    cap_sub = cap.add_subparsers(dest="capture_command", required=True)

    event_p = cap_sub.add_parser("event", help="Submit a capture event")
    event_p.add_argument("--path", help="Project path")
    event_p.add_argument("--namespace", help="Project namespace")
    event_p.add_argument("--source", choices=[s.value for s in CaptureSource], default="generic")
    event_p.add_argument("--type", choices=[t.value for t in CaptureEventType], default="manual_note")
    event_p.add_argument("--content", required=True)
    event_p.add_argument("--agent", default="cli")
    event_p.add_argument("--session", default=None)
    event_p.add_argument("--working-dir", default=None)
    event_p.add_argument("--no-auto-register", action="store_true", help="Don't auto-register project")

    summary_p = cap_sub.add_parser("summary", help="Submit an agent session summary")
    summary_p.add_argument("--path", help="Project path")
    summary_p.add_argument("--namespace", help="Project namespace")
    summary_p.add_argument("--content", required=True)
    summary_p.add_argument("--agent", default="cli")
    summary_p.add_argument("--session", default=None)
    summary_p.add_argument("--working-dir", default=None)
    summary_p.add_argument("--no-auto-register", action="store_true", help="Don't auto-register project")

    cap_sub.add_parser("status", help="Show capture system status")

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "embed-memories": cmd_embed_memories,
        "health": cmd_health,
        "context": cmd_context,
        "remember": cmd_remember,
        "project": {
            "add": cmd_project_add,
            "list": cmd_project_list,
            "scan": cmd_project_scan,
            "enable": cmd_project_enable,
            "disable": cmd_project_disable,
        },
        "capture": {
            "event": cmd_capture_event,
            "summary": cmd_capture_summary,
            "status": cmd_capture_status,
        },
    }

    if args.command in ("project", "capture"):
        handler_map = handlers[args.command]
        subcommand = getattr(args, f"{args.command}_command")
        handler = handler_map.get(subcommand)
        if handler is None:
            parser.error(f"Unknown {args.command} command: {subcommand}")
    else:
        handler = handlers.get(args.command)
        if handler is None:
            parser.error(f"Unknown command: {args.command}")

    raise SystemExit(handler(args))


if __name__ == "__main__":
    main(sys.argv[1:])
