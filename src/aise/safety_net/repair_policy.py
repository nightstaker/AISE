"""Default policy that maps an ExpectedArtifact to a repair name.

This is the only place that knows the relationship between a missing
artifact's *kind* (and sometimes *path*) and the named repair that
heals it. Adding a new domain means appending one branch here plus
adding a check + repair in the new domain module — no other call site
changes.
"""

from __future__ import annotations

from .registry import register_artifact_repair_policy
from .types import ExpectedArtifact

_STANDARD_SUBDIRS = frozenset({"docs", "src", "tests", "scripts", "config", "artifacts", "trace"})


@register_artifact_repair_policy
def _default_policy(artifact: ExpectedArtifact) -> str | None:
    """Return the canonical repair name for ``artifact`` (or ``None``)."""
    if artifact.kind == "git_repo":
        return "missing_git_repo"
    if artifact.kind == "file" and artifact.path == ".gitignore":
        return "missing_gitignore"
    if artifact.kind == "dir" and artifact.path in _STANDARD_SUBDIRS:
        return "missing_standard_subdirs"
    if artifact.kind == "clean_tree":
        return "uncommitted_changes"
    if artifact.kind == "git_tag":
        return "missing_phase_tag"
    if artifact.kind == "must_not_exist":
        return "leftover_file"
    if artifact.kind == "json_file":
        return "missing_or_invalid_json"
    if artifact.kind == "stack_contract":
        return "missing_or_invalid_stack_contract"
    return None
