"""Canonical filesystem path identity for projects.

Windows paths are case-insensitive and separator-insensitive, so
``E:\\Muninn``, ``e:\\muninn\\`` and ``E:/Muninn`` must resolve to the
same project identity. The canonical *key* is used for comparisons;
the stored ``canonical_path`` keeps the true-case resolved path for display.
"""

from __future__ import annotations

import os
from pathlib import Path


def canonical_key(path: str) -> str:
    """Return a normalized comparison key for a filesystem path.

    Resolves symlinks/junctions/short names exactly like ``true_case_path``
    so scanned paths always compare equal to stored canonical paths.
    On Windows this also lowercases and normalizes separators (normcase).
    """
    if not path:
        return ""
    expanded = os.path.expanduser(path)
    try:
        return os.path.normcase(os.path.realpath(expanded))
    except OSError:
        return os.path.normcase(os.path.abspath(expanded))


def true_case_path(path: str) -> str:
    """Best-effort resolved, true-case filesystem path for persistence."""
    try:
        return str(Path(path).expanduser().resolve())
    except OSError:
        return os.path.abspath(os.path.expanduser(path))
