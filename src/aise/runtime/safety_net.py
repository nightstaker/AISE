"""Safety net that verifies and repairs LLM-driven step outputs.

PR-b handed scaffolding and per-phase operations to the product-manager
agent. This module closes the loop: after each step the safety net
checks that what the LLM *claimed* to do actually landed on disk, and
if not, runs a mechanical repair action so the project doesn't enter
an unrecoverable state.

Two layers of checks, applied in order:

1. **Layer B** — plan-declared ``expected_artifacts``. The caller
   passes a list of ``ExpectedArtifact`` objects describing what the
   step *should* have produced. B is the "official contract"
   assertion: it lets process.md templates and agent skills declare
   their post-conditions and catch violations directly.

2. **Layer A** — hardcoded invariants. If layer B passes (or the
   caller didn't supply any B expectations), a second pass runs
   conservative invariants that guard the project's structural
   integrity — is it still a git repo? is the working tree clean
   after a phase that wrote files? — to catch drift that the caller
   didn't explicitly declare. A is also load-bearing for legacy
   callers that haven't written a B contract yet.

Every detected miss produces:

- A structured event appended to ``<project_root>/trace/safety_net_events.jsonl``
  — this doubles as telemetry to measure LLM-capability over time
  (see issue #122 for the follow-up dashboard).
- A repair action, dispatched through the :data:`REPAIR_ACTIONS`
  registry. Repairs are best-effort; failures are captured on the
  outcome dict and also emitted as events.

The module never raises — a broken safety net must not block a run.
Errors are captured as ``repair_status="error"`` events and surfaced
on the ``CheckOutcome`` return value. Callers decide whether to
flip ``ProjectStatus.SCAFFOLDING_FAILED`` (scaffolding path) or just
log a warning (per-phase path, where the agent may recover).
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger

logger = get_logger(__name__)


# Baseline ``.gitignore`` seeded by the ``missing_gitignore`` repair
# action. Kept here (not imported from some other module) so the safety
# net is self-contained — a teammate reading this file can reproduce
# what the repair does without chasing cross-package refs.
#
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


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ExpectedArtifact:
    """A single layer-B expectation for a step's output.

    ``kind`` values:
    - ``"dir"`` — ``path`` must be a directory (exists + is_dir).
    - ``"file"`` — ``path`` must be a regular file; if ``non_empty`` is
      true, also requires size > 0.
    - ``"git_repo"`` — ``path`` must contain a ``.git`` entry (dir or
      worktree reference); other fields ignored.
    - ``"git_tag"`` — ``tag_name`` (required) must be present in the
      repo at ``path``.
    - ``"clean_tree"`` — ``git status --porcelain`` at ``path`` must
      be empty (useful after a phase that should have committed
      everything it wrote).

    ``path`` is relative to the project root. Use ``"."`` for
    project-root-level checks.
    """

    path: str
    kind: str
    tag_name: str | None = None
    non_empty: bool = False
    description: str = ""

    def describe(self) -> str:
        """Human-readable identifier used in telemetry events."""
        if self.kind == "git_tag":
            return f"git_tag:{self.tag_name}"
        if self.kind == "clean_tree":
            return "clean_tree"
        if self.kind == "git_repo":
            return "git_repo"
        return f"{self.kind}:{self.path}"


@dataclass
class CheckOutcome:
    """Aggregated result of a single post-step check + repair pass."""

    step_id: str
    layer_b_missing: list[ExpectedArtifact] = field(default_factory=list)
    layer_a_failures: list[str] = field(default_factory=list)
    repairs_attempted: list[str] = field(default_factory=list)
    repairs_succeeded: list[str] = field(default_factory=list)
    repairs_failed: list[tuple[str, str]] = field(default_factory=list)
    events_emitted: int = 0

    @property
    def repaired_ok(self) -> bool:
        """True when the step ultimately landed in a good state.

        Either nothing was missing, or everything that was missing got
        repaired successfully. A caller that wants "all green" as a
        gate should check this flag.
        """
        return not self.layer_a_failures and not self.repairs_failed


# ---------------------------------------------------------------------------
# Repair actions
# ---------------------------------------------------------------------------


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """Run a git command under ``cwd``. Never raises; returncode tells
    the caller what happened. Kept small and duplicated from PR-b's
    ``web/app.py`` helper rather than cross-importing, because the
    safety net has to keep working even if the web package failed to
    import.
    """
    return subprocess.run(  # noqa: S603 — args are literal strings from our own code
        ["git", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


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


def _repair_create_standard_subdirs(project_root: Path, ctx: dict[str, Any]) -> None:  # noqa: ARG001
    """Create the seven standard subdirs when the PM agent skipped
    them. Cheap, idempotent — ``mkdir(exist_ok=True)`` on a full set
    is a no-op if they're already there."""
    for subdir in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace"):
        (project_root / subdir).mkdir(parents=True, exist_ok=True)


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


REPAIR_ACTIONS: dict[str, Callable[[Path, dict[str, Any]], None]] = {
    "missing_git_repo": _repair_git_init,
    "missing_gitignore": _repair_seed_gitignore,
    "missing_standard_subdirs": _repair_create_standard_subdirs,
    "uncommitted_changes": _repair_autocommit,
    "missing_phase_tag": _repair_create_phase_tag,
}


# ---------------------------------------------------------------------------
# Layer A invariants
# ---------------------------------------------------------------------------


def _invariant_git_repo(project_root: Path) -> str | None:
    """The project must be its own git repo."""
    return None if (project_root / ".git").exists() else "missing_git_repo"


def _invariant_gitignore_present(project_root: Path) -> str | None:
    """A ``.gitignore`` must be seeded so phase-end commits don't
    sweep up runtime artefacts or secrets."""
    return None if (project_root / ".gitignore").is_file() else "missing_gitignore"


def _invariant_standard_subdirs(project_root: Path) -> str | None:
    """All seven standard subdirs must exist. The PM agent creates
    them during SCAFFOLDING; the safety net recreates them if they
    don't."""
    missing = [
        name
        for name in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace")
        if not (project_root / name).is_dir()
    ]
    return "missing_standard_subdirs" if missing else None


# Invariant sets keyed by step category. Callers pick the set that
# matches the step they just ran. ``None`` means "no layer-A checks
# declared for this category" — layer B is authoritative and A skips.
LAYER_A_INVARIANTS: dict[str, list[Callable[[Path], str | None]]] = {
    "scaffold": [
        _invariant_git_repo,
        _invariant_gitignore_present,
        _invariant_standard_subdirs,
    ],
    # Phase-level invariants intentionally live under callers that
    # know the phase tag name; add them here as hardcoded patterns
    # emerge.
    "phase": [],
}


# ---------------------------------------------------------------------------
# Layer B evaluation
# ---------------------------------------------------------------------------


def _artifact_present(project_root: Path, artifact: ExpectedArtifact) -> bool:
    """Return ``True`` when ``artifact`` is satisfied on disk.

    Unknown ``kind`` values are treated as satisfied (we don't fail
    an unknown expectation — callers owe us a meaningful schema, and
    a typo would otherwise manifest as a permanent "missing"). A log
    line flags the unknown kind so the caller can fix it.
    """
    target = (project_root / artifact.path).resolve() if artifact.path != "." else project_root.resolve()
    if artifact.kind == "dir":
        return target.is_dir()
    if artifact.kind == "file":
        if not target.is_file():
            return False
        if artifact.non_empty and target.stat().st_size == 0:
            return False
        return True
    if artifact.kind == "git_repo":
        return (project_root / ".git").exists()
    if artifact.kind == "git_tag":
        if not artifact.tag_name:
            return True
        r = _run_git(project_root, "rev-parse", "--verify", f"refs/tags/{artifact.tag_name}")
        return r.returncode == 0
    if artifact.kind == "clean_tree":
        r = _run_git(project_root, "status", "--porcelain")
        return r.returncode == 0 and not (r.stdout or "").strip()
    logger.warning("safety_net: unknown ExpectedArtifact kind %r (treated as satisfied)", artifact.kind)
    return True


def _repair_action_for_artifact(artifact: ExpectedArtifact) -> str | None:
    """Map a missing layer-B artifact to a repair action key.

    Returns ``None`` when no registered repair matches — the miss is
    still reported as an event, but the caller gets no mechanical
    recovery. Callers that want custom repair should extend
    :data:`REPAIR_ACTIONS` and this mapping.
    """
    if artifact.kind == "git_repo":
        return "missing_git_repo"
    if artifact.kind == "file" and artifact.path == ".gitignore":
        return "missing_gitignore"
    if artifact.kind == "dir" and artifact.path in {
        "docs",
        "src",
        "tests",
        "scripts",
        "config",
        "artifacts",
        "trace",
    }:
        return "missing_standard_subdirs"
    if artifact.kind == "clean_tree":
        return "uncommitted_changes"
    if artifact.kind == "git_tag":
        return "missing_phase_tag"
    return None


# ---------------------------------------------------------------------------
# Analytics event emission
# ---------------------------------------------------------------------------


def _events_path(project_root: Path) -> Path:
    """Where the structured events land. ``trace/`` is already on the
    baseline ``.gitignore`` so events stay out of commits by default.
    """
    return project_root / "trace" / "safety_net_events.jsonl"


def _emit_event(project_root: Path, payload: dict[str, Any]) -> bool:
    """Append a JSON event to the project's safety-net log. Returns
    ``True`` if the line was written, ``False`` on any IO error. Errors
    are logged but not raised — the safety net must not block on
    telemetry."""
    path = _events_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False))
            fp.write("\n")
        return True
    except OSError as exc:
        logger.warning("safety_net: failed to emit event: path=%s err=%s", path, exc)
        return False


def _make_event(
    *,
    step_id: str,
    layer: str,
    expected: str,
    actual: str,
    repair_action: str,
    repair_status: str,
    detail: str = "",
) -> dict[str, Any]:
    """Build the canonical telemetry event. Schema is stable; the
    dashboard (issue #122) parses these as-is."""
    return {
        "event_type": "llm_fallback_triggered",
        "step_id": step_id,
        "layer": layer,
        "expected": expected,
        "actual": actual,
        "repair_action": repair_action,
        "repair_status": repair_status,
        "detail": detail[:500] if detail else "",
        "ts": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_post_step_check(
    project_root: Path,
    *,
    step_id: str,
    layer_b_expected: Iterable[ExpectedArtifact] = (),
    layer_a_category: str = "",
    repair_context: dict[str, Any] | None = None,
) -> CheckOutcome:
    """Check (and repair) a step's output. Never raises.

    Arguments:
        project_root: Directory the step was supposed to modify.
        step_id: Stable identifier for this step (``"scaffold"``,
            ``"phase_2_architecture"``, etc.). Lands in the event
            log as the grouping key for per-step telemetry.
        layer_b_expected: Plan-declared expectations. Empty is fine —
            layer A still runs.
        layer_a_category: Key into :data:`LAYER_A_INVARIANTS`. Empty
            means "skip layer A"; pass ``"scaffold"`` for scaffolding
            steps.
        repair_context: Extra context forwarded to repair actions
            (e.g. ``{"tag_name": "phase_2_architecture"}`` for the
            phase-tag repair).

    Returns:
        A :class:`CheckOutcome` summarizing what was missing, what
        got repaired, and how many telemetry events were emitted.
    """
    outcome = CheckOutcome(step_id=step_id)
    repair_ctx = {"step_id": step_id, **(repair_context or {})}

    expected_list = list(layer_b_expected)

    # -- Layer B ------------------------------------------------------------
    for artifact in expected_list:
        try:
            present = _artifact_present(project_root, artifact)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("safety_net: layer-B check raised for %s: %s", artifact, exc)
            present = True  # don't penalize the step for our bug
        if present:
            continue
        outcome.layer_b_missing.append(artifact)
        repair_key = _repair_action_for_artifact(artifact)
        _run_repair(project_root, repair_key, artifact.describe(), "B", outcome, repair_ctx)

    # -- Layer A ------------------------------------------------------------
    # Only run layer A if layer B passed (or had nothing to check).
    # The rationale: if B already caught something and we've kicked off
    # repairs, layer A's invariants are likely to trigger on the same
    # root cause — better to let the caller re-run the check after B's
    # repairs land, rather than double-reporting.
    b_clean = not outcome.layer_b_missing
    if b_clean and layer_a_category:
        for check in LAYER_A_INVARIANTS.get(layer_a_category, []):
            try:
                miss_key = check(project_root)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("safety_net: layer-A invariant %s raised: %s", check.__name__, exc)
                miss_key = None
            if miss_key is None:
                continue
            outcome.layer_a_failures.append(miss_key)
            _run_repair(project_root, miss_key, miss_key, "A", outcome, repair_ctx)

    return outcome


def _run_repair(
    project_root: Path,
    repair_key: str | None,
    expected_desc: str,
    layer: str,
    outcome: CheckOutcome,
    ctx: dict[str, Any],
) -> None:
    """Dispatch a repair action and record the outcome + emit an event.

    Factored out so layer B and layer A share the same repair flow —
    same event shape, same success / failure bookkeeping.
    """
    repair_fn = REPAIR_ACTIONS.get(repair_key or "")
    if repair_fn is None:
        # No mechanical repair known for this miss. Still emit the
        # telemetry event so the dashboard can surface unhandled
        # failure modes.
        if _emit_event(
            project_root,
            _make_event(
                step_id=outcome.step_id,
                layer=layer,
                expected=expected_desc,
                actual="missing",
                repair_action="none",
                repair_status="skipped",
            ),
        ):
            outcome.events_emitted += 1
        return

    outcome.repairs_attempted.append(repair_key)
    try:
        repair_fn(project_root, ctx)
    except Exception as exc:
        outcome.repairs_failed.append((repair_key, str(exc)))
        if _emit_event(
            project_root,
            _make_event(
                step_id=outcome.step_id,
                layer=layer,
                expected=expected_desc,
                actual="missing",
                repair_action=repair_key,
                repair_status="failed",
                detail=str(exc),
            ),
        ):
            outcome.events_emitted += 1
        return

    outcome.repairs_succeeded.append(repair_key)
    if _emit_event(
        project_root,
        _make_event(
            step_id=outcome.step_id,
            layer=layer,
            expected=expected_desc,
            actual="repaired",
            repair_action=repair_key,
            repair_status="success",
        ),
    ):
        outcome.events_emitted += 1


# ---------------------------------------------------------------------------
# Pre-baked expectation sets
# ---------------------------------------------------------------------------


def scaffolding_expectations() -> tuple[ExpectedArtifact, ...]:
    """The layer-B expectations the PM agent's SCAFFOLDING TASK claims
    to satisfy. Exposed as a free function so callers in
    ``web/app.py`` can wire it without duplicating the list.
    """
    return (
        ExpectedArtifact(path=".", kind="git_repo", description="project root initialized as git repo"),
        ExpectedArtifact(path=".gitignore", kind="file", non_empty=True, description="baseline .gitignore seeded"),
        ExpectedArtifact(path="docs", kind="dir"),
        ExpectedArtifact(path="src", kind="dir"),
        ExpectedArtifact(path="tests", kind="dir"),
        ExpectedArtifact(path="scripts", kind="dir"),
        ExpectedArtifact(path="config", kind="dir"),
        ExpectedArtifact(path="artifacts", kind="dir"),
        ExpectedArtifact(path="trace", kind="dir"),
    )
