"""Project API routes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project, ProjectStatus
from app.projects.discovery import get_discovery_status
from app.projects.service import ProjectService


router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreateRequest(BaseModel):
    path: str = Field(..., min_length=1)
    name: str | None = None
    enable_capture: bool = False


class ProjectUpdateRequest(BaseModel):
    capture_enabled: bool | None = None


class ProjectScanRequest(BaseModel):
    roots: list[str] | None = None
    include_auto_drives: bool = True


class ProjectResponse(BaseModel):
    model_config = {"from_attributes": True}

    id: str
    name: str
    namespace: str
    root_path: str
    canonical_path: str
    git_root: str | None
    remote_url: str | None
    default_branch: str | None
    status: str
    capture_enabled: bool
    discovered_at: datetime
    last_activity_at: datetime | None
    last_capture_at: datetime | None = None
    metadata: dict[str, Any] = Field(validation_alias="metadata_")
    ignored: bool = False
    discovery_source: str | None = None
    discovery_evidence: list[str] = Field(default_factory=list)
    last_discovered_at: datetime | None = None
    memory_count: int = 0
    capture_event_count: int = 0
    processed_capture_count: int = 0
    ignored_capture_count: int = 0
    failed_capture_count: int = 0


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
    total: int


class SkippedCandidateInfo(BaseModel):
    path: str
    reason: str


class DriveReportInfo(BaseModel):
    root_path: str
    drive_type: str
    status: str
    reason: str | None = None


class ProjectScanResponse(BaseModel):
    started_at: datetime
    finished_at: datetime | None
    duration_ms: int
    drives: list[DriveReportInfo]
    roots_scanned: list[str]
    directories_considered: int
    directories_skipped: int
    skipped_by_reason: dict[str, int]
    permission_errors: int
    max_depth_reached: int
    projects_found: int
    projects_new_count: int
    projects_existing_count: int
    discovered: list[ProjectResponse]
    existing: list[ProjectResponse]
    skipped_candidates: list[SkippedCandidateInfo]


class DiscoveryStatusResponse(BaseModel):
    scan_in_progress: bool
    last_scan: dict[str, Any] | None


class ProjectActivityResponse(BaseModel):
    project_id: str
    namespace: str
    last_activity_at: datetime | None
    status: str
    capture_enabled: bool
    recent_captures: list[dict[str, Any]]


def _to_response(project: Project, memory_count: int | None = None) -> ProjectResponse:
    counts = {project.namespace: memory_count} if memory_count is not None else {}
    return _to_response_with_counts(project, counts)


def _to_response_with_counts(
    project: Project, 
    counts: dict[str, int],
    capture_counts: dict[str, dict[str, int]] | None = None,
    last_capture_timestamps: dict[str, datetime | None] | None = None,
) -> ProjectResponse:
    capture_stats = capture_counts.get(project.id, {}) if capture_counts else {}
    total_events = sum(capture_stats.values())
    
    # Calculate sub-counts from the detailed stats
    # completed_STORE = stored memories, completed_IGNORE = ignored
    processed_count = capture_stats.get("completed_STORE", 0) + capture_stats.get("completed_IGNORE", 0)
    ignored_count = capture_stats.get("completed_IGNORE", 0)
    stored_count = capture_stats.get("completed_STORE", 0)
    failed_count = capture_stats.get("failed", 0)
    pending_count = capture_stats.get("pending", 0)
    
    return ProjectResponse(
        id=project.id,
        name=project.name,
        namespace=project.namespace,
        root_path=project.root_path,
        canonical_path=project.canonical_path,
        git_root=project.git_root,
        remote_url=project.remote_url,
        default_branch=project.default_branch,
        status=project.status.value if hasattr(project.status, "value") else str(project.status),
        capture_enabled=project.capture_enabled,
        discovered_at=project.discovered_at,
        last_activity_at=project.last_activity_at,
        last_capture_at=last_capture_timestamps.get(project.id) if last_capture_timestamps else None,
        metadata_=project.metadata_,
        ignored=project.ignored,
        discovery_source=project.discovery_source,
        discovery_evidence=list(project.discovery_evidence_json or []),
        last_discovered_at=project.last_discovered_at,
        memory_count=counts.get(project.namespace, 0),
        capture_event_count=total_events,
        processed_capture_count=processed_count,
        ignored_capture_count=ignored_count,
        failed_capture_count=failed_count,
    )


@router.post(
    "/register",
    response_model=ProjectResponse,
    summary="Register a project",
)
def register_project(
    payload: ProjectCreateRequest,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """Register a project at the given path."""
    service = ProjectService(db)
    project = service.register_project(
        payload.path,
        name=payload.name,
        enable_capture=payload.enable_capture,
        discovery_source="manual",
    )
    if project is None:
        raise HTTPException(status_code=404, detail="Project path does not exist")
    db.commit()
    return _to_response(project)


@router.post(
    "/scan",
    response_model=ProjectScanResponse,
    summary="Scan workspace roots and eligible drives for projects",
)
def scan_projects(
    payload: ProjectScanRequest | None = None,
    db: Session = Depends(get_db),
) -> ProjectScanResponse:
    """Run one bounded workstation discovery pass."""
    service = ProjectService(db)
    request = payload or ProjectScanRequest()
    try:
        outcome = service.run_workstation_scan(
            roots=request.roots,
            include_auto_drives=request.include_auto_drives,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=500, detail=f"Discovery scan failed: {exc}") from exc

    db.commit()

    counts = service.memory_counts_by_namespace()
    summary = outcome.to_summary()
    return ProjectScanResponse(
        started_at=summary["started_at"],
        finished_at=summary["finished_at"],
        duration_ms=summary["duration_ms"],
        drives=[DriveReportInfo(**d) for d in summary["drives"]],
        roots_scanned=summary["roots_scanned"],
        directories_considered=summary["directories_considered"],
        directories_skipped=summary["directories_skipped"],
        skipped_by_reason=summary["skipped_by_reason"],
        permission_errors=summary["permission_errors"],
        max_depth_reached=summary["max_depth_reached"],
        projects_found=summary["projects_found"],
        projects_new_count=len(outcome.projects_new),
        projects_existing_count=len(outcome.projects_existing),
        discovered=[_to_response_with_counts(p, counts) for p in outcome.projects_new],
        existing=[_to_response_with_counts(p, counts) for p in outcome.projects_existing],
        skipped_candidates=[SkippedCandidateInfo(**s) for s in summary["skipped_candidates"]],
    )


@router.get(
    "/discovery/status",
    response_model=DiscoveryStatusResponse,
    summary="Get last discovery scan result and progress",
)
def discovery_status() -> DiscoveryStatusResponse:
    status = get_discovery_status()
    return DiscoveryStatusResponse(scan_in_progress=status["scan_in_progress"], last_scan=status["last_scan"])


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List registered projects",
)
def list_projects(
    status: ProjectStatus | None = Query(None),
    capture_enabled: bool | None = Query(None),
    include_ignored: bool = Query(False),
    limit: int = Query(500, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ProjectListResponse:
    """List ALL registered projects — including ones with zero memories."""
    service = ProjectService(db)
    projects, memory_counts, capture_counts, last_capture_timestamps, total = service.list_projects_with_full_counts(
        status=status,
        capture_enabled=capture_enabled,
        include_ignored=include_ignored,
        limit=limit,
        offset=offset,
    )
    return ProjectListResponse(
        projects=[_to_response_with_counts(p, memory_counts, capture_counts, last_capture_timestamps) for p in projects],
        total=total,
    )


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Get project details",
)
def get_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """Get a project by ID."""
    service = ProjectService(db)
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    counts = service.memory_counts_by_namespace()
    return _to_response_with_counts(project, counts)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    summary="Update project",
)
def update_project(
    project_id: str,
    payload: ProjectUpdateRequest,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """Update project settings."""
    service = ProjectService(db)
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    if payload.capture_enabled is not None:
        if payload.capture_enabled:
            project = service.enable_capture(project_id)
        else:
            project = service.disable_capture(project_id)

    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    db.commit()
    counts = service.memory_counts_by_namespace()
    return _to_response_with_counts(project, counts)


@router.post(
    "/{project_id}/ignore",
    response_model=ProjectResponse,
    summary="Ignore a project (hidden from scans and default lists)",
)
def ignore_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    service = ProjectService(db)
    project = service.set_ignored(project_id, True)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.commit()
    return _to_response(project)


@router.post(
    "/{project_id}/unignore",
    response_model=ProjectResponse,
    summary="Unignore a previously ignored project",
)
def unignore_project(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    service = ProjectService(db)
    project = service.set_ignored(project_id, False)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.commit()
    return _to_response(project)


@router.post(
    "/{project_id}/enable",
    response_model=ProjectResponse,
    summary="Enable capture for a project",
)
def enable_capture(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """Enable capture for a project."""
    service = ProjectService(db)
    project = service.enable_capture(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.commit()
    counts = service.memory_counts_by_namespace()
    return _to_response_with_counts(project, counts)


@router.post(
    "/{project_id}/disable",
    response_model=ProjectResponse,
    summary="Disable capture for a project",
)
def disable_capture(
    project_id: str,
    db: Session = Depends(get_db),
) -> ProjectResponse:
    """Disable capture for a project."""
    service = ProjectService(db)
    project = service.disable_capture(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    db.commit()
    counts = service.memory_counts_by_namespace()
    return _to_response_with_counts(project, counts)


@router.get(
    "/{project_id}/activity",
    response_model=ProjectActivityResponse,
    summary="Get project activity",
)
def get_project_activity(
    project_id: str,
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
) -> ProjectActivityResponse:
    """Get recent capture activity for a project."""
    from app.capture.repository import CaptureEventRepository

    service = ProjectService(db)
    project = service.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    repo = CaptureEventRepository(db)
    captures = repo.list_by_project(project_id, limit=limit)

    return ProjectActivityResponse(
        project_id=project.id,
        namespace=project.namespace,
        last_activity_at=project.last_activity_at,
        status=project.status.value,
        capture_enabled=project.capture_enabled,
        recent_captures=[
            {
                "id": c.id,
                "source": c.source.value,
                "event_type": c.source_event_type.value,
                "content": c.content[:200],
                "occurred_at": c.occurred_at,
                                "captured_at": c.captured_at,
                "processing_status": c.processing_status.value,
                "status": c.processing_status.value,
                "memory_id": c.memory_id,
            }
            for c in captures
        ],
    )
