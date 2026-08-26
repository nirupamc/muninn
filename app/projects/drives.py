"""Drive discovery — enumerate local filesystem volumes.

Windows is the currently verified platform (logical drives via the Win32
API). Other platforms fall back to common mount roots; that path is NOT
claimed as verified.
"""

from __future__ import annotations

import ctypes
import logging
import os
import string
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum

logger = logging.getLogger("munin.projects.drives")


class DriveType(str, Enum):
    """Physical/volume classification for a discovered drive."""

    fixed = "FIXED"
    removable = "REMOVABLE"
    network = "NETWORK"
    cdrom = "CDROM"
    ramdisk = "RAMDISK"
    unknown = "UNKNOWN"


@dataclass
class DiscoveredDrive:
    """A single enumerated drive/volume with scan eligibility."""

    root_path: str
    drive_type: DriveType
    accessible: bool
    enabled_for_scan: bool
    skip_reason: str | None = None
    last_scanned_at: datetime | None = field(default=None)

    def to_dict(self) -> dict[str, object]:
        return {
            "root_path": self.root_path,
            "drive_type": self.drive_type.value,
            "accessible": self.accessible,
            "enabled_for_scan": self.enabled_for_scan,
            "skip_reason": self.skip_reason,
            "last_scanned_at": self.last_scanned_at.isoformat() if self.last_scanned_at else None,
        }


# Win32 GetDriveTypeW return codes.
_DRIVE_TYPE_CODES: dict[int, DriveType] = {
    2: DriveType.removable,
    3: DriveType.fixed,
    4: DriveType.network,
    5: DriveType.cdrom,
    6: DriveType.ramdisk,
}

Enumerator = type(lambda: [])


def _windows_logical_drives() -> list[tuple[str, int]]:
    """Return (root_path, raw_drive_type) tuples for all logical drives."""
    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    mask = kernel32.GetLogicalDrives()
    results: list[tuple[str, int]] = []
    for index, letter in enumerate(string.ascii_uppercase):
        if not mask or not (mask >> index) & 1:
            continue
        root = f"{letter}:\\"
        raw_type = kernel32.GetDriveTypeW(ctypes.c_wchar_p(root))
        results.append((root, raw_type))
    return results


def _posix_mount_roots() -> list[tuple[str, int]]:
    """Fallback mount-root enumeration for non-Windows platforms.

    NOTE: not verified against real macOS/Linux workstations; kept simple.
    """
    candidates = ["/", "/home", "/Users", "/media", "/mnt"]
    return [(c, 3 if c in ("/", "/home", "/Users") else 0) for c in candidates if os.path.isdir(c)]


def _platform_enumerator() -> list[tuple[str, int]]:
    if sys.platform == "win32":
        return _windows_logical_drives()
    return _posix_mount_roots()


def _is_accessible(root: str) -> bool:
    try:
        return os.path.exists(root) and os.listdir(root) is not None
    except (PermissionError, OSError):
        return False


class DriveDiscoveryService:
    """Enumerates available drives and decides which are eligible for scanning."""

    def __init__(self, enumerator=None) -> None:
        # Enumerator injectable for tests; default is platform-specific.
        self._enumerator = enumerator or _platform_enumerator

    def list_drives(
        self,
        *,
        include_fixed: bool = True,
        include_removable: bool = False,
        include_network: bool = False,
        excluded_roots: set[str] | None = None,
        last_scanned: dict[str, datetime] | None = None,
    ) -> list[DiscoveredDrive]:
        """Enumerate drives with eligibility decisions applied."""
        excluded = {canonical_root(r) for r in (excluded_roots or set())}
        scanned_map = last_scanned or {}
        drives: list[DiscoveredDrive] = []
        seen: set[str] = set()

        for raw_root, raw_type in sorted(self._enumerator(), key=lambda item: item[0]):
            root = canonical_root(raw_root)
            if root in seen:
                continue
            seen.add(root)
            drive_type = _DRIVE_TYPE_CODES.get(raw_type, DriveType.unknown)
            accessible = _is_accessible(raw_root)

            enabled = True
            reason: str | None = None
            if root in excluded:
                enabled = False
                reason = "excluded by configuration"
            elif not accessible:
                enabled = False
                reason = "not accessible"
            elif drive_type == DriveType.fixed and not include_fixed:
                enabled = False
                reason = "fixed-drive scanning disabled"
            elif drive_type == DriveType.removable and not include_removable:
                enabled = False
                reason = "removable-drive scanning disabled"
            elif drive_type == DriveType.network and not include_network:
                enabled = False
                reason = "network-drive scanning disabled"
            elif drive_type in (DriveType.cdrom,):
                enabled = False
                reason = "optical media ignored"

            drives.append(
                DiscoveredDrive(
                    root_path=raw_root,
                    drive_type=drive_type,
                    accessible=accessible,
                    enabled_for_scan=enabled,
                    skip_reason=reason,
                    last_scanned_at=scanned_map.get(root),
                )
            )
        return drives


def canonical_root(root: str) -> str:
    """Normalize a drive/root path for comparisons."""
    normalized = os.path.normcase(os.path.normpath(root))
    # Keep the trailing separator for bare drive roots ("e:\") so they are
    # unambiguous; other paths keep their normal form.
    if sys.platform == "win32" and len(normalized) == 2 and normalized[1] == ":":
        normalized += "\\"
    return normalized
