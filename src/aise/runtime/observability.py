"""Live observability for in-flight tasks + manual abort surface.

Without budget caps (Decision 1: no wall-clock, no max_dispatches), the
operator's only signal about a stuck task is ``elapsed_seconds`` and
``llm_call_count``. This module owns the registry that PhaseExecutor /
dispatch_task update on each LLM call, and the abort surface a CLI /
web command can poke to forcibly mark a task as failed.

Surface
-------
* TaskRegistry — process-global singleton (one per aise process)
  - register_task(task_id, agent, step) — at dispatch start
  - record_llm_call(task_id, dur_ms, in_tokens, out_tokens) — per call
  - record_loop_detector_hit(task_id) — when loop_detector fires
  - mark_completed(task_id, status) — at dispatch end
  - request_abort(task_id) — operator API
  - is_abort_requested(task_id) → bool — task hot-path checks this
    between LLM calls and raises AbortRequested if set
  - active_tasks() → list[TaskSnapshot] — for web UI / CLI
  - get_snapshot(task_id) → TaskSnapshot | None
* TaskSnapshot dataclass: serializable view for logs / web / CLI
* AbortRequested exception — raised by tasks that observed an abort
  request. PhaseExecutor catches this and marks the producer attempt
  as failed (so 3-retry semantics still apply).

Threading
---------
TaskRegistry is thread-safe (internal lock). Methods are O(1) except
active_tasks (O(N) over registered tasks) which is fine for the
expected scale (≤100 in-flight tasks per phase).

Persistence
-----------
None. The registry is in-memory only — when the aise process exits
or the run is killed, the registry resets. Web UI surfaces a separate
notion of historical tasks via the trace files. The registry is
strictly for "what's happening RIGHT NOW".
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from time import monotonic
from typing import Any

# -- Snapshot type -------------------------------------------------------


@dataclass(frozen=True)
class TaskSnapshot:
    task_id: str
    agent: str
    step: str
    started_at_monotonic: float
    elapsed_seconds: float
    llm_call_count: int
    last_llm_call_seconds_ago: float | None
    input_tokens: int
    output_tokens: int
    loop_detector_hits: int
    abort_requested: bool
    status: str  # "running" | "completed" | "failed" | "aborted"

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "agent": self.agent,
            "step": self.step,
            "elapsed_seconds": round(self.elapsed_seconds, 1),
            "llm_call_count": self.llm_call_count,
            "last_llm_call_seconds_ago": (
                round(self.last_llm_call_seconds_ago, 1)
                if self.last_llm_call_seconds_ago is not None
                else None
            ),
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "loop_detector_hits": self.loop_detector_hits,
            "abort_requested": self.abort_requested,
            "status": self.status,
        }


# -- AbortRequested exception -------------------------------------------


class AbortRequested(Exception):
    """Raised by a task that observed an operator abort request via
    ``TaskRegistry.is_abort_requested``."""


# -- Internal mutable record --------------------------------------------


@dataclass
class _TaskRecord:
    task_id: str
    agent: str
    step: str
    started_at_monotonic: float
    llm_call_count: int = 0
    last_llm_call_at_monotonic: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    loop_detector_hits: int = 0
    abort_requested: bool = False
    status: str = "running"

    def snapshot(self, now: float | None = None) -> TaskSnapshot:
        now = monotonic() if now is None else now
        last_ago: float | None = None
        if self.last_llm_call_at_monotonic is not None:
            last_ago = now - self.last_llm_call_at_monotonic
        return TaskSnapshot(
            task_id=self.task_id,
            agent=self.agent,
            step=self.step,
            started_at_monotonic=self.started_at_monotonic,
            elapsed_seconds=now - self.started_at_monotonic,
            llm_call_count=self.llm_call_count,
            last_llm_call_seconds_ago=last_ago,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            loop_detector_hits=self.loop_detector_hits,
            abort_requested=self.abort_requested,
            status=self.status,
        )


# -- Registry -----------------------------------------------------------


class TaskRegistry:
    """Process-global registry of in-flight tasks. Thread-safe."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: dict[str, _TaskRecord] = {}

    # -- write API (called from dispatch_task hot path) --

    def register_task(self, task_id: str, agent: str, step: str = "") -> None:
        with self._lock:
            self._records[task_id] = _TaskRecord(
                task_id=task_id,
                agent=agent,
                step=step,
                started_at_monotonic=monotonic(),
            )

    def record_llm_call(
        self,
        task_id: str,
        *,
        duration_ms: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        with self._lock:
            rec = self._records.get(task_id)
            if rec is None:
                return
            rec.llm_call_count += 1
            rec.last_llm_call_at_monotonic = monotonic()
            rec.input_tokens += input_tokens
            rec.output_tokens += output_tokens

    def record_loop_detector_hit(self, task_id: str) -> None:
        with self._lock:
            rec = self._records.get(task_id)
            if rec is None:
                return
            rec.loop_detector_hits += 1

    def mark_completed(self, task_id: str, status: str = "completed") -> None:
        """``status`` values: ``completed`` / ``failed`` / ``aborted``."""
        with self._lock:
            rec = self._records.get(task_id)
            if rec is None:
                return
            rec.status = status

    # -- abort API (called from CLI / web) --

    def request_abort(self, task_id: str) -> bool:
        """Set the abort flag. Returns True if the task was found and
        marked, False if no such task is registered (likely already
        completed / never started)."""
        with self._lock:
            rec = self._records.get(task_id)
            if rec is None:
                return False
            rec.abort_requested = True
            return True

    def is_abort_requested(self, task_id: str) -> bool:
        with self._lock:
            rec = self._records.get(task_id)
            return rec is not None and rec.abort_requested

    # -- read API (called from web UI / CLI) --

    def active_tasks(self) -> list[TaskSnapshot]:
        """All currently-running tasks (status == 'running'), newest first."""
        with self._lock:
            now = monotonic()
            return sorted(
                (
                    rec.snapshot(now)
                    for rec in self._records.values()
                    if rec.status == "running"
                ),
                key=lambda s: -s.started_at_monotonic,
            )

    def get_snapshot(self, task_id: str) -> TaskSnapshot | None:
        with self._lock:
            rec = self._records.get(task_id)
            return rec.snapshot() if rec is not None else None

    def all_tasks(self) -> list[TaskSnapshot]:
        """Including completed/failed/aborted. For full audit views."""
        with self._lock:
            now = monotonic()
            return sorted(
                (rec.snapshot(now) for rec in self._records.values()),
                key=lambda s: -s.started_at_monotonic,
            )

    def clear(self) -> None:
        """Drop all records (tests + on session reset)."""
        with self._lock:
            self._records.clear()


# -- Process singleton ---------------------------------------------------


_REGISTRY: TaskRegistry = TaskRegistry()


def get_registry() -> TaskRegistry:
    """Return the process-global TaskRegistry singleton.

    Tests can call ``get_registry().clear()`` between cases."""
    return _REGISTRY


# -- Convenience helper that combines abort-check + raise ----------------


def check_abort(task_id: str) -> None:
    """Raise AbortRequested if the operator has requested abort.

    PhaseExecutor / dispatch_task should call this between LLM calls in
    their inner loop:

        for attempt in range(MAX_RETRIES):
            check_abort(task_id)
            result = handle_message(...)
            ...
    """
    if _REGISTRY.is_abort_requested(task_id):
        raise AbortRequested(f"task={task_id} aborted by operator")
