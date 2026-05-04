"""ConcurrentExecutor — strict ALL_PASS fanout with DAG ordering.

Implements the concurrency model described in
``waterfall_v2.process.md``:

* Tier T1 (fully independent): ``run_parallel`` — single-stage parallel
  with bounded workers; per-task retries are 3 (handled inside
  ``task_fn``); ALL_PASS join means any failed task surfaces as a
  ``StageResult.failed``.
* Tier T2 (DAG with ``depends_on``): ``run_dag`` — runs each stage in
  topological order; previous stage must ALL_PASS before next stage
  starts.
* Tier T3 (single writer): just call ``task_fn`` directly.

The executor is LLM-agnostic. Callers pass:

* ``tasks: list[Task]`` for one stage, OR
* ``stages: list[StageSpec]`` for a DAG
* ``task_fn: Callable[[Task], TaskResult]`` — caller's per-task work
  (typically wraps a dispatch_task call + acceptance gate evaluation)

This module does NOT cancel in-flight tasks when a sibling fails. The
rationale (per the design discussion): siblings might still produce
useful artifacts that show up in the user's resume request, saving
work on retry. The aggregator collects every result and surfaces
failures together so the user can fix multiple issues in one review.
"""

from __future__ import annotations

import concurrent.futures
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Generic, Hashable, TypeVar

T = TypeVar("T")


# -- Task / Result types --------------------------------------------------


@dataclass(frozen=True)
class Task(Generic[T]):
    """One unit of work for the concurrent executor.

    ``payload`` is opaque to the executor — callers stuff their
    dispatch arguments / context into it. ``id`` is required for
    DAG group-by routing and result reporting. ``group`` is used by
    DAG stages with ``group_by``: tasks in the same group run
    serially relative to each other; different groups run in
    parallel up to the worker cap.
    """

    id: str
    payload: T
    group: Hashable | None = None


@dataclass(frozen=True)
class TaskResult:
    task_id: str
    passed: bool
    detail: str = ""
    artifact_paths: tuple[str, ...] = field(default_factory=tuple)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StageResult:
    stage_id: str
    results: tuple[TaskResult, ...]

    @property
    def passed(self) -> bool:
        return all(r.passed for r in self.results) and len(self.results) > 0

    @property
    def failed_results(self) -> tuple[TaskResult, ...]:
        return tuple(r for r in self.results if not r.passed)

    @property
    def passed_results(self) -> tuple[TaskResult, ...]:
        return tuple(r for r in self.results if r.passed)


@dataclass(frozen=True)
class DagResult:
    stage_results: tuple[StageResult, ...]
    halted_at_stage: str | None = None  # set when a stage failed and DAG aborted

    @property
    def passed(self) -> bool:
        return self.halted_at_stage is None and all(s.passed for s in self.stage_results)


# -- Stage spec for DAG runs ----------------------------------------------


@dataclass(frozen=True)
class StageSpec(Generic[T]):
    """One stage in a DAG. ``group_by`` is a callable that, given a
    task's payload, returns the group key. When set, tasks in the same
    group run serially. ``depends_on`` is informational here — the
    executor walks stages in declared order; the loader's schema
    enforces the depends_on consistency.
    """

    id: str
    tasks: tuple[Task[T], ...]
    max_workers: int = 5
    depends_on: str | None = None
    group_by: Callable[[T], Hashable] | None = None


# -- Public API -----------------------------------------------------------


def run_parallel(
    tasks: list[Task[T]] | tuple[Task[T], ...],
    task_fn: Callable[[Task[T]], TaskResult],
    *,
    max_workers: int = 5,
    stage_id: str = "stage",
) -> StageResult:
    """T1 fanout: every task fully independent, parallel up to max_workers.

    Returns when every task has reported (success or failure). Does NOT
    early-cancel siblings on first failure — see module docstring.
    """
    if not tasks:
        return StageResult(stage_id=stage_id, results=())

    results: list[TaskResult] = []
    lock = threading.Lock()

    def _run_one(t: Task[T]) -> TaskResult:
        try:
            return task_fn(t)
        except Exception as exc:
            return TaskResult(
                task_id=t.id,
                passed=False,
                detail=f"task_fn raised {type(exc).__name__}: {exc}",
            )

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futures = [pool.submit(_run_one, t) for t in tasks]
        for fut in concurrent.futures.as_completed(futures):
            r = fut.result()
            with lock:
                results.append(r)

    # Sort by original task order for deterministic reporting.
    by_id = {r.task_id: r for r in results}
    ordered = tuple(by_id[t.id] for t in tasks if t.id in by_id)
    # Append any stragglers (defensive — should be empty)
    extras = tuple(r for r in results if r.task_id not in {t.id for t in tasks})
    return StageResult(stage_id=stage_id, results=ordered + extras)


def run_grouped(
    tasks: list[Task[T]] | tuple[Task[T], ...],
    task_fn: Callable[[Task[T]], TaskResult],
    *,
    group_by: Callable[[T], Hashable],
    max_workers: int = 5,
    stage_id: str = "stage",
) -> StageResult:
    """T2 fanout with grouping: same-group tasks serial, different-group
    parallel up to max_workers groups simultaneously.

    Used by phase 3's component stage where same-subsystem components
    share files (e.g. all components touch their subsystem's barrel
    file) and must not race, but cross-subsystem components are safe
    to parallelize.
    """
    if not tasks:
        return StageResult(stage_id=stage_id, results=())

    groups: dict[Hashable, list[Task[T]]] = defaultdict(list)
    for t in tasks:
        groups[group_by(t.payload)].append(t)

    def _run_group(group_tasks: list[Task[T]]) -> list[TaskResult]:
        out: list[TaskResult] = []
        for t in group_tasks:
            try:
                r = task_fn(t)
            except Exception as exc:
                r = TaskResult(
                    task_id=t.id,
                    passed=False,
                    detail=f"task_fn raised {type(exc).__name__}: {exc}",
                )
            out.append(r)
        return out

    all_results: list[TaskResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, max_workers)) as pool:
        futures = [pool.submit(_run_group, g) for g in groups.values()]
        for fut in concurrent.futures.as_completed(futures):
            all_results.extend(fut.result())

    by_id = {r.task_id: r for r in all_results}
    ordered = tuple(by_id[t.id] for t in tasks if t.id in by_id)
    return StageResult(stage_id=stage_id, results=ordered)


def run_dag(
    stages: list[StageSpec[T]],
    task_fn: Callable[[Task[T]], TaskResult],
) -> DagResult:
    """Run stages in declared order. If any stage fails ALL_PASS, the
    DAG halts (later stages are NOT run). Returns the partial
    StageResult list with ``halted_at_stage`` set to the failed
    stage id.
    """
    completed: list[StageResult] = []
    for stage in stages:
        if stage.group_by is not None:
            sr = run_grouped(
                stage.tasks,
                task_fn,
                group_by=stage.group_by,
                max_workers=stage.max_workers,
                stage_id=stage.id,
            )
        else:
            sr = run_parallel(
                stage.tasks,
                task_fn,
                max_workers=stage.max_workers,
                stage_id=stage.id,
            )
        completed.append(sr)
        if not sr.passed:
            return DagResult(
                stage_results=tuple(completed),
                halted_at_stage=stage.id,
            )
    return DagResult(stage_results=tuple(completed), halted_at_stage=None)
