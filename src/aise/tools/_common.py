"""Shared helpers used by multiple tool modules."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_processes_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "processes"
