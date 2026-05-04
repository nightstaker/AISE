"""Dataclasses for the waterfall_v2 process spec.

These mirror ``src/aise/processes/waterfall_v2.process.md`` and
``src/aise/schemas/process_v2.schema.json``. PhaseExecutor (commit c3)
walks instances of these.

Kept distinct from the legacy ``ProcessDefinition`` in
``runtime/models.py`` so the v1 parser keeps working unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# -- Acceptance predicates ------------------------------------------------


@dataclass(frozen=True)
class AcceptancePredicate:
    """One acceptance predicate row.

    Source forms:
      - bare string: ``"file_exists"`` → kind="file_exists", arg=None
      - one-key dict: ``{"min_bytes": 2000}`` → kind="min_bytes", arg=2000
      - one-key dict with object arg:
        ``{"contains_sections": ["A", "B"]}`` → kind="contains_sections",
        arg=["A", "B"]
    """

    kind: str
    arg: Any = None


# -- Deliverables ---------------------------------------------------------


@dataclass(frozen=True)
class Deliverable:
    """One deliverable artifact for a phase."""

    kind: str  # "document" | "contract" | "derived"
    path: str | None = None  # for kind=document/contract
    from_: str | None = None  # for kind=derived; source contract name
    rule: str | None = None  # for kind=derived; rule key
    acceptance: tuple[AcceptancePredicate, ...] = field(default_factory=tuple)


# -- Concurrency / fanout -------------------------------------------------


@dataclass(frozen=True)
class ConcurrencyPolicy:
    max_workers: int
    per_task_retries: int
    join_policy: str = "ALL_PASS"
    on_task_failure_after_retries: str = "phase_halt"


@dataclass(frozen=True)
class FanoutStage:
    id: str
    concurrency: ConcurrencyPolicy
    tier: str = "T1"  # T1 / T2 / T3
    depends_on: str | None = None
    group_by: str | None = None
    mode_when_runner_unavailable: str | None = None  # "write_only"|"skip"|"fail"|None


@dataclass(frozen=True)
class FanoutSpec:
    strategy: str  # subsystem_dag / scenario_parallel / flat_parallel
    source_jsonpath: str
    stages: tuple[FanoutStage, ...]


# -- Review ---------------------------------------------------------------


@dataclass(frozen=True)
class ReviewSpec:
    consensus: str = "ALL_PASS"
    revise_budget: int = 3
    on_revise_exhausted: str = "continue_with_marker"
    reviewer_questions: dict[str, str] = field(default_factory=dict)


# -- Phase ----------------------------------------------------------------


@dataclass(frozen=True)
class PhaseSpec:
    id: str
    producer: str
    deliverables: tuple[Deliverable, ...]
    title: str = ""
    reviewer: tuple[str, ...] = field(default_factory=tuple)
    inputs: tuple[str, ...] = field(default_factory=tuple)
    fanout: FanoutSpec | None = None
    review: ReviewSpec | None = None

    @property
    def has_fanout(self) -> bool:
        return self.fanout is not None

    @property
    def has_reviewer(self) -> bool:
        return bool(self.reviewer)

    @property
    def is_single_writer(self) -> bool:
        return not self.has_fanout


# -- Process --------------------------------------------------------------


@dataclass(frozen=True)
class WaterfallV2Spec:
    process_id: str
    phases: tuple[PhaseSpec, ...]
    name: str = ""
    summary: str = ""
    schema_version: int = 2
    terminal_phase: str = ""
    quality_profile: str = "balanced"
    metadata: dict[str, Any] = field(default_factory=dict)

    def phase_by_id(self, phase_id: str) -> PhaseSpec | None:
        for p in self.phases:
            if p.id == phase_id:
                return p
        return None

    def phase_index(self, phase_id: str) -> int | None:
        for i, p in enumerate(self.phases):
            if p.id == phase_id:
                return i
        return None

    def next_phase(self, phase_id: str) -> PhaseSpec | None:
        idx = self.phase_index(phase_id)
        if idx is None or idx + 1 >= len(self.phases):
            return None
        return self.phases[idx + 1]
