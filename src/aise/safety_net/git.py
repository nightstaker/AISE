"""VCS domain — git **and** ``.gitignore`` checks + repairs co-located.

A ``.gitignore`` only exists to feed git, and every repair in this
file talks to git via :func:`_run_git`, so detection and remediation
for the whole VCS surface live in one module. Adding a new git-touching
behaviour means editing this file and nothing else.

Registered with the safety-net registry on import:

Layer-A invariants (category ``"scaffold"``)
- ``missing_git_repo`` — project root is its own git repo
- ``missing_gitignore`` — ``.gitignore`` is present

Layer-B artifact-kind handlers
- ``git_repo`` — ``.git/`` exists at project root
- ``git_tag`` — ``rev-parse refs/tags/<tag>`` succeeds
- ``clean_tree`` — ``git status --porcelain`` is empty

Repairs
- ``missing_git_repo`` — ``git init`` + local identity
- ``missing_gitignore`` — write the bundled baseline ``.gitignore``
- ``uncommitted_changes`` — ``git add -A`` + safety-net commit
- ``missing_phase_tag`` — ``git tag <ctx['tag_name']>``
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from .registry import register_artifact_kind, register_invariant, register_repair
from .types import ExpectedArtifact

# ---------------------------------------------------------------------------
# Shared git wrapper
# ---------------------------------------------------------------------------


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command under ``cwd``. Never raises; returncode tells
    the caller what happened. Kept inline here (not imported from a
    helpers module) so the safety net's VCS surface lives in a single
    file — a teammate reading this can see every git invocation
    without chasing cross-package refs.
    """
    return subprocess.run(  # noqa: S603 — args are literal strings from our own code
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


# ---------------------------------------------------------------------------
# Layer-A invariants
# ---------------------------------------------------------------------------


@register_invariant("missing_git_repo", category="scaffold")
def _invariant_git_repo(project_root: Path) -> str | None:
    """The project must be its own git repo."""
    return None if (project_root / ".git").exists() else "missing_git_repo"


@register_invariant("missing_gitignore", category="scaffold")
def _invariant_gitignore_present(project_root: Path) -> str | None:
    """A ``.gitignore`` must be seeded so phase-end commits don't
    sweep up runtime artefacts or secrets."""
    return None if (project_root / ".gitignore").is_file() else "missing_gitignore"


# ---------------------------------------------------------------------------
# Layer-B artifact-kind handlers
# ---------------------------------------------------------------------------


@register_artifact_kind("git_repo")
def _kind_git_repo(project_root: Path, artifact: ExpectedArtifact) -> bool:  # noqa: ARG001
    return (project_root / ".git").exists()


@register_artifact_kind("git_tag")
def _kind_git_tag(project_root: Path, artifact: ExpectedArtifact) -> bool:
    if not artifact.tag_name:
        return True
    r = _run_git(project_root, "rev-parse", "--verify", f"refs/tags/{artifact.tag_name}")
    return r.returncode == 0


@register_artifact_kind("clean_tree")
def _kind_clean_tree(project_root: Path, artifact: ExpectedArtifact) -> bool:  # noqa: ARG001
    r = _run_git(project_root, "status", "--porcelain")
    return r.returncode == 0 and not (r.stdout or "").strip()


# ---------------------------------------------------------------------------
# Repairs
# ---------------------------------------------------------------------------


@register_repair("missing_git_repo")
def _repair_git_init(project_root: Path, ctx: dict[str, Any]) -> None:  # noqa: ARG001
    """The PM agent forgot to run ``git init`` — do it ourselves.

    Idempotent: if ``.git`` sneaks into existence between the check
    and the repair (a concurrent retry, say), ``git init`` is a no-op.
    Also configures a local identity so later commits don't fail on
    hosts without a global ``user.name`` / ``user.email``.
    """
    result = _run_git(project_root, "init", "--quiet")
    if result.returncode != 0:
        raise RuntimeError(f"git init failed: {(result.stderr or '').strip()[:200]}")
    _run_git(project_root, "config", "user.name", "AISE Orchestrator")
    _run_git(project_root, "config", "user.email", "orchestrator@aise.local")


@register_repair("uncommitted_changes")
def _repair_autocommit(project_root: Path, ctx: dict[str, Any]) -> None:
    """Phase ended with files sitting uncommitted — the PM agent
    forgot the end-of-phase commit ritual. Commit them ourselves with
    a subject that makes it clear this was a safety-net fallback,
    not a real agent commit.

    Context dict may carry ``step_id`` so the message ties the commit
    back to the phase that missed it.
    """
    step = str(ctx.get("step_id") or "unknown_phase").strip() or "unknown_phase"
    # Stage everything that's tracked OR untracked.
    add = _run_git(project_root, "add", "-A")
    if add.returncode != 0:
        raise RuntimeError(f"git add -A failed: {(add.stderr or '').strip()[:200]}")
    # Refuse to create an empty commit — if there's nothing to commit,
    # the earlier invariant would have passed; being here means
    # someone else committed between the check and the repair.
    diff = _run_git(project_root, "diff", "--cached", "--quiet")
    if diff.returncode == 0:
        return
    subject = f"safety_net({step}): autocommit uncommitted changes"[:72]
    commit = _run_git(project_root, "commit", "--quiet", "-m", subject)
    if commit.returncode != 0:
        raise RuntimeError(f"git commit failed: {(commit.stderr or '').strip()[:200]}")


@register_repair("missing_phase_tag")
def _repair_create_phase_tag(project_root: Path, ctx: dict[str, Any]) -> None:
    """The phase completed successfully but the PM agent didn't tag
    HEAD as ``phase_<N>_<name>``. Tag it ourselves so the next phase's
    ``git diff phase_<N>..HEAD`` has something to compare against.

    The target tag name MUST be supplied via ``ctx["tag_name"]``.
    Without it, the repair is a no-op — we won't invent a tag name
    from thin air because a wrong tag would break all future diffs.
    """
    tag = str(ctx.get("tag_name") or "").strip()
    if not tag:
        return
    # ``git tag`` refuses to recreate an existing tag; idempotent
    # behavior is OK because the caller runs the check FIRST and only
    # invokes repair if the tag was missing.
    result = _run_git(project_root, "tag", tag)
    if result.returncode != 0:
        # Collapse "already exists" into a no-op — a concurrent run
        # might have created the tag between check and repair.
        stderr = (result.stderr or "").lower()
        if "already exists" in stderr:
            return
        raise RuntimeError(f"git tag {tag} failed: {stderr[:200]}")


# ---------------------------------------------------------------------------
# .gitignore baseline (kept inline so the seed repair is self-contained;
# the runtime safety net must keep working even if a separate constants
# module fails to import).
# ---------------------------------------------------------------------------

# Secret patterns are deliberate: if the PM agent forgot to write a
# ``.gitignore`` at all, a plain baseline that didn't exclude keys /
# credentials would be worse than no gitignore, because then the
# phase-end autocommit would happily capture whatever was lying
# around.
_BASELINE_GITIGNORE = """\
# AISE runtime artefacts
runs/trace/
runs/plans/
analytics_events.jsonl
trace/safety_net_events.jsonl

# Python
__pycache__/
*.pyc
*.pyo
*.pyd
.pytest_cache/
.coverage
coverage.xml
htmlcov/
.mypy_cache/
.ruff_cache/

# Node / JS
node_modules/
dist/
build/

# OS / IDE
.DS_Store
.vscode/
.idea/

# Secrets / credentials — never commit these
.env
.env.*
*.pem
*.key
*_secret*
*credentials*
"""


@register_repair("missing_gitignore")
def _repair_seed_gitignore(project_root: Path, ctx: dict[str, Any]) -> None:  # noqa: ARG001
    """Write the baseline ``.gitignore`` the PM agent should have
    written. Refuses to overwrite an existing file — if one is there
    it's either the agent's tuned version or a user's manual edit,
    and we'd rather let the layer-A check pass empty-content next
    time than silently clobber."""
    gi = project_root / ".gitignore"
    if gi.exists():
        return
    gi.write_text(_BASELINE_GITIGNORE, encoding="utf-8")
