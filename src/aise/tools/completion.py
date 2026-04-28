"""Workflow-completion tool — gated ``mark_complete``."""

from __future__ import annotations

import json
import re
from pathlib import Path

from langchain_core.tools import BaseTool, tool

from ..utils.logging import get_logger
from ._common import _now
from .context import ToolContext

logger = get_logger(__name__)


_COMPLETION_MIN_ARTIFACT_BYTES = 64

# Regex hits that indicate the report itself is announcing a partial
# delivery. PM has historically called ``mark_complete`` after a
# truncated implementation phase with text like "0/10 ❌ (dispatch
# cap hit)" — the gate refuses these so the run cannot be falsely
# closed as completed. Patterns are case-insensitive.
_COMPLETION_REPORT_REJECT_PATTERNS: tuple[str, ...] = (
    r"\bdispatch cap hit\b",
    r"\bnot implemented\b",
    r"\bcould not be processed\b",
    r"\bbefore this subsystem\b",
    r"\b0\s*/\s*\d+\b",
    r"❌",
    r"\btruncated\b",
    r"\bexhausted\b",
)


def _completion_artifact_shortfall(
    project_root: Path | None,
) -> list[str]:
    """Return component source files declared by the architect's stack
    contract that are missing or trivially small on disk.

    Used by the ``mark_complete`` gate to refuse closing a run while
    the architect's deliverables aren't fully on disk.
    """
    if project_root is None:
        return []
    contract_path = project_root / "docs" / "stack_contract.json"
    if not contract_path.is_file():
        return []
    try:
        data = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    subsystems = data.get("subsystems")
    if not isinstance(subsystems, list):
        return []

    missing: list[str] = []
    for ss in subsystems:
        if not isinstance(ss, dict):
            continue
        for comp in ss.get("components") or []:
            if not isinstance(comp, dict):
                continue
            cfile = comp.get("file")
            if not cfile:
                continue
            target = (project_root / cfile).resolve()
            try:
                size = target.stat().st_size if target.is_file() else 0
            except OSError:
                size = 0
            if size < _COMPLETION_MIN_ARTIFACT_BYTES:
                missing.append(cfile)
    return missing


def make_completion_tool(ctx: ToolContext) -> BaseTool:
    """Create the ``mark_complete`` primitive — the explicit terminal signal."""

    @tool
    def mark_complete(report: str) -> str:
        """Signal that the workflow is complete and provide the final report.

        After calling this, the orchestrator's continuation loop exits.
        Use ONCE, when all phases are done.

        The runtime gates this call: it is REJECTED when

        - every planned phase has not yet emitted ``phase_complete``,
        - the architect's stack contract declares component files that
          are missing or trivially small on disk, OR
        - the report text contains markers indicating the run was
          truncated (``"dispatch cap hit"``, ``"0/N"``, ``"❌"``, etc.)

        Rejected calls return ``status: refused`` with the missing
        artifact list so the orchestrator can dispatch the gaps and
        retry instead of silently closing a partial run.

        Args:
            report: The final delivery report (markdown text).
        """
        # Idempotency guard: if the workflow is already complete, keep
        # the first report and refuse the second call. Without this the
        # LLM sometimes calls ``mark_complete`` twice in a row, the
        # second call overwriting the first report (often with a
        # shorter / lower-quality version) and also interleaving extra
        # dispatches between the two calls.
        if ctx.workflow_state.is_complete:
            logger.info(
                "mark_complete refused: already complete (existing_len=%d new_len=%d)",
                len(ctx.workflow_state.final_report),
                len(report),
            )
            return json.dumps(
                {
                    "status": "refused",
                    "error": "Workflow is already marked complete.",
                    "existing_report_length": len(ctx.workflow_state.final_report),
                }
            )

        # Gate 1: every planned phase must have completed — except the
        # final one, since mark_complete is called from INSIDE the
        # final phase (before the orchestrator loop emits its
        # ``phase_complete`` event). The legal pattern is therefore:
        # we have a ``phase_start`` for the final index AND every
        # earlier index has a matching ``phase_complete``.
        with ctx.event_lock:
            plan_events = [e for e in ctx.event_log if e.get("type") == "phase_plan"]
            done_events = [e for e in ctx.event_log if e.get("type") == "phase_complete"]
            start_events = [e for e in ctx.event_log if e.get("type") == "phase_start"]
        planned_total = 0
        if plan_events:
            try:
                planned_total = int(plan_events[-1].get("total") or 0)
            except (TypeError, ValueError):
                planned_total = 0
        done_indices: set[int] = set()
        for ev in done_events:
            try:
                done_indices.add(int(ev.get("phase_idx")))
            except (TypeError, ValueError):
                continue
        started_indices: set[int] = set()
        for ev in start_events:
            try:
                started_indices.add(int(ev.get("phase_idx")))
            except (TypeError, ValueError):
                continue
        if planned_total:
            final_idx = planned_total - 1
            earlier_required = set(range(final_idx))
            missing_earlier = sorted(earlier_required - done_indices)
            in_final_phase = final_idx in started_indices
            if missing_earlier or not in_final_phase:
                missing_phases = sorted(earlier_required - done_indices)
                if not in_final_phase:
                    missing_phases.append(final_idx)
                logger.info(
                    "mark_complete refused: phases_done=%s started_final=%s plan_total=%d",
                    sorted(done_indices),
                    in_final_phase,
                    planned_total,
                )
                return json.dumps(
                    {
                        "status": "refused",
                        "error": (
                            f"Cannot mark complete — {len(done_indices)}/{planned_total} "
                            f"phases finished and final phase started={in_final_phase}. "
                            f"Missing phase indices: {missing_phases}. "
                            "Continue dispatching the remaining phases (main_entry / "
                            "qa_testing / delivery) before calling mark_complete again."
                        ),
                        "phases_completed": sorted(done_indices),
                        "phases_total": planned_total,
                        "missing_phase_indices": missing_phases,
                    },
                    ensure_ascii=False,
                )

        # Gate 2: every component file declared by the architect must
        # exist on disk with non-trivial content. A run that closes
        # while ``src/gameplay/*.py`` is still empty is not done.
        missing_files = _completion_artifact_shortfall(ctx.project_root)
        if missing_files:
            logger.info(
                "mark_complete refused: %d declared component files missing/empty",
                len(missing_files),
            )
            return json.dumps(
                {
                    "status": "refused",
                    "error": (
                        f"Cannot mark complete — {len(missing_files)} component "
                        "files declared in docs/stack_contract.json are missing or "
                        "trivially small on disk. Dispatch the responsible subsystem "
                        "to fill them in, then call mark_complete again."
                    ),
                    "missing_artifacts": missing_files[:50],
                    "missing_artifact_count": len(missing_files),
                },
                ensure_ascii=False,
            )

        # Gate 3: refuse reports that openly admit partial delivery.
        # PM has historically tried to close runs with text like
        # "0/10 ❌ (dispatch cap hit before this subsystem was
        # processed)" — that's a partial delivery, not a delivery.
        report_lower = (report or "").lower()
        flagged: list[str] = []
        for pattern in _COMPLETION_REPORT_REJECT_PATTERNS:
            if re.search(pattern, report_lower, flags=re.IGNORECASE):
                flagged.append(pattern)
        if flagged:
            logger.info(
                "mark_complete refused: report contains partial-delivery markers: %s",
                flagged,
            )
            return json.dumps(
                {
                    "status": "refused",
                    "error": (
                        "Cannot mark complete — the report you supplied describes a "
                        "partial delivery (matched markers: "
                        f"{flagged}). Finish the missing work and submit a report "
                        "that does not flag any subsystem as failed/truncated."
                    ),
                    "flagged_markers": flagged,
                },
                ensure_ascii=False,
            )

        ctx.workflow_state.is_complete = True
        ctx.workflow_state.final_report = report
        ctx.emit(
            {
                "type": "workflow_complete",
                "report_length": len(report),
                "timestamp": _now(),
            }
        )
        logger.info("Workflow marked complete: report=%d chars", len(report))
        return json.dumps({"status": "acknowledged", "report_length": len(report)})

    return mark_complete
