"""Project API routes."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.project import Project, ProjectStatus
from app.projects.service import ProjectService
from app.projects.discovery import ProjectDiscoveryService


router = APIRouter(prefix="/projects", tags=["projects"])


class ProjectCreateRequest(BaseModel):
    path: str = Field(..., min_length=1)
    name: str | None = None
    enable_capture: bool = False


class ProjectUpdateRequest(BaseModel):
    capture_enabled: bool | None = None


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
    metadata: dict[str, Any] = Field(validation_alias="metadata_")


class ProjectListResponse(BaseModel):
    projects: list[ProjectResponse]
    total: int


class ProjectScanResponse(BaseModel):
    discovered: list[ProjectResponse]


class ProjectActivityResponse(BaseModel):
    project_id: str
    namespace: str
    last_activity_at: datetime | None
    status: str
    capture_enabled: bool
    recent_captures: list[dict[str, Any]]


def _to_response(project: Project) -> ProjectResponse:
    return ProjectResponse(
        id=project.id,
        name=project.name,
        namespace=project.namespace,
        root_path=project.root_path,
        canonical_path=project.canonical_path,
        git_root=project.git_root,
        remote_url=project.remote_url,
        default_branch=project.default_branch,
        status=project.status.value,
        capture_enabled=project.capture_enabled,
        discovered_at=project.discovered_at,
        last_activity_at=project.last_activity_at,
        metadata=project.metadata_,
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
    )
    return _to_response(project)


@router.post(
    "/scan",
    response_model=ProjectScanResponse,
    summary="Scan workspace roots for projects",
)
def scan_projects(
    db: Session = Depends(get_db),
) -> ProjectScanResponse:
    """Scan configured workspace roots for Git repositories."""
    service = ProjectService(db)
    discovered = service.scan_workspace_roots()
    return ProjectScanResponse(projects=[_to_response(p) for p in discovered])


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="List projects",
)
def list_projects(
    status: ProjectStatus | None = Query(None),
    capture_enabled: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> ProjectListResponse:
    """List projects with optional filters."""
    service = ProjectService(db)
    projects = service.list_projects(
        status=status,
        capture_enabled=capture_enabled,
        limit=limit,
        offset=offset,
    )
    total = service.repo.count(status=status)
    return ProjectListResponse(
        projects=[_to_response(p) for p in projects],
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
    return _to_response(project)


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
    return _to_response(project)


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
    return _to_response(project)


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
    from app.models.capture import CaptureProcessingStatus

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
                "status": c.processing_status.value,
                "memory_id": c.memory_id,
            }
            for c in captures
        ],
    )