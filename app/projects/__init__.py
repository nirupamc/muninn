"""Projects package."""

from app.projects.discovery import DiscoveredProject, ProjectDiscoveryService
from app.projects.repository import ProjectRepository
from app.projects.service import ProjectService

__all__ = [
    "ProjectRepository",
    "ProjectService",
    "ProjectDiscoveryService",
    "DiscoveredProject",
]