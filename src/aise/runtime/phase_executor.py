"""PhaseExecutor — drives one phase through the PRODUCE / AUTO_GATE /
REVIEWER / DECISION state machine declared in
``waterfall_v2.process.md``.

Inputs (DI'd into ``PhaseExecutor.__init__``):
* ``spec: WaterfallV2Spec`` — parsed process.md (c1 loader)
* ``project_root: Path`` — where deliverables live
* ``produce_fn: Callable[[PhaseSpec, str], str]`` — caller dispatches
  the producer with the given prompt and returns the producer's text
  output. Caller wraps dispatch_task (c5) so per-task retry semantics
  are honored.
* ``dispatch_reviewer: Callable[[str, str], str]`` — caller's
  reviewer dispatcher (used by reviewer.run_review_loop, c7)
* ``concurrent_runner: ConcurrentRunner`` — see below; encapsulates
  c6's run_parallel/run_grouped/run_dag for the fanout case.

Per-phase flow:

    1. PRODUCE
       - If phase has fanout: enumerate fanout tasks (from
         stack_contract / behavioral_contract / etc.) and run them via
         ConcurrentExecutor with ALL_PASS.
         - Stage failure (any sub-task fails after its 3 retries)
           → PHASE_FAILED → halt.
       - If phase is single-writer: call produce_fn once with the
         producer prompt.
    2. AUTO_GATE
       - For every deliverable in spec, materialize PredicateContext
         and run evaluate_deliverable (c2). Aggregate.
       - If any deliverable fails AUTO_GATE: hand the failure summary
         to the producer as feedback and re-PRODUCE.
       - If after 3 producer retries AUTO_GATE still fails:
         PHASE_FAILED → halt.
    3. REVIEWER_GATE
       - If phase has reviewer: run reviewer.run_review_loop with the
         phase's revise_budget (default 3) and the configured
         consensus (ALL_PASS only is supported for now).
       - Reviewer feedback is prepended to producer prompt on revise
         (Decision 2).
       - On revise budget exhaustion: phase advances with
         ``passed_with_unresolved_review=True`` per Decision 1
         (continue_with_marker).
    4. DECISION
       - All gates passed → tag ``phase_<n>_<id>_done`` (caller
         responsible for actually creating the git tag); return
         PhaseResult with status=passed.
       - Reviewer exhausted → tag
         ``phase_<n>_<id>_done_review_pending`` (short-name decision a);
         return status=passed_with_unresolved_review.
       - Producer hard fail → return status=failed for caller to halt.

PhaseExecutor itself does NOT touch git or web_state — those are
caller (ProjectSession in c4) responsibilities. PhaseExecutor is
deliberately a pure state machine that returns a PhaseResult.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Sequence

from ..utils.logging import get_logger
from .concurrent_executor import (
    DagResult,
    StageResult,
    StageSpec,
    Task,
    TaskResult,
    run_dag,
    run_grouped,
    run_parallel,
)
from .predicates import (
    DeliverableReport,
    PredicateContext,
    evaluate_deliverable,
)
from .reviewer import (
    ReviewerContext,
    ReviewerFeedback,
    ReviewLoopResult,
    prepend_reviewer_feedback,
    run_review_loop,
)
from .waterfall_v2_models import (
    Deliverable,
    FanoutSpec,
    PhaseSpec,
    WaterfallV2Spec,
)

logger = get_logger(__name__)


# -- Result types ---------------------------------------------------------


class PhaseStatus(str, Enum):
    PASSED = "passed"
    PASSED_WITH_UNRESOLVED_REVIEW = "passed_with_unresolved_review"
    FAILED = "failed"  # producer hard fail; caller halts run


@dataclass(frozen=True)
class PhaseResult:
    phase_id: str
    status: PhaseStatus
    deliverable_reports: tuple[DeliverableReport, ...] = ()
    fanout_result: Any = None  # StageResult | DagResult | None
    review_result: ReviewLoopResult | None = None
    producer_attempts: int = 0
    failure_summary: str = ""

    @property
    def tag_suffix(self) -> str:
        if self.status == PhaseStatus.PASSED:
            return "done"
        if self.status == PhaseStatus.PASSED_WITH_UNRESOLVED_REVIEW:
            return "done_review_pending"  # short-name per decision (a)
        return "failed"

    def phase_tag(self, phase_index: int) -> str:
        return f"phase_{phase_index + 1}_{self.phase_id}_{self.tag_suffix}"


# -- Producer self-check budget ------------------------------------------


_PRODUCER_AUTO_GATE_RETRIES = 3


# -- Fanout enumeration types --------------------------------------------


@dataclass(frozen=True)
class FanoutTaskPayload:
    """Opaque payload for a fanout subtask — describes which subsystem /
    component / scenario the task targets and what prompt to issue."""

    role: str  # producer agent role (always phase.producer)
    task_description: str
    expected_artifacts: tuple[str, ...]
    subsystem: str | None = None
    component: str | None = None
    scenario_id: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


# -- Fanout enumerator ----------------------------------------------------


def enumerate_subsystem_dag_tasks(
    fanout: FanoutSpec, stack_contract: dict[str, Any], producer: str
) -> dict[str, list[Task[FanoutTaskPayload]]]:
    """For ``strategy=subsystem_dag``, return tasks per stage id.

    Stage ``skeleton``: 1 task per subsystem.
    Stage ``component``: 1 task per (subsystem, component) pair.
    """
    subsystems = stack_contract.get("subsystems", []) or []
    out: dict[str, list[Task[FanoutTaskPayload]]] = {
        s.id: [] for s in fanout.stages
    }
    for ss in subsystems:
        sname = ss.get("name", "?")
        # Skeleton task
        if "skeleton" in out:
            comp_files = tuple(c.get("file") for c in ss.get("components", []) if c.get("file"))
            payload = FanoutTaskPayload(
                role=producer,
                task_description=(
                    f"Implement skeleton for subsystem '{sname}': "
                    f"create the public API surface for the components "
                    f"declared in stack_contract.subsystems[name={sname!r}]."
                ),
                expected_artifacts=comp_files,
                subsystem=sname,
            )
            out["skeleton"].append(
                Task(id=f"skeleton.{sname}", payload=payload)
            )
        # Component tasks
        if "component" in out:
            for comp in ss.get("components", []) or []:
                cf = comp.get("file")
                if not cf:
                    continue
                cname = comp.get("name", "?")
                tfile = comp.get("test_file")
                expected = (cf,) + ((tfile,) if tfile else ())
                payload = FanoutTaskPayload(
                    role=producer,
                    task_description=(
                        f"Implement component '{cname}' of subsystem "
                        f"'{sname}'. Source file: {cf}. "
                        f"Responsibility: {comp.get('responsibility', '')}."
                    ),
                    expected_artifacts=expected,
                    subsystem=sname,
                    component=cname,
                )
                out["component"].append(
                    Task(id=f"component.{sname}.{cname}", payload=payload)
                )
    return out


def enumerate_scenario_parallel_tasks(
    fanout: FanoutSpec,
    behavioral_contract: dict[str, Any],
    stack_contract: dict[str, Any],
    producer: str,
) -> dict[str, list[Task[FanoutTaskPayload]]]:
    """For ``strategy=scenario_parallel``, 1 task per scenario."""
    scenarios = behavioral_contract.get("scenarios", []) or []
    language = stack_contract.get("language", "python").lower()
    # Conservative ext map — same set as in waterfall_v2.process.md prompt
    ext = {
        "python": ".py", "py": ".py",
        "typescript": ".ts", "ts": ".ts",
        "javascript": ".js", "js": ".js",
        "go": ".go",
        "rust": ".rs",
        "java": ".java",
        "dart": ".dart",
        "csharp": ".cs", "cs": ".cs",
        "kotlin": ".kt",
        "swift": ".swift",
    }.get(language, ".py")

    out: dict[str, list[Task[FanoutTaskPayload]]] = {
        s.id: [] for s in fanout.stages
    }
    stage_id = fanout.stages[0].id  # scenario_parallel has one stage
    for scenario in scenarios:
        sid = scenario.get("id")
        if not sid:
            continue
        rel = f"tests/scenarios/{sid}{ext}"
        payload = FanoutTaskPayload(
            role=producer,
            task_description=(
                f"Implement scenario_id={sid}.\n"
                f"Trigger: {json.dumps(scenario.get('trigger', {}), ensure_ascii=False)}\n"
                f"Effect: {json.dumps(scenario.get('effect', {}), ensure_ascii=False)}\n"
                f"Description: {scenario.get('description', '')}\n"
                f"Write the test at {rel}."
            ),
            expected_artifacts=(rel,),
            scenario_id=sid,
        )
        out[stage_id].append(Task(id=f"scenario.{sid}", payload=payload))
    return out


# -- ConcurrentRunner abstraction (lets tests inject) ---------------------


@dataclass
class ConcurrentRunner:
    """Thin wrapper around concurrent_executor for DI in tests."""

    run_parallel: Callable = field(default=run_parallel)
    run_grouped: Callable = field(default=run_grouped)
    run_dag: Callable = field(default=run_dag)


# -- Phase executor -------------------------------------------------------


@dataclass
class PhaseExecutor:
    spec: WaterfallV2Spec
    project_root: Path
    produce_fn: Callable[[str, str, Sequence[str]], str]
    """produce_fn(producer_role, prompt, expected_artifacts) -> str.
    Returns the producer's textual output. Caller is responsible for
    using the per-task 3-retry semantics (c5 dispatch_task) inside.
    """
    dispatch_reviewer: Callable[[str, str], str]
    """dispatch_reviewer(reviewer_role, prompt) -> str. Per Decision 2,
    reviewer model is whatever ``agent_model_selection.<role>`` resolves to."""
    runner: ConcurrentRunner = field(default_factory=ConcurrentRunner)
    stack_contract: dict[str, Any] | None = None
    behavioral_contract: dict[str, Any] | None = None
    requirement_contract: dict[str, Any] | None = None

    # -- Phase prompt builder (caller can override per-phase via DI) -----

    build_phase_prompt: Callable[[PhaseSpec, str], str] = field(
        default=lambda phase, requirement: f"Execute phase '{phase.id}'. Requirement: {requirement}"
    )

    # -- Public API -------------------------------------------------------

    def execute_phase(self, phase: PhaseSpec, requirement: str) -> PhaseResult:
        """Run one phase end-to-end. Returns PhaseResult; caller decides
        whether to halt the run (status=failed) or advance."""
        logger.info("PhaseExecutor: starting phase=%s producer=%s", phase.id, phase.producer)

        # 1. PRODUCE + AUTO_GATE loop (up to _PRODUCER_AUTO_GATE_RETRIES)
        producer_prompt = self.build_phase_prompt(phase, requirement)
        producer_attempts = 0
        deliverable_reports: tuple[DeliverableReport, ...] = ()
        fanout_result: Any = None

        while producer_attempts < _PRODUCER_AUTO_GATE_RETRIES:
            producer_attempts += 1

            # Run producer (fanout or single-writer)
            if phase.has_fanout:
                fanout_result = self._run_fanout(phase, producer_prompt)
                if not self._fanout_passed(fanout_result):
                    # ALL_PASS fanout failure → producer hard fail → halt
                    summary = self._summarize_fanout_failure(fanout_result)
                    logger.warning(
                        "PhaseExecutor: phase=%s fanout failed — %s",
                        phase.id,
                        summary,
                    )
                    return PhaseResult(
                        phase_id=phase.id,
                        status=PhaseStatus.FAILED,
                        fanout_result=fanout_result,
                        producer_attempts=producer_attempts,
                        failure_summary=summary,
                    )
            else:
                # Single-writer producer
                self._run_single_producer(phase, producer_prompt)

            # AUTO_GATE: evaluate every deliverable
            deliverable_reports = self._evaluate_deliverables(phase)
            failures = [r for r in deliverable_reports if not r.passed]
            if not failures:
                break  # AUTO_GATE PASS
            # Re-prepare prompt with auto-gate failure as feedback
            failure_text = "\n\n".join(r.summary() for r in failures)
            logger.info(
                "PhaseExecutor: phase=%s auto_gate failed (attempt %d/%d): %s",
                phase.id,
                producer_attempts,
                _PRODUCER_AUTO_GATE_RETRIES,
                failure_text[:500],
            )
            producer_prompt = (
                f"[AUTO-GATE FEEDBACK]\n"
                f"Your previous attempt's deliverables failed automated checks:\n"
                f"{failure_text}\n\n"
                f"Fix the above and re-produce. ---\n\n"
                + self.build_phase_prompt(phase, requirement)
            )
        else:
            # Loop exhausted without AUTO_GATE pass → halt
            failure_text = "\n\n".join(
                r.summary() for r in deliverable_reports if not r.passed
            )
            logger.warning(
                "PhaseExecutor: phase=%s auto_gate exhausted after %d attempts",
                phase.id,
                producer_attempts,
            )
            return PhaseResult(
                phase_id=phase.id,
                status=PhaseStatus.FAILED,
                deliverable_reports=deliverable_reports,
                fanout_result=fanout_result,
                producer_attempts=producer_attempts,
                failure_summary=f"AUTO_GATE failed after {producer_attempts} attempts:\n{failure_text}",
            )

        # 3. REVIEWER_GATE
        review_result: ReviewLoopResult | None = None
        if phase.has_reviewer and phase.review is not None:
            review_result = self._run_review_loop(phase, requirement)

        # 4. DECISION
        if review_result is not None and review_result.passed_with_unresolved_review:
            status = PhaseStatus.PASSED_WITH_UNRESOLVED_REVIEW
        else:
            status = PhaseStatus.PASSED

        logger.info(
            "PhaseExecutor: phase=%s status=%s producer_attempts=%d review_iters=%s",
            phase.id,
            status.value,
            producer_attempts,
            review_result.iterations_used if review_result else "n/a",
        )
        return PhaseResult(
            phase_id=phase.id,
            status=status,
            deliverable_reports=deliverable_reports,
            fanout_result=fanout_result,
            review_result=review_result,
            producer_attempts=producer_attempts,
        )

    # -- Phase machinery (private) ---------------------------------------

    def _run_single_producer(self, phase: PhaseSpec, prompt: str) -> str:
        # Collect every deliverable's resolved path. For
        # kind=document/contract that's just deliverable.path; for
        # kind=derived (e.g. entry_point in main_entry phase) we
        # resolve via the derived-path helper so the producer is told
        # exactly what file to write.
        expected: list[str] = []
        for d in phase.deliverables:
            if d.kind in ("document", "contract") and d.path:
                expected.append(d.path)
            elif d.kind == "derived":
                for resolved in self._resolve_derived_paths(d):
                    try:
                        rel = resolved.relative_to(self.project_root)
                        expected.append(str(rel))
                    except ValueError:
                        expected.append(str(resolved))
        return self.produce_fn(phase.producer, prompt, tuple(expected))

    def _run_fanout(self, phase: PhaseSpec, base_prompt: str) -> Any:
        assert phase.fanout is not None
        fanout = phase.fanout
        strategy = fanout.strategy
        if strategy == "subsystem_dag":
            tasks_per_stage = enumerate_subsystem_dag_tasks(
                fanout, self.stack_contract or {}, phase.producer
            )
        elif strategy == "scenario_parallel":
            tasks_per_stage = enumerate_scenario_parallel_tasks(
                fanout,
                self.behavioral_contract or {},
                self.stack_contract or {},
                phase.producer,
            )
        elif strategy == "flat_parallel":
            # Caller's responsibility to subclass / inject. Default empty.
            tasks_per_stage = {s.id: [] for s in fanout.stages}
        else:
            raise ValueError(f"Unknown fanout strategy: {strategy!r}")

        def task_fn(t: Task[FanoutTaskPayload]) -> TaskResult:
            payload = t.payload
            sub_prompt = (
                f"{base_prompt}\n\n"
                f"[FANOUT TASK]\n"
                f"{payload.task_description}\n\n"
                f"Expected artifacts: {list(payload.expected_artifacts)}"
            )
            try:
                self.produce_fn(payload.role, sub_prompt, payload.expected_artifacts)
            except Exception as exc:
                return TaskResult(
                    task_id=t.id,
                    passed=False,
                    detail=f"produce_fn raised {type(exc).__name__}: {exc}",
                )
            # Gate the task by checking its expected_artifacts exist on disk.
            missing = [
                p for p in payload.expected_artifacts
                if not (self.project_root / p.lstrip("/")).is_file()
            ]
            if missing:
                return TaskResult(
                    task_id=t.id,
                    passed=False,
                    detail=f"missing artifacts after producer: {missing}",
                    artifact_paths=payload.expected_artifacts,
                )
            return TaskResult(
                task_id=t.id,
                passed=True,
                detail="produced",
                artifact_paths=payload.expected_artifacts,
            )

        # Build StageSpec list and run via DAG (handles ordering)
        stage_specs: list[StageSpec[FanoutTaskPayload]] = []
        for stage in fanout.stages:
            tasks = tuple(tasks_per_stage.get(stage.id, []))
            group_by = None
            if stage.group_by == "subsystem":
                group_by = lambda payload: payload.subsystem  # noqa: E731
            stage_specs.append(
                StageSpec(
                    id=stage.id,
                    tasks=tasks,
                    max_workers=stage.concurrency.max_workers,
                    depends_on=stage.depends_on,
                    group_by=group_by,
                )
            )
        return self.runner.run_dag(stage_specs, task_fn)

    @staticmethod
    def _fanout_passed(fanout_result: Any) -> bool:
        if isinstance(fanout_result, DagResult):
            return fanout_result.passed
        if isinstance(fanout_result, StageResult):
            return fanout_result.passed
        return False

    @staticmethod
    def _summarize_fanout_failure(fanout_result: Any) -> str:
        if isinstance(fanout_result, DagResult):
            halted = fanout_result.halted_at_stage or "?"
            failed = []
            for sr in fanout_result.stage_results:
                for r in sr.failed_results:
                    failed.append(f"{sr.stage_id}::{r.task_id}: {r.detail}")
            joined = "\n  - ".join(failed[:10])
            more = f" (+{len(failed) - 10} more)" if len(failed) > 10 else ""
            return f"halted at stage={halted}; failures:\n  - {joined}{more}"
        if isinstance(fanout_result, StageResult):
            failed = [f"{r.task_id}: {r.detail}" for r in fanout_result.failed_results]
            return f"stage failures: {failed[:5]}{'...' if len(failed) > 5 else ''}"
        return "unknown fanout failure"

    def _evaluate_deliverables(self, phase: PhaseSpec) -> tuple[DeliverableReport, ...]:
        # Re-load contracts from disk before AUTO_GATE — the producer
        # we just ran may have written the contract files for the first
        # time (this is exactly what the architect phase does for
        # stack_contract.json / behavioral_contract.json).
        self._refresh_contracts_from_disk()

        reports: list[DeliverableReport] = []
        for deliverable in phase.deliverables:
            paths = self._resolve_deliverable_paths(deliverable)
            for p in paths:
                ctx = PredicateContext(
                    project_root=self.project_root,
                    deliverable_path=p,
                    stack_contract=self.stack_contract,
                    behavioral_contract=self.behavioral_contract,
                    requirement_contract=self.requirement_contract,
                )
                reports.append(evaluate_deliverable(deliverable, ctx))
        return tuple(reports)

    def _refresh_contracts_from_disk(self) -> None:
        """Re-read docs/{stack,behavioral,requirement}_contract.json so
        AUTO_GATE sees the just-produced state. Idempotent — silent on
        missing files (predicates handle that themselves)."""
        for attr, fname in (
            ("stack_contract", "stack_contract.json"),
            ("behavioral_contract", "behavioral_contract.json"),
            ("requirement_contract", "requirement_contract.json"),
        ):
            path = self.project_root / "docs" / fname
            if not path.is_file():
                continue
            try:
                setattr(self, attr, json.loads(path.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                pass  # leave whatever was already on the executor

    def _resolve_deliverable_paths(self, deliverable: Deliverable) -> list[Path]:
        """For kind=document/contract: one path. For kind=derived: many."""
        if deliverable.kind in ("document", "contract"):
            if deliverable.path is None:
                return []
            return [self.project_root / deliverable.path.lstrip("/")]
        if deliverable.kind == "derived":
            return self._resolve_derived_paths(deliverable)
        return []

    def _resolve_derived_paths(self, deliverable: Deliverable) -> list[Path]:
        """Materialize derived deliverable paths from the appropriate
        contract. Supports the rules referenced in waterfall_v2.process.md:
        * stack_contract.every_component.file
        * stack_contract.every_component.test_file
        * stack_contract.entry_point
        * behavioral_contract.scenario_test_path
        Anything else returns empty (loader schema would have caught it
        if it was a typo, so this is a no-op for forward-compat rules).
        """
        if deliverable.from_ == "stack_contract":
            sc = self.stack_contract or {}
            if deliverable.rule == "every_component.file":
                return [
                    self.project_root / c["file"].lstrip("/")
                    for ss in sc.get("subsystems", [])
                    for c in ss.get("components", [])
                    if c.get("file")
                ]
            if deliverable.rule == "every_component.test_file":
                # Only the components that explicitly declared a test_file.
                # Components without test_file are out of scope for AUTO_GATE
                # (their test path would be derived in the verification phase).
                return [
                    self.project_root / c["test_file"].lstrip("/")
                    for ss in sc.get("subsystems", [])
                    for c in ss.get("components", [])
                    if c.get("test_file")
                ]
            if deliverable.rule == "entry_point":
                ep = sc.get("entry_point")
                if ep:
                    return [self.project_root / ep.lstrip("/")]
                return []
        if deliverable.from_ == "behavioral_contract":
            bc = self.behavioral_contract or {}
            if deliverable.rule == "scenario_test_path":
                # Match the same ext mapping used for fanout enumeration
                language = (self.stack_contract or {}).get("language", "python").lower()
                ext_map = {
                    "python": ".py", "typescript": ".ts", "javascript": ".js",
                    "go": ".go", "rust": ".rs", "java": ".java",
                    "dart": ".dart", "csharp": ".cs", "cs": ".cs",
                    "kotlin": ".kt", "swift": ".swift",
                }
                ext = ext_map.get(language, ".py")
                return [
                    self.project_root / f"tests/scenarios/{s['id']}{ext}"
                    for s in bc.get("scenarios", [])
                    if s.get("id")
                ]
        return []

    def _run_review_loop(
        self, phase: PhaseSpec, requirement: str
    ) -> ReviewLoopResult:
        assert phase.review is not None
        ctx = ReviewerContext(
            project_root=self.project_root,
            dispatch_reviewer=self.dispatch_reviewer,
        )

        def deliverable_paths_fn() -> list[Path]:
            paths: list[Path] = []
            for d in phase.deliverables:
                paths.extend(self._resolve_deliverable_paths(d))
            return paths

        def revise_callback(feedbacks: Sequence[ReviewerFeedback]) -> None:
            base_prompt = self.build_phase_prompt(phase, requirement)
            new_prompt = prepend_reviewer_feedback(base_prompt, feedbacks)
            # Re-issue producer with prepended feedback. We don't re-run
            # fanout here — reviewer feedback typically affects the
            # docs (architecture.md / requirement.md) not fanned-out
            # source code; if the user wants reviewer-driven re-fanout
            # they can rephrase the question to require it.
            if not phase.has_fanout:
                self._run_single_producer(phase, new_prompt)

        return run_review_loop(
            list(phase.reviewer),
            phase.review.reviewer_questions,
            deliverable_paths_fn,
            ctx,
            revise_callback,
            revise_budget=phase.review.revise_budget,
        )
