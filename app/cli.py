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
            summary["scanned_missing"], summary["embedded"], summary["failed"],
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


def cmd_memory_representations(args) -> int:
    """Manage hierarchical memory representations (M10)."""
    settings = get_settings()
    configure_logging(settings.log_level)
    logger = logging.getLogger("munin.cli")

    db = SessionLocal()
    try:
        from app.memory.representations.service import RepresentationService
        service = RepresentationService(db)

        if args.repr_command == "backfill":
            dry_run = getattr(args, "dry_run", False)
            batch_size = getattr(args, "batch_size", 100)
            skip_existing = not getattr(args, "force", False)

            print(f"Backfilling representations (dry_run={dry_run}, batch_size={batch_size})...")
            stats = service.backfill(
                batch_size=batch_size,
                dry_run=dry_run,
                skip_existing=skip_existing,
            )
            print(f"\nBackfill complete:")
            print(f"  scanned: {stats['scanned']}")
            print(f"  updated: {stats['updated']}")
            print(f"  skipped: {stats['skipped']}")
            print(f"  failed:  {stats['failed']}")
            return 1 if stats["failed"] else 0
        else:
            print(f"Unknown representations command: {args.repr_command}")
            return 1
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
        if project is None:
            print(f"Path does not exist: {args.path}")
            return 1
        db.commit()
        print(f"id={project.id} name={project.name} namespace={project.namespace} path={project.canonical_path}")
        return 0
    finally:
        db.close()


def cmd_project_list(args) -> int:
    db = SessionLocal()
    try:
        service = ProjectService(db)
        include_ignored = getattr(args, "include_ignored", False)
        projects, counts, _total = service.list_projects_with_counts(
            include_ignored=include_ignored,
            limit=args.limit,
            offset=args.offset,
        )
        if not projects:
            print("No projects found.")
            return 0
        for p in projects:
            memory_count = counts.get(p.namespace, 0)
            ignored = " [IGNORED]" if p.ignored else ""
            git = "git" if p.git_root else "no-git"
            print(
                f"{p.id}  {p.name:<30} {p.namespace:<30} {p.status.value:<12} "
                f"capture={str(p.capture_enabled):<5} {git:<6} memories={memory_count}{ignored}  {p.canonical_path}"
            )
        return 0
    finally:
        db.close()


def cmd_project_drives(_args) -> int:
    from app.projects.drives import DriveDiscoveryService

    settings = get_settings()
    service = DriveDiscoveryService()
    excluded = {p.strip() for p in settings.project_discovery_excluded_roots.split(";") if p.strip()}
    drives = service.list_drives(
        include_fixed=settings.auto_discover_fixed_drives,
        include_removable=settings.auto_discover_removable_drives,
        include_network=settings.auto_discover_network_drives,
        excluded_roots=excluded,
    )
    if not drives:
        print("No drives found.")
        return 0
    for d in drives:
        state = "enabled" if d.enabled_for_scan else "disabled"
        reason = f" ({d.skip_reason})" if d.skip_reason else ""
        accessible = "" if d.accessible else " [unavailable]"
        print(f"{d.root_path:<4} {d.drive_type.value:<10} {state}{reason}{accessible}")
    return 0


def cmd_project_scan(args) -> int:
    from app.projects.discovery import ProjectDiscoveryService as Orchestrator

    db = SessionLocal()
    try:
        orchestrator = Orchestrator(db)
        outcome = orchestrator.run_scan(
            roots=list(args.roots) if args.roots else None,
            include_auto_drives=not args.no_auto_drives,
        )
        summary = outcome.to_summary()

        print("\nDrive Discovery")
        print("---------------")
        for d in summary["drives"]:
            line = f"{d['root_path']:<5} {d['drive_type']:<10} {d['status']}"
            if d.get("reason"):
                line += f" ({d['reason']})"
            print(line)
        if not summary["drives"]:
            print("(automatic drive discovery disabled)")

        print("\nScan summary:")
        print(f"  roots_scanned:            {len(summary['roots_scanned'])}")
        print(f"  directories_considered:   {summary['directories_considered']}")
        print(f"  directories_skipped:      {summary['directories_skipped']}")
        print(f"  permission_errors:        {summary['permission_errors']}")
        print(f"  max_depth_reached:        {summary['max_depth_reached']}")
        print(f"  projects_found:           {summary['projects_found']}")
        print(f"  projects_new:             {summary['projects_new']}")
        print(f"  projects_existing:        {summary['projects_existing']}")
        print(f"  duration_ms:              {summary['duration_ms']}")

        db.commit()

        print("\nNew projects:")
        if not outcome.projects_new:
            print("  (none)")
        for p in outcome.projects_new:
            print(f"  DETECTED {p.canonical_path}")
            if args.verbose:
                evidence = ", ".join(p.discovery_evidence_json or [])
                print(f"    namespace: {p.namespace}")
                print(f"    evidence:  {evidence or 'n/a'}")
                print(f"    git:       {'yes' if p.git_root else 'no'}")

        if args.verbose and summary["skipped_candidates"]:
            print("\nSkipped candidates (bounded sample):")
            for sk in summary["skipped_candidates"]:
                print(f"  SKIPPED {sk['path']}")
                print(f"    reason: {sk['reason']}")
        return 0
    finally:
        db.close()


def cmd_project_enable(args) -> int:
    db = SessionLocal()
    try:
        service = ProjectService(db)
        project = service.find_project(args.project_id) or service.get_project(args.project_id)
        if not project:
            print("Project not found")
            return 1
        project = service.enable_capture(project.id)
        print(f"Capture enabled for {project.name} ({project.namespace})")
        db.commit()
        return 0
    finally:
        db.close()


def cmd_project_disable(args) -> int:
    db = SessionLocal()
    try:
        service = ProjectService(db)
        project = service.find_project(args.project_id)
        if not project:
            print("Project not found")
            return 1
        project = service.disable_capture(project.id)
        print(f"Capture disabled for {project.name} ({project.namespace})")
        db.commit()
        return 0
    finally:
        db.close()


def cmd_project_ignore(args) -> int:
    db = SessionLocal()
    try:
        service = ProjectService(db)
        project = service.find_project(args.project)
        if not project:
            print("Project not found")
            return 1
        service.set_ignored(project.id, True)
        db.commit()
        print(f"Ignored: {project.name} ({project.canonical_path})")
        return 0
    finally:
        db.close()


def cmd_project_unignore(args) -> int:
    db = SessionLocal()
    try:
        service = ProjectService(db)
        project = service.find_project(args.project)
        if not project:
            print("Project not found (ignored projects are still resolvable by id/namespace)")
            return 1
        service.set_ignored(project.id, False)
        db.commit()
        print(f"Unignored: {project.name} ({project.canonical_path})")
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


def cmd_capture_agent_sessions(args) -> int:
    """Show agent session adapter status."""
    db = SessionLocal()
    try:
        from app.capture.agent_sessions.service import AgentSessionService
        
        service = AgentSessionService(db)
        health = service.get_adapter_health()
        available = service.get_available_adapters()
        
        print("Agent Session Adapters:")
        print("-" * 60)
        
        for source, info in health.items():
            status = "available" if info.get("available") else "unavailable"
            integration = info.get("integration_status", "unknown")
            print(f"  {source.value:15} status={status:12} integration={integration}")
        
        print(f"\nAvailable adapters: {len(available)}")
        for a in available:
            print(f"  - {a.value}")
        
        # Try to discover sessions
        sessions = service.discover_sessions()
        print(f"\nDiscovered sessions: {len(sessions)}")
        
        return 0
    finally:
        db.close()


def cmd_run(args) -> int:
    """Run a coding agent with Munin context injection."""
    from app.agents.runner import AgentRunner, RunConfig
    from app.agents.types import AgentLaunchResult

    # Parse agent name and extra args from REMAINDER list.
    # Convention: munin run [flags] -- codex [agent args...]
    # After argparse REMAINDER, args.agent is a list like ['codex', '--verbose']
    # or ['--', 'codex', '--verbose'] depending on how user typed it.
    agent_parts = args.agent or []
    # Strip leading '--' separator if present
    if agent_parts and agent_parts[0] == "--":
        agent_parts = agent_parts[1:]

    if not agent_parts:
        print("Error: No agent specified. Usage: munin run [flags] -- <agent> [args...]", file=sys.stderr)
        return 1

    agent_name = agent_parts[0]
    extra_args = agent_parts[1:]

    # Parse project argument if it's a path
    project_path = None
    project_id = None
    namespace = None

    if args.project:
        # Try to determine if it's a path or namespace
        if args.project.startswith("project:") or ":" not in args.project:
            # Likely a namespace
            namespace = args.project
        else:
            # Treat as path
            project_path = args.project

    if args.project_id:
        project_id = args.project_id

    config = RunConfig(
        agent_name=agent_name,
        project_path=project_path,
        project_id=project_id,
        namespace=namespace,
        task=args.task,
        extra_args=extra_args,
        dry_run=args.dry_run,
        token_budget=args.token_budget,
        max_memories=args.max_memories,
    )

    runner = AgentRunner(config)
    result: AgentLaunchResult = runner.run()

    if not result.success:
        print(f"Error: {result.error}", file=sys.stderr)
        return 1

    if args.dry_run:
        # Dry run output is already printed by runner
        return 0

    # For actual run, the agent should have been launched
    if result.exit_code is not None and result.exit_code != 0:
        return result.exit_code

    return 0


def cmd_agents(args) -> int:
    """Show installed coding agent status."""
    from app.agents.registry import get_registry
    
    registry = get_registry()
    table = registry.get_status_table()
    
    print("Installed Coding Agents:")
    print("-" * 80)
    print(f"{'Name':<15} {'Type':<15} {'Installed':<12} {'Status':<20} {'Executable'}")
    print("-" * 80)
    
    for row in table:
        installed = "yes" if row["installed"] else "no"
        executable = row["executable"][:40] + "..." if len(row["executable"]) > 40 else row["executable"]
        print(f"{row['name']:<15} {row['type']:<15} {installed:<12} {row['status']:<20} {executable}")
    
    print(f"\nTotal agents: {len(table)}")
    installed_count = sum(1 for row in table if row["installed"])
    print(f"Installed: {installed_count}")
    
    return 0


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

    list_p = proj_sub.add_parser("list", help="List registered projects (including zero-memory)")
    list_p.add_argument("--limit", type=int, default=200)
    list_p.add_argument("--offset", type=int, default=0)
    list_p.add_argument("--include-ignored", action="store_true", help="Also show ignored projects")

    proj_sub.add_parser("drives", help="Show discovered drives and scan eligibility")

    scan_p = proj_sub.add_parser(
        "scan",
        help="Scan eligible drives (and workspace roots) for projects",
    )
    scan_p.add_argument("roots", nargs="*", help="Optional explicit roots to scan instead of auto drives")
    scan_p.add_argument("--no-auto-drives", action="store_true", help="Do not expand to automatic drive discovery")
    scan_p.add_argument("--verbose", action="store_true", help="Show evidence and skipped-candidate diagnostics")

    enable_p = proj_sub.add_parser("enable", help="Enable capture for a project")
    enable_p.add_argument("project_id", help="Project ID or namespace")

    disable_p = proj_sub.add_parser("disable", help="Disable capture for a project")
    disable_p.add_argument("project_id", help="Project ID or namespace")

    ignore_p = proj_sub.add_parser("ignore", help="Ignore a project (excluded from scans and default lists)")
    ignore_p.add_argument("project", help="Project ID or namespace")

    unignore_p = proj_sub.add_parser("unignore", help="Stop ignoring a project")
    unignore_p.add_argument("project", help="Project ID or namespace")

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
    
    # Agent session commands (M8.3)
    cap_sub.add_parser("agent-sessions", help="Show agent session adapter status")

    # Agent run commands (M8.3B)
    # Convention: munin run [munin flags] -- <agent> [agent args...]
    # Named Munin flags go BEFORE the agent name.
    run_p = sub.add_parser(
        "run",
        help="Run a coding agent with Munin context injection",
    )
    run_p.add_argument("--project", default=None, help="Project path or namespace")
    run_p.add_argument("--project-id", default=None, help="Project ID")
    run_p.add_argument("--task", default=None, help="Task description for context targeting")
    run_p.add_argument("--token-budget", type=int, default=1500, help="Token budget for context")
    run_p.add_argument("--max-memories", type=int, default=20, help="Max memories for context")
    run_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be executed without launching",
    )
    run_p.add_argument(
        "agent",
        nargs=argparse.REMAINDER,
        help="Agent name and arguments after -- separator",
    )

    # Agent status command (M8.3B)
    sub.add_parser(
        "agents",
        help="Show installed coding agent status",
    )

    # M10 — Memory representations
    repr_p = sub.add_parser(
        "memory-representations",
        help="Manage hierarchical memory representations (M10)",
    )
    repr_sub = repr_p.add_subparsers(dest="repr_command", required=True)

    backfill_p = repr_sub.add_parser(
        "backfill",
        help="Backfill L0/L1 representations for existing memories",
    )
    backfill_p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing",
    )
    backfill_p.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of memories per batch",
    )
    backfill_p.add_argument(
        "--force",
        action="store_true",
        help="Regenerate even if representations already exist",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    handlers = {
        "embed-memories": cmd_embed_memories,
        "health": cmd_health,
        "context": cmd_context,
        "remember": cmd_remember,
        "run": cmd_run,
        "agents": cmd_agents,
        "memory-representations": {
            "backfill": cmd_memory_representations,
        },
        "project": {
            "add": cmd_project_add,
            "list": cmd_project_list,
            "drives": cmd_project_drives,
            "scan": cmd_project_scan,
            "enable": cmd_project_enable,
            "disable": cmd_project_disable,
            "ignore": cmd_project_ignore,
            "unignore": cmd_project_unignore,
        },
        "capture": {
            "event": cmd_capture_event,
            "summary": cmd_capture_summary,
            "status": cmd_capture_status,
            "agent-sessions": cmd_capture_agent_sessions,
        },
    }

    if args.command in ("project", "capture", "memory-representations"):
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
