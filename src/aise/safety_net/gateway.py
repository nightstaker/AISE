"""Gateway — the single entry point that routes through the registry.

External callers never poke at the registries directly. They call
``run_post_step_check(project_root, ...)`` and the gateway dispatches:

1. For each Layer-B ``ExpectedArtifact``: look up the registered kind
   handler, check the artifact, and on miss look up the registered
   repair via the artifact-repair policy.
2. For Layer-A: iterate the registered invariants for the requested
   category and run the matching repair on each miss.

Every miss + repair is recorded as a structured event via
``events._emit_event`` so the dashboard (issue #122) can surface
LLM-capability drift over time.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger
from .events import _emit_event, _make_event
from .registry import (
    get_artifact_kind_handler,
    get_repair,
    layer_a_invariants,
    repair_for_artifact,
)
from .types import CheckOutcome, ExpectedArtifact

logger = get_logger(__name__)


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
        layer_a_category: Category key for Layer-A invariants. Empty
            means "skip layer A"; pass ``"scaffold"`` for scaffolding
            steps.
        repair_context: Extra context forwarded to repair actions
            (e.g. ``{"tag_name": "phase_2_architecture"}`` for the
            phase-tag repair).

    Returns:
        A :class:`CheckOutcome` summarizing what was missing, what
        got repaired, and how many telemetry events were emitted.
    """
    # Force registry side-effects to fire before we route anything.
    # Each domain module decorates its check/repair functions on
    # import; the package's ``__init__`` already imported them, so
    # re-importing is a no-op thanks to Python's module cache. The
    # legacy ``checks`` / ``repairs`` package layout was flattened
    # into the per-domain modules (filesystem, git, stack_contract,
    # entry_point, ui_smoke) — we no longer need the unused stubs.
    from . import filesystem as _filesystem  # noqa: F401
    from . import git as _git  # noqa: F401
    from . import stack_contract as _stack_contract  # noqa: F401

    outcome = CheckOutcome(step_id=step_id)
    repair_ctx = {"step_id": step_id, **(repair_context or {})}

    expected_list = list(layer_b_expected)

    # -- Layer B ------------------------------------------------------------
    for artifact in expected_list:
        try:
            present = _check_artifact(project_root, artifact)
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("safety_net: layer-B check raised for %s: %s", artifact, exc)
            present = True  # don't penalize the step for our bug
        if present:
            continue
        outcome.layer_b_missing.append(artifact)
        repair_key = repair_for_artifact(artifact)
        # Per-artifact repair context: must_not_exist needs the path
        # to delete; git_tag needs the tag name; others use the shared
        # repair_ctx unchanged.
        per_artifact_ctx = dict(repair_ctx)
        if artifact.kind == "must_not_exist":
            per_artifact_ctx["path"] = artifact.path
        _run_repair(project_root, repair_key, artifact.describe(), "B", outcome, per_artifact_ctx)

    # -- Layer A ------------------------------------------------------------
    # Only run layer A if layer B passed (or had nothing to check).
    # The rationale: if B already caught something and we've kicked off
    # repairs, layer A's invariants are likely to trigger on the same
    # root cause — better to let the caller re-run the check after B's
    # repairs land, rather than double-reporting.
    b_clean = not outcome.layer_b_missing
    if b_clean and layer_a_category:
        for invariant in layer_a_invariants(layer_a_category):
            try:
                miss_key = invariant.fn(project_root)
            except Exception as exc:  # pragma: no cover — defensive
                logger.warning("safety_net: layer-A invariant %s raised: %s", invariant.name, exc)
                miss_key = None
            if miss_key is None:
                continue
            outcome.layer_a_failures.append(miss_key)
            _run_repair(project_root, miss_key, miss_key, "A", outcome, repair_ctx)

    return outcome


def _check_artifact(project_root: Path, artifact: ExpectedArtifact) -> bool:
    """Resolve and invoke the registered handler for ``artifact.kind``.

    Unknown ``kind`` values are treated as satisfied (we don't fail an
    unknown expectation — callers owe us a meaningful schema, and a
    typo would otherwise manifest as a permanent "missing"). A log
    line flags the unknown kind so the caller can fix it.
    """
    handler = get_artifact_kind_handler(artifact.kind)
    if handler is None:
        logger.warning("safety_net: unknown ExpectedArtifact kind %r (treated as satisfied)", artifact.kind)
        return True
    return handler(project_root, artifact)


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
    repair_fn = get_repair(repair_key)
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
