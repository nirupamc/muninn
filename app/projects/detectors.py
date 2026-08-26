"""Deterministic project detection via filesystem evidence.

No LLM involvement. A directory is a project when accumulated marker
evidence crosses a threshold. Filenames/manifests only — never file contents.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# Evidence weights (deterministic, no ML).
GIT_ROOT = 100
PYPROJECT = 80
SOLUTION_FILE = 80
CARGO_TOML = 80
GO_MOD = 80
PACKAGE_JSON = 70
CSPROJ = 70
SETUP_PY = 65
POM_XML = 70
BUILD_GRADLE = 70
COMPOSER_JSON = 65
GEMFILE = 60
SETUP_CFG = 55
REQUIREMENTS_TXT = 50
PNPM_WORKSPACE = 45
YARN_LOCK = 40
DOCKERFILE = 30
SOURCE_DIR = 20
README_ONLY = 5

DEFAULT_THRESHOLD = 50

_MARKER_FILES: dict[str, int] = {
    "pyproject.toml": PYPROJECT,
    "setup.py": SETUP_PY,
    "setup.cfg": SETUP_CFG,
    "requirements.txt": REQUIREMENTS_TXT,
    "package.json": PACKAGE_JSON,
    "pnpm-workspace.yaml": PNPM_WORKSPACE,
    "yarn.lock": YARN_LOCK,
    "Cargo.toml": CARGO_TOML,
    "go.mod": GO_MOD,
    "pom.xml": POM_XML,
    "composer.json": COMPOSER_JSON,
    "Gemfile": GEMFILE,
    "Dockerfile": DOCKERFILE,
}

_SOLUTION_SUFFIXES = (".sln",)
_PROJECT_FILE_SUFFIXES = (".csproj", ".vbproj", ".fsproj")
_GRADLE_FILES = {"build.gradle", "build.gradle.kts"}
_SOURCE_DIRS = ("src", "lib", "app")
_README_NAMES = ("readme.md", "readme.rst", "readme.txt", "readme")


@dataclass
class ProjectEvidence:
    """Evidence collected for one candidate directory."""

    markers: list[str] = field(default_factory=list)
    score: int = 0

    def add(self, marker: str, weight: int) -> None:
        self.markers.append(marker)
        self.score += weight


def detect_evidence(path: str) -> ProjectEvidence | None:
    """Score a directory's project evidence; None when it does not exist."""
    if not os.path.isdir(path):
        return None

    evidence = ProjectEvidence()

    try:
        entries = set(os.listdir(path))
    except (PermissionError, OSError):
        return None

    # Git remains the strongest signal.
    git_marker = ".git"
    if git_marker in entries and (
        os.path.isdir(os.path.join(path, git_marker)) or os.path.isfile(os.path.join(path, git_marker))
    ):
        evidence.add(git_marker, GIT_ROOT)

    for name in entries:
        lowered = name.lower()
        weight = _MARKER_FILES.get(name)
        if weight is not None and os.path.isfile(os.path.join(path, name)):
            evidence.add(name, weight)
            continue
        if lowered.endswith(_SOLUTION_SUFFIXES) or lowered.endswith(_PROJECT_FILE_SUFFIXES):
            if os.path.isfile(os.path.join(path, name)):
                weight = SOLUTION_FILE if lowered.endswith(_SOLUTION_SUFFIXES) else CSPROJ
                evidence.add(name, weight)
                continue
        if name in _GRADLE_FILES and os.path.isfile(os.path.join(path, name)):
            evidence.add(name, BUILD_GRADLE)

    for source_dir in _SOURCE_DIRS:
        if source_dir in entries and os.path.isdir(os.path.join(path, source_dir)):
            evidence.add(f"{source_dir}/", SOURCE_DIR)

    # README-only folders are weak positive evidence.
    if not evidence.markers:
        has_readme = any(lowered in _README_NAMES for lowered in (e.lower() for e in entries))
        has_source_files = any(
            e.lower().endswith((".py", ".js", ".ts", ".go", ".rs", ".java", ".cs"))
            for e in entries
            if os.path.isfile(os.path.join(path, e))
        )
        if has_readme and has_source_files:
            evidence.add("readme+source", README_ONLY)

    return evidence


def is_project(path: str, threshold: int = DEFAULT_THRESHOLD) -> ProjectEvidence | None:
    """Return evidence when the directory qualifies as a project root."""
    evidence = detect_evidence(path)
    if evidence is None or evidence.score < threshold:
        return None
    return evidence
