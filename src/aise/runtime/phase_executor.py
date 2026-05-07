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

import hashlib
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


# -- Fan-out parallelism cap ---------------------------------------------
#
# A3 (2026-05-05): the spec's static ``max_workers: 3`` was chosen for
# small Python CLIs and serialized 22-Dart-component fan-outs into 7+
# batches. We widen at runtime based on task count, capped here.
# Above ~8 we hit local-vLLM queue saturation (no real parallelism left)
# and on a cloud LLM with prompt caching the marginal speedup vs queue
# pressure flattens around the same number.
_MAX_FANOUT_PARALLELISM = 8


def _file_fingerprint(path: Path) -> str:
    """Cheap content fingerprint used by the AUTO_GATE incremental
    cache (B3). Returns ``"missing"`` for non-existent files (treated
    as a distinct cache key from any present-file fingerprint), and
    ``size:hex(sha256)`` otherwise. Reading the file twice in the same
    AUTO_GATE pass is fine — it's small (architect docs / contract
    JSON / per-component source); the cache only helps across
    *retries*, not within one pass.
    """
    if not path.is_file():
        return "missing"
    try:
        data = path.read_bytes()
    except OSError:
        return "missing"
    return f"{len(data)}:{hashlib.sha256(data).hexdigest()[:32]}"


def _adaptive_max_workers(task_count: int) -> int:
    """Return a sensible per-stage worker count for ``task_count`` tasks.

    The mapping is intentionally coarse — 3 buckets:

    - ≤ 4 tasks: 2 workers (small project; saturating 3+ wastes setup)
    - 5–15 tasks: 4 workers (medium; balance of throughput vs LLM queue)
    - 16+ tasks: 8 workers (large project; full parallelism cap)

    Callers (``_run_fanout``) treat this as a *floor* combined with the
    spec's static ``max_workers``; the larger of the two wins, so a
    spec author can still pin a higher value if their stack supports it.
    """
    if task_count <= 4:
        return 2
    if task_count <= 15:
        return 4
    return _MAX_FANOUT_PARALLELISM


# -- Inline JSON contract examples ---------------------------------------
# Surfaced to producer LLMs in the rich phase prompt. The local model
# can't be expected to fetch + parse the JSON Schema files; giving it a
# valid example skeleton is the most reliable way to get a conforming
# output. Keyed by the bare filename of the deliverable path
# (resolved via ``rel.name``).

_CONTRACT_EXAMPLES: dict[str, str] = {
    "requirement_contract.json": """{
  "project_name": "<project name>",
  "summary": "<one-paragraph summary>",
  "functional_requirements": [
    {
      "id": "FR-001",
      "title": "<short title>",
      "description": "<what the system must do>",
      "acceptance_criteria": ["<measurable criterion>"],
      "priority": "P0"
    }
  ],
  "non_functional_requirements": [
    {
      "id": "NFR-001",
      "title": "<e.g. response latency>",
      "description": "<measurable constraint>",
      "priority": "P1"
    }
  ],
  "use_cases": [
    {
      "id": "UC-001",
      "actor": "<role>",
      "goal": "<one-sentence goal>",
      "preconditions": ["<precondition>"],
      "main_flow": ["<step 1>", "<step 2>"],
      "covers_requirements": ["FR-001"]
    }
  ]
}""",
    "stack_contract.json": """{
  "language": "python",
  "runtime": "cpython3.11",
  "framework_backend": "fastapi",
  "framework_frontend": "",
  "package_manager": "pip",
  "project_config_file": "pyproject.toml",
  "test_runner": "pytest",
  "test_cmd": "python -m pytest tests/ -q",
  "static_analyzer": ["ruff check"],
  "entry_point": "src/main.py",
  "run_command": "python -m src.main",
  "ui_required": false,
  "subsystems": [
    {
      "name": "core",
      "src_dir": "src/core",
      "responsibilities": "<what this subsystem owns>",
      "components": [
        {
          "name": "<component name>",
          "file": "src/core/<file>.py",
          "test_file": "tests/core/test_<file>.py",
          "responsibility": "<what this component does>"
        }
      ]
    }
  ],
  "lifecycle_inits": []
}""",
    "behavioral_contract.json": """{
  "scenarios": [
    {
      "id": "boot_shows_main",
      "name": "Boot shows main entry",
      "description": "When the program starts, it produces the expected initial output.",
      "preconditions": ["No prior state required"],
      "trigger": {"action": "run", "command": "python -m src.main"},
      "effect": {"stdout_contains": "<expected substring>"},
      "covers_requirements": ["FR-001"]
    }
  ]
}""",
    "data_dependency_contract.json": """{
  "version": "1",
  "data_dependencies": [
    {
      "name": "level_data",
      "files_glob": "assets/level_*.json",
      "consumer_module": "src/level/loader.*",
      "min_files": 1,
      "load_invariant": {
        "kind": "collection_non_empty",
        "expr": "loader.levels",
        "after": "boot+init"
      }
    }
  ]
}""",
    "action_contract.json": """{
  "version": "1",
  "actions": [
    {
      "name": "primary_action",
      "trigger": { "kind": "key", "value": "Enter" },
      "expected_change": { "kind": "state_field_changes", "field": "currentScreen" },
      "handler_must_call": ["controller.handlePrimary"]
    }
  ]
}""",
    "integration_report.json": """{
  "phase": "main_entry",
  "completed_at": "<ISO timestamp>",
  "verdict": "pass",
  "lifecycle_init_check": { "expected": 0, "reached": 0 },
  "data_wiring_check": [
    { "name": "<dep name>", "static_refs": 1, "consumer_module_resolved": "src/<file>", "runtime_invariant_ok": true }
  ],
  "action_wiring_check": [
    { "name": "<action name>", "handler_calls_found": 1, "handler_calls_missing": [] }
  ],
  "boot_check": { "ran": false, "verdict": "skipped", "reason": "no headless harness available in sandbox" },
  "violations": []
}""",
}


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
    out: dict[str, list[Task[FanoutTaskPayload]]] = {s.id: [] for s in fanout.stages}
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
            out["skeleton"].append(Task(id=f"skeleton.{sname}", payload=payload))
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
                out["component"].append(Task(id=f"component.{sname}.{cname}", payload=payload))
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
        "python": ".py",
        "py": ".py",
        "typescript": ".ts",
        "ts": ".ts",
        "javascript": ".js",
        "js": ".js",
        "go": ".go",
        "rust": ".rs",
        "dart": ".dart",
        "cpp": ".cpp",
        "c++": ".cpp",
        "kotlin": ".kt",
        "swift": ".swift",
    }.get(language, ".py")

    out: dict[str, list[Task[FanoutTaskPayload]]] = {s.id: [] for s in fanout.stages}
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
    data_dependency_contract: dict[str, Any] | None = None
    action_contract: dict[str, Any] | None = None
    # B3 (2026-05-05): per-(path, kind, file_fp, contracts_fp) cache of
    # previously-PASSED DeliverableReports. Skips re-running the predicate
    # sweep on retries when nothing relevant has changed. Reset implicitly
    # whenever a new PhaseExecutor is built (one per phase invocation).
    _gate_cache: dict[tuple, DeliverableReport] = field(default_factory=dict)

    # -- Phase prompt builder (caller can override per-phase via DI) -----
    # Default builder lazily resolves to ``_default_build_phase_prompt``
    # at call time (we can't reference it in the dataclass field literal
    # because the bound method needs ``self``).

    build_phase_prompt: Callable[[PhaseSpec, str], str] | None = None

    # -- Public API -------------------------------------------------------

    def execute_phase(self, phase: PhaseSpec, requirement: str) -> PhaseResult:
        """Run one phase end-to-end. Returns PhaseResult; caller decides
        whether to halt the run (status=failed) or advance."""
        logger.info("PhaseExecutor: starting phase=%s producer=%s", phase.id, phase.producer)

        # 1. PRODUCE + AUTO_GATE loop (up to _PRODUCER_AUTO_GATE_RETRIES)
        producer_prompt = self._call_build_phase_prompt(phase, requirement)
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
                f"Fix the above and re-produce. ---\n\n" + self._call_build_phase_prompt(phase, requirement)
            )
        else:
            # Loop exhausted without AUTO_GATE pass → halt
            failure_text = "\n\n".join(r.summary() for r in deliverable_reports if not r.passed)
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
            tasks_per_stage = enumerate_subsystem_dag_tasks(fanout, self.stack_contract or {}, phase.producer)
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
            missing = [p for p in payload.expected_artifacts if not (self.project_root / p.lstrip("/")).is_file()]
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
            # Adaptive max_workers: scale with task count (perf opt A3,
            # 2026-05-05). The spec's static value is a floor; we widen
            # it up to ``_MAX_FANOUT_PARALLELISM`` when fan-out is fat
            # (e.g. 22-component Flutter project would otherwise sit at
            # 3-wide and serialize 7 batches). For small projects the
            # static value still wins because there aren't enough tasks
            # to fill more workers anyway.
            adaptive_workers = max(stage.concurrency.max_workers, _adaptive_max_workers(len(tasks)))
            stage_specs.append(
                StageSpec(
                    id=stage.id,
                    tasks=tasks,
                    max_workers=adaptive_workers,
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

        # B3 (2026-05-05): incremental cache. Re-checking deliverables
        # whose file content + contracts haven't changed across
        # producer attempts is wasted IO + CPU. We hash (sha256) the
        # deliverable file plus a fingerprint of the loaded contracts
        # and skip the per-deliverable predicate sweep when the same
        # tuple was just verified PASS. Cache is per-PhaseExecutor so
        # a fresh phase execution starts clean.
        contracts_fp = self._contracts_fingerprint()

        reports: list[DeliverableReport] = []
        for deliverable in phase.deliverables:
            paths = self._resolve_deliverable_paths(deliverable)
            for p in paths:
                file_fp = _file_fingerprint(p)
                cache_key = (str(p), deliverable.kind, file_fp, contracts_fp)
                cached = self._gate_cache.get(cache_key)
                if cached is not None and cached.passed:
                    # Re-evaluating a passing predicate set on identical
                    # input is deterministic — safe to reuse. We do NOT
                    # cache failing reports (the failure detail string
                    # contains paths that may surface differently across
                    # attempts; safer to re-run them).
                    reports.append(cached)
                    continue
                ctx = PredicateContext(
                    project_root=self.project_root,
                    deliverable_path=p,
                    stack_contract=self.stack_contract,
                    behavioral_contract=self.behavioral_contract,
                    requirement_contract=self.requirement_contract,
                    data_dependency_contract=self.data_dependency_contract,
                    action_contract=self.action_contract,
                )
                report = evaluate_deliverable(deliverable, ctx)
                if report.passed:
                    self._gate_cache[cache_key] = report
                reports.append(report)
        return tuple(reports)

    def _contracts_fingerprint(self) -> str:
        """Cheap content-hash of the loaded contracts. When any
        contract changes between producer attempts, every deliverable's
        cache entry is invalidated — even if the deliverable file
        itself is unchanged — because the predicate evaluator reads
        the contracts via PredicateContext."""
        h = hashlib.sha256()
        for c in (
            self.stack_contract,
            self.behavioral_contract,
            self.requirement_contract,
            self.data_dependency_contract,
            self.action_contract,
        ):
            h.update(b"\x00")
            if c is not None:
                # sort_keys to make this deterministic across dict ordering
                h.update(json.dumps(c, sort_keys=True, ensure_ascii=False).encode("utf-8"))
        return h.hexdigest()

    def _refresh_contracts_from_disk(self) -> None:
        """Re-read docs/*_contract.json so AUTO_GATE sees the just-produced
        state. Idempotent — silent on missing files (predicates handle
        that themselves; the integration-assembly predicates vacuous-pass
        when their driving contract is absent)."""
        for attr, fname in (
            ("stack_contract", "stack_contract.json"),
            ("behavioral_contract", "behavioral_contract.json"),
            ("requirement_contract", "requirement_contract.json"),
            ("data_dependency_contract", "data_dependency_contract.json"),
            ("action_contract", "action_contract.json"),
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
                    "python": ".py",
                    "typescript": ".ts",
                    "javascript": ".js",
                    "go": ".go",
                    "rust": ".rs",
                    "dart": ".dart",
                    "cpp": ".cpp",
                    "c++": ".cpp",
                    "kotlin": ".kt",
                    "swift": ".swift",
                }
                ext = ext_map.get(language, ".py")
                return [
                    self.project_root / f"tests/scenarios/{s['id']}{ext}"
                    for s in bc.get("scenarios", [])
                    if s.get("id")
                ]
        return []

    # -- Producer prompt builder ----------------------------------------

    def _call_build_phase_prompt(self, phase: PhaseSpec, requirement: str) -> str:
        """Route to caller-provided builder if any, else the rich default.
        The default lists every deliverable's path + acceptance summary +
        any schema reference so the producer LLM knows exactly what files
        it MUST write and what they need to look like."""
        if self.build_phase_prompt is not None:
            return self.build_phase_prompt(phase, requirement)
        return self._default_build_phase_prompt(phase, requirement)

    def _default_build_phase_prompt(self, phase: PhaseSpec, requirement: str) -> str:
        lines: list[str] = []
        lines.append("=== ORIGINAL USER REQUIREMENT ===")
        lines.append(requirement)
        lines.append("=== END REQUIREMENT ===")
        lines.append("")
        lines.append(f"Phase: {phase.id}  ({phase.title or 'no title'})")
        lines.append(f"Producer role: {phase.producer}")
        if phase.inputs:
            lines.append(f"Inputs (read these first): {list(phase.inputs)}")
        lines.append("")
        lines.append("DELIVERABLES YOU MUST PRODUCE (each must satisfy the listed acceptance checks):")
        for d in phase.deliverables:
            paths = self._resolve_deliverable_paths(d)
            if not paths:
                continue
            for p in paths:
                try:
                    rel = p.relative_to(self.project_root)
                except ValueError:
                    rel = p
                acc_kinds = [a.kind for a in d.acceptance]
                lines.append(f"  - {rel}")
                lines.append(f"      kind: {d.kind}")
                lines.append(f"      acceptance: {acc_kinds}")
                for a in d.acceptance:
                    if a.kind == "schema":
                        # Inline an example skeleton matching the schema so
                        # the producer doesn't have to look it up. Surfacing
                        # only the schema FILE path confused weak local
                        # models into writing the schema definition itself
                        # (or writing the contract under ``schemas/``).
                        example = _CONTRACT_EXAMPLES.get(str(rel).split("/")[-1], "")
                        if example:
                            lines.append("      content MUST be valid JSON like this example:")
                            for ex_line in example.splitlines():
                                lines.append(f"        {ex_line}")
                    elif a.kind == "min_bytes":
                        lines.append(f"      minimum size: {a.arg} bytes")
                    elif a.kind == "contains_sections":
                        lines.append(f"      required sections (must appear as markdown headings): {a.arg}")
                    elif a.kind == "regex_count":
                        lines.append(f"      required regex matches: {a.arg}")
                    elif a.kind == "min_scenarios":
                        lines.append(f"      minimum scenarios in JSON: {a.arg}")
                    elif a.kind == "prior_phases_summarized":
                        lines.append(
                            "      report MUST mention canonical artifact paths "
                            "(docs/requirement.md, docs/architecture.md, "
                            "docs/stack_contract.json, docs/behavioral_contract.json)"
                        )
                    elif a.kind == "contains_all_lifecycle_inits":
                        lines.append(
                            "      entry_point body MUST invoke every "
                            "<attr>.<method>() declared in stack_contract.lifecycle_inits"
                        )
                    elif a.kind == "mermaid_validates_via_skill":
                        lines.append(
                            "      every ```mermaid block MUST start with a known header "
                            "(flowchart / graph / sequenceDiagram / classDiagram / "
                            "stateDiagram / erDiagram / C4Context / C4Container / C4Component)"
                        )
        lines.append("")
        lines.append("INSTRUCTIONS:")
        lines.append("- Use write_file to create EACH deliverable at the EXACT path listed above.")
        lines.append("- For *.json deliverables, output VALID JSON. Use the example as a structural template.")
        lines.append("- Do NOT write into 'schemas/' — that is for schema definitions, not your output.")
        lines.append("- Do NOT skip any deliverable — every one is graded by an automated check.")
        lines.append("- When done, reply with a one-line summary; do NOT call any 'mark_complete' tool.")
        return "\n".join(lines)

    def _run_review_loop(self, phase: PhaseSpec, requirement: str) -> ReviewLoopResult:
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
            base_prompt = self._call_build_phase_prompt(phase, requirement)
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
