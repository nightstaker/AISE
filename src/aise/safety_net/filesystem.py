"""Plain-filesystem domain — checks + repairs for the standard
project layout and generic file/directory expectations.

Registered with the safety-net registry on import:

Layer-A invariant (category ``"scaffold"``)
- ``missing_standard_subdirs`` — the seven baseline subdirs all exist

Layer-B artifact-kind handlers
- ``dir`` — path is a directory
- ``file`` — path is a regular file (optionally non-empty)
- ``json_file`` — path is a regular file containing valid JSON
- ``must_not_exist`` — inverted check, path must NOT exist

Repairs
- ``missing_standard_subdirs`` — ``mkdir -p`` the seven baseline dirs
- ``leftover_file`` — delete a stale path from a prior run
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger
from .registry import register_artifact_kind, register_invariant, register_repair
from .types import ExpectedArtifact

logger = get_logger(__name__)

# Standard subdirs every scaffold must produce. Single source of
# truth used by both the invariant and its repair.
_STANDARD_SUBDIRS: tuple[str, ...] = ("docs", "src", "tests", "scripts", "config", "artifacts", "trace")


def _resolve(project_root: Path, artifact: ExpectedArtifact) -> Path:
    return (project_root / artifact.path).resolve() if artifact.path != "." else project_root.resolve()


# ---------------------------------------------------------------------------
# Layer-A invariant
# ---------------------------------------------------------------------------


@register_invariant("missing_standard_subdirs", category="scaffold")
def _invariant_standard_subdirs(project_root: Path) -> str | None:
    """All seven standard subdirs must exist. The PM agent creates
    them during SCAFFOLDING; the safety net recreates them if they
    don't."""
    missing = [name for name in _STANDARD_SUBDIRS if not (project_root / name).is_dir()]
    return "missing_standard_subdirs" if missing else None


# ---------------------------------------------------------------------------
# Layer-B artifact-kind handlers
# ---------------------------------------------------------------------------


@register_artifact_kind("dir")
def _kind_dir(project_root: Path, artifact: ExpectedArtifact) -> bool:
    return _resolve(project_root, artifact).is_dir()


@register_artifact_kind("file")
def _kind_file(project_root: Path, artifact: ExpectedArtifact) -> bool:
    target = _resolve(project_root, artifact)
    if not target.is_file():
        return False
    if artifact.non_empty and target.stat().st_size == 0:
        return False
    return True


@register_artifact_kind("json_file")
def _kind_json_file(project_root: Path, artifact: ExpectedArtifact) -> bool:
    target = _resolve(project_root, artifact)
    if not target.is_file():
        return False
    if artifact.non_empty and target.stat().st_size == 0:
        return False
    try:
        _json.loads(target.read_text(encoding="utf-8"))
    except Exception:
        return False
    return True


@register_artifact_kind("must_not_exist")
def _kind_must_not_exist(project_root: Path, artifact: ExpectedArtifact) -> bool:
    """Inverted check: present means FAIL. Catches leftover files
    from earlier runs (e.g. stale package.json / node_modules from
    a prior project that never got cleaned up)."""
    return not _resolve(project_root, artifact).exists()


# ---------------------------------------------------------------------------
# Repairs
# ---------------------------------------------------------------------------


@register_repair("missing_standard_subdirs")
def _repair_create_standard_subdirs(project_root: Path, ctx: dict[str, Any]) -> None:  # noqa: ARG001
    """Create the seven standard subdirs when the PM agent skipped
    them. Cheap, idempotent — ``mkdir(exist_ok=True)`` on a full set
    is a no-op if they're already there."""
    for subdir in _STANDARD_SUBDIRS:
        (project_root / subdir).mkdir(parents=True, exist_ok=True)


@register_repair("leftover_file")
def _repair_remove_leftover(project_root: Path, ctx: dict[str, Any]) -> None:
    """Delete a leftover file that the ``must_not_exist`` check flagged.

    A previous run (typically a project that was scaffolded with a
    different stack — e.g. Phaser ``package.json`` — and never
    cleaned) left a file at ``ctx["path"]``. We remove it so the new
    run can scaffold its own version freely. ``ctx["path"]`` MUST be
    a project-relative path; absolute paths are rejected as a safety
    measure to prevent accidental host-filesystem deletion.
    """
    rel = str(ctx.get("path") or "").strip()
    if not rel:
        return
    if rel.startswith("/") or ".." in rel.split("/"):
        logger.warning(
            "safety_net: refusing to remove leftover file with unsafe path %r",
            rel,
        )
        return
    target = (project_root / rel).resolve()
    try:
        target.relative_to(project_root.resolve())
    except ValueError:
        logger.warning(
            "safety_net: refusing to remove leftover file outside project root: %s",
            target,
        )
        return
    if not target.exists():
        return
    if target.is_file() or target.is_symlink():
        target.unlink()
    elif target.is_dir():
        import shutil

        shutil.rmtree(target)
    logger.info("safety_net: removed leftover %s", target)
