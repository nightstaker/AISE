"""ProjectSession driver for waterfall_v2.

This is the c4 replacement for the hand-coded
``_build_initial_phase_prompts`` 7-phase tuple list in project_session.py.
Instead of hard-coding phase names + prompts in Python, the driver:

1. Loads ``src/aise/processes/waterfall_v2.process.md`` via c1's loader
2. Walks each phase via c3's PhaseExecutor (PRODUCE / AUTO_GATE /
   REVIEWER / DECISION state machine)
3. On producer hard fail (acceptance gate exhausted) saves halt state
   via c11 and returns; user resumes via the resume command
4. Threads observability hooks (c9) so active_tasks() reflects the
   in-flight phase + producer

c4 ships this driver alongside the legacy ``_build_initial_phase_prompts``
in project_session.py — both are valid entry points. Migration:

* New projects default to waterfall_v2 by setting
  ``project_config.process_type="waterfall_v2"``.
* Existing projects with ``process_type="waterfall"`` keep the legacy
  flow until the user opts in.

Future cleanup commit will delete ``_build_initial_phase_prompts``
once all callers (web app, CLI, tests) have migrated.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Sequence

from ..utils.logging import get_logger
from .halt_resume import (
    HaltState,
    clear_halt_state,
    is_halted,
    load_halt_state,
    remaining_phases,
    save_halt_state,
)
from .observability import get_registry
from .phase_executor import (
    PhaseExecutor,
    PhaseResult,
    PhaseStatus,
)
from .waterfall_v2_loader import (
    default_waterfall_v2_path,
    load_waterfall_v2,
)
from .waterfall_v2_models import WaterfallV2Spec

logger = get_logger(__name__)


# -- Result types ---------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    """End-to-end result of running waterfall_v2 across all phases."""

    completed_phases: tuple[str, ...] = field(default_factory=tuple)
    halted: bool = False
    halt_state: HaltState | None = None
    phase_results: tuple[PhaseResult, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        if self.halted:
            return "halted"
        return "completed"


# -- Driver ---------------------------------------------------------------


@dataclass
class WaterfallV2Driver:
    """Drive a project through waterfall_v2 phases.

    DI:
    * ``project_root: Path`` — where artifacts live
    * ``produce_fn: Callable[[role, prompt, expected], str]`` — wraps
      dispatch_task (c5) for the producer agent. Caller's responsibility
      to honor 3-retry semantics inside.
    * ``dispatch_reviewer: Callable[[role, prompt], str]`` — wraps
      dispatch_task for reviewer agents (model selected per
      agent_model_selection config; see c7).
    * ``contracts_loader: Callable[[Path], dict] | None`` — if provided,
      called with project_root to load (stack_contract, behavioral_contract,
      requirement_contract). Default uses the bundled JSON readers.
    * ``spec_path: Path | None`` — override the bundled
      waterfall_v2.process.md (tests use this).
    """

    project_root: Path
    produce_fn: Callable[[str, str, Sequence[str]], str]
    dispatch_reviewer: Callable[[str, str], str]
    contracts_loader: Callable[[Path], dict[str, Any]] | None = None
    spec_path: Path | None = None
    spec: WaterfallV2Spec | None = None  # injectable for tests

    def __post_init__(self) -> None:
        if self.spec is None:
            path = self.spec_path or default_waterfall_v2_path()
            self.spec = load_waterfall_v2(path)

    # -- Public API -------------------------------------------------------

    def run(self, requirement: str) -> RunResult:
        """Drive the full pipeline. Resumes from halt state if present."""
        assert self.spec is not None  # __post_init__ guarantees

        # Resume support (c11)
        if is_halted(self.project_root):
            existing = load_halt_state(self.project_root)
            if existing is None:
                # Halt file present but unreadable — treat as fresh run
                logger.warning("halt file present but unparseable; starting fresh")
                phases_to_run = self.spec.phases
                completed = ()
            else:
                logger.info(
                    "Resuming from halted phase: %s (%d already completed)",
                    existing.halted_at_phase,
                    len(existing.completed_phases),
                )
                phases_to_run = remaining_phases(self.spec, existing)
                completed = existing.completed_phases
                clear_halt_state(self.project_root)
        else:
            phases_to_run = self.spec.phases
            completed = ()

        contracts = self._load_contracts()

        executor = PhaseExecutor(
            spec=self.spec,
            project_root=self.project_root,
            produce_fn=self.produce_fn,
            dispatch_reviewer=self.dispatch_reviewer,
            stack_contract=contracts.get("stack_contract"),
            behavioral_contract=contracts.get("behavioral_contract"),
            requirement_contract=contracts.get("requirement_contract"),
        )

        phase_results: list[PhaseResult] = []
        for phase in phases_to_run:
            logger.info("=== Phase %s starting ===", phase.id)
            # Re-load contracts before each phase — earlier phases (esp.
            # phase 2 architecture) produce stack_contract.json /
            # behavioral_contract.json which downstream phases need.
            contracts = self._load_contracts()
            executor.stack_contract = contracts.get("stack_contract")
            executor.behavioral_contract = contracts.get("behavioral_contract")
            executor.requirement_contract = contracts.get("requirement_contract")

            result = executor.execute_phase(phase, requirement)
            phase_results.append(result)

            if result.status == PhaseStatus.FAILED:
                # Producer hard fail → save halt state and return
                halt = HaltState(
                    halted_at_phase=phase.id,
                    halt_reason="producer_acceptance_gate_exhausted",
                    halt_detail=result.failure_summary,
                    completed_phases=completed,
                    producer_attempts_used=result.producer_attempts,
                    failure_summary=result.failure_summary,
                )
                save_halt_state(self.project_root, halt)
                logger.warning(
                    "Phase %s halted; halt state saved at runs/HALTED.json",
                    phase.id,
                )
                return RunResult(
                    completed_phases=completed,
                    halted=True,
                    halt_state=halt,
                    phase_results=tuple(phase_results),
                )

            # Phase passed (or passed_with_unresolved_review): tag, advance
            completed = completed + (phase.id,)
            logger.info(
                "Phase %s done with status=%s; tag=%s",
                phase.id,
                result.status.value,
                result.phase_tag(self.spec.phase_index(phase.id) or 0),
            )

        return RunResult(
            completed_phases=completed,
            halted=False,
            phase_results=tuple(phase_results),
        )

    # -- Helpers ---------------------------------------------------------

    def _load_contracts(self) -> dict[str, Any]:
        if self.contracts_loader is not None:
            return self.contracts_loader(self.project_root)
        return _default_contracts_loader(self.project_root)


def _default_contracts_loader(project_root: Path) -> dict[str, Any]:
    """Read the three contract JSONs from docs/. Returns dict with keys
    ``stack_contract``, ``behavioral_contract``, ``requirement_contract``;
    each value is None when the file is missing or invalid."""
    out: dict[str, Any] = {
        "stack_contract": None,
        "behavioral_contract": None,
        "requirement_contract": None,
    }
    docs = project_root / "docs"
    for key, fname in (
        ("stack_contract", "stack_contract.json"),
        ("behavioral_contract", "behavioral_contract.json"),
        ("requirement_contract", "requirement_contract.json"),
    ):
        path = docs / fname
        if not path.is_file():
            continue
        try:
            out[key] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("contract load failed for %s: %s", path, exc)
    return out


# -- Observability bridge ------------------------------------------------


def make_observable_produce_fn(
    underlying: Callable[[str, str, Sequence[str]], str],
    *,
    task_id_factory: Callable[[], str] | None = None,
) -> Callable[[str, str, Sequence[str]], str]:
    """Wrap a produce_fn so each call registers a task in the observability
    registry (c9). Used by the driver to surface live state to the web UI.

    The underlying function is unchanged in behavior; the wrapper:
    * registers a task before each call
    * marks completed/failed after
    * forwards exceptions
    """
    import uuid as _uuid

    factory = task_id_factory or (lambda: _uuid.uuid4().hex[:10])
    registry = get_registry()

    def wrapped(role: str, prompt: str, expected: Sequence[str]) -> str:
        task_id = factory()
        registry.register_task(task_id, agent=role, step="produce")
        try:
            result = underlying(role, prompt, expected)
        except Exception:
            registry.mark_completed(task_id, "failed")
            raise
        registry.mark_completed(task_id, "completed")
        return result

    return wrapped
