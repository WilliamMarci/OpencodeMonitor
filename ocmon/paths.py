"""Locate opencode's data directory (database + auth.json)."""

from __future__ import annotations

import os
from pathlib import Path


def data_dirs() -> list[Path]:
    """Candidate opencode data directories, most likely first."""
    dirs: list[Path] = []

    override = os.environ.get("OPENCODE_DATA_DIR")
    if override:
        dirs.append(Path(override).expanduser())

    if os.name == "nt":
        for var in ("LOCALAPPDATA", "APPDATA"):
            base = os.environ.get(var)
            if base:
                dirs.append(Path(base) / "opencode")
    else:
        xdg = os.environ.get("XDG_DATA_HOME")
        if xdg:
            dirs.append(Path(xdg).expanduser() / "opencode")
        dirs.append(Path.home() / ".local" / "share" / "opencode")
        dirs.append(Path.home() / "Library" / "Application Support" / "opencode")

    seen: set[Path] = set()
    unique: list[Path] = []
    for d in dirs:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


def find_database() -> Path | None:
    for d in data_dirs():
        candidate = d / "opencode.db"
        if candidate.is_file():
            return candidate
    return None


def find_auth_file() -> Path | None:
    for d in data_dirs():
        candidate = d / "auth.json"
        if candidate.is_file():
            return candidate
    return None
