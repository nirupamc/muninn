"""Projects package."""

from app.projects.detectors import ProjectEvidence, detect_evidence, is_project
from app.projects.drives import DiscoveredDrive, DriveDiscoveryService, DriveType
from app.projects.repository import ProjectRepository
from app.projects.scanner import DetectedProject, ScanResult, WorkspaceScanner
from app.projects.service import ProjectService

__all__ = [
    "ProjectRepository",
    "ProjectService",
    "DetectedProject",
    "ScanResult",
    "WorkspaceScanner",
    "DiscoveredDrive",
    "DriveDiscoveryService",
    "DriveType",
    "ProjectEvidence",
    "detect_evidence",
    "is_project",
]
