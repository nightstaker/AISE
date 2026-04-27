"""Workflow and pipeline engine for orchestrating development phases."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..utils.logging import get_logger

logger = get_logger(__name__)


class PhaseStatus(Enum):
    """Status of a workflow phase."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    IN_REVIEW = "in_review"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Task:
    """A single task within a phase."""

    agent: str
    skill: str
    input_data: dict[str, Any] = field(default_factory=dict)
    depends_on: list[str] = field(default_factory=list)
    status: PhaseStatus = PhaseStatus.PENDING
    result_artifact_id: str | None = None

    @property
    def key(self) -> str:
        return f"{self.agent}.{self.skill}"


@dataclass
class ReviewGate:
    """A review checkpoint between phases."""

    reviewer_agent: str
    review_skill: str
    target_artifact_type: str
    min_review_rounds: int = 1
    max_iterations: int = 3


@dataclass
class Phase:
    """A phase in the development pipeline."""

    name: str
    tasks: list[Task] = field(default_factory=list)
    review_gate: ReviewGate | None = None
    status: PhaseStatus = PhaseStatus.PENDING

    def add_task(self, agent: str, skill: str, input_data: dict[str, Any] | None = None) -> Task:
        task = Task(agent=agent, skill=skill, input_data=input_data or {})
        self.tasks.append(task)
        return task


@dataclass
class Workflow:
    """A complete development workflow composed of ordered phases."""

    name: str
    phases: list[Phase] = field(default_factory=list)
    current_phase_index: int = 0

    def add_phase(self, phase: Phase) -> None:
        self.phases.append(phase)

    @property
    def current_phase(self) -> Phase | None:
        if 0 <= self.current_phase_index < len(self.phases):
            return self.phases[self.current_phase_index]
        return None

    @property
    def is_complete(self) -> bool:
        return self.current_phase_index >= len(self.phases)

    def advance(self) -> Phase | None:
        """Move to the next phase. Returns the new current phase or None if done."""
        self.current_phase_index += 1
        return self.current_phase


class WorkflowEngine:
    """Executes workflows by dispatching tasks to agents via the orchestrator."""

    def __init__(self) -> None:
        self._workflows: dict[str, Workflow] = {}

    def register_workflow(self, workflow: Workflow) -> None:
        self._workflows[workflow.name] = workflow

    def get_workflow(self, name: str) -> Workflow | None:
        return self._workflows.get(name)

    def execute_phase(self, workflow: Workflow, executor) -> dict[str, Any]:
        """Execute the current phase of a workflow.

        Args:
            workflow: The workflow to execute.
            executor: Callable(agent_name, skill_name, input_data) -> artifact_id

        Returns:
            Dict with phase results.
        """
        phase = workflow.current_phase
        if phase is None:
            return {"status": "complete", "message": "Workflow is complete"}

        # Validate and resolve task dependencies before execution
        ordered_tasks = self._topological_sort_tasks(phase.tasks)

        phase.status = PhaseStatus.IN_PROGRESS
        results = {}
        logger.info(
            "Phase execution started: workflow=%s phase=%s tasks=%d", workflow.name, phase.name, len(ordered_tasks)
        )

        for task in ordered_tasks:
            task.status = PhaseStatus.IN_PROGRESS
            logger.debug("Phase task started: task=%s", task.key)
            try:
                artifact_id = executor(task.agent, task.skill, task.input_data)
                task.result_artifact_id = artifact_id
                task.status = PhaseStatus.COMPLETED
                results[task.key] = {"status": "success", "artifact_id": artifact_id}
                logger.info("Phase task completed: task=%s artifact_id=%s", task.key, artifact_id)
            except Exception as e:
                task.status = PhaseStatus.FAILED
                results[task.key] = {"status": "error", "error": str(e)}
                logger.warning("Phase task failed: task=%s error=%s", task.key, str(e))

        all_succeeded = all(t.status == PhaseStatus.COMPLETED for t in phase.tasks)

        if all_succeeded and phase.review_gate:
            phase.status = PhaseStatus.IN_REVIEW
        elif all_succeeded:
            phase.status = PhaseStatus.COMPLETED
        else:
            phase.status = PhaseStatus.FAILED

        logger.info("Phase execution finished: phase=%s status=%s", phase.name, phase.status.value)
        return {"phase": phase.name, "status": phase.status.value, "tasks": results}

    def _topological_sort_tasks(self, tasks: list[Task]) -> list[Task]:
        """Sort tasks topologically based on their dependencies.

        Uses Kahn's algorithm for topological sorting with cycle detection.

        Args:
            tasks: List of tasks to sort

        Returns:
            Tasks sorted in execution order respecting dependencies

        Raises:
            ValueError: If circular dependency or missing dependency is detected
        """
        if not tasks:
            return []

        # Build task key to task mapping and validate dependencies
        task_map = {task.key: task for task in tasks}

        # Validate all dependencies exist
        self._validate_dependencies_exist(tasks, task_map)

        # Build adjacency list and in-degree count
        graph: dict[str, list[str]] = {task.key: [] for task in tasks}
        in_degree: dict[str, int] = {task.key: 0 for task in tasks}

        for task in tasks:
            for dep_key in task.depends_on:
                graph[dep_key].append(task.key)
                in_degree[task.key] += 1

        # Kahn's algorithm
        queue = [key for key, degree in in_degree.items() if degree == 0]
        sorted_tasks: list[Task] = []

        while queue:
            queue.sort()
            current_key = queue.pop(0)
            current_task = task_map[current_key]
            sorted_tasks.append(current_task)

            for dependent_key in graph[current_key]:
                in_degree[dependent_key] -= 1
                if in_degree[dependent_key] == 0:
                    queue.append(dependent_key)

        if len(sorted_tasks) != len(tasks):
            cycle_tasks = [key for key, degree in in_degree.items() if degree > 0]
            raise ValueError(
                f"Circular dependency detected in tasks: {', '.join(sorted(cycle_tasks))}. "
                "A task cannot depend on itself directly or indirectly."
            )

        logger.debug(
            "Tasks sorted topologically: phase_tasks=%d execution_order=%s",
            len(tasks),
            " -> ".join(t.key for t in sorted_tasks),
        )
        return sorted_tasks

    def _validate_dependencies_exist(self, tasks: list[Task], task_map: dict[str, Task]) -> None:
        """Validate that all declared dependencies reference existing tasks."""
        for task in tasks:
            for dep_key in task.depends_on:
                if dep_key not in task_map:
                    raise ValueError(
                        f"Task '{task.key}' has a missing dependency '{dep_key}'. "
                        f"Available tasks: {', '.join(sorted(task_map.keys()))}"
                    )

    def run_review(self, workflow: Workflow, executor) -> dict[str, Any]:
        """Run the review gate for the current phase.

        Executes at least ``gate.min_review_rounds`` review iterations
        (up to ``gate.max_iterations``).  Each round invokes the review
        skill; if the reviewer raises an exception the loop stops early
        and the review is marked as not approved.

        Returns:
            Dict with review results including 'approved' boolean,
            'rounds_completed' count, and per-round details.
        """
        phase = workflow.current_phase
        if phase is None or phase.review_gate is None:
            return {"approved": True, "rounds_completed": 0}

        gate = phase.review_gate
        rounds: list[dict[str, Any]] = []
        approved = False

        iterations = max(gate.min_review_rounds, 1)
        iterations = min(iterations, gate.max_iterations)

        for round_num in range(1, iterations + 1):
            try:
                logger.info(
                    "Review round started: workflow=%s phase=%s round=%d reviewer=%s skill=%s",
                    workflow.name,
                    phase.name,
                    round_num,
                    gate.reviewer_agent,
                    gate.review_skill,
                )
                artifact_id = executor(
                    gate.reviewer_agent,
                    gate.review_skill,
                    {
                        "target_artifact_type": gate.target_artifact_type,
                        "review_round": round_num,
                    },
                )
                rounds.append({"round": round_num, "status": "success", "artifact_id": artifact_id})
                approved = True
                logger.info(
                    "Review round completed: phase=%s round=%d artifact_id=%s", phase.name, round_num, artifact_id
                )
            except Exception as e:
                rounds.append({"round": round_num, "status": "failed", "error": str(e)})
                approved = False
                logger.warning("Review round failed: phase=%s round=%d error=%s", phase.name, round_num, str(e))
                break

        if approved:
            phase.status = PhaseStatus.COMPLETED

        result = {
            "approved": approved,
            "rounds_completed": len(rounds),
            "rounds": rounds,
        }
        logger.info(
            "Review gate finished: workflow=%s phase=%s approved=%s rounds=%d",
            workflow.name,
            phase.name,
            approved,
            len(rounds),
        )
        return result

    @staticmethod
    def create_default_workflow() -> Workflow:
        """Create the standard software development workflow."""
        workflow = Workflow(name="default_sdlc")

        # Phase 1: Requirements (Product Manager owned)
        p1 = Phase(name="requirements")
        p1.add_task("product_manager", "deep_product_workflow", {"output_dir": "docs"})
        workflow.add_phase(p1)

        # Phase 2: Architecture & Design (Architect owned)
        p2 = Phase(name="design")
        p2.add_task("architect", "deep_architecture_workflow", {"output_dir": "docs", "source_dir": "src"})
        workflow.add_phase(p2)

        # Phase 3: Implementation
        p3 = Phase(name="implementation")
        p3.add_task("developer", "code_generation", {"source_dir": "src"})
        p3.review_gate = ReviewGate(
            reviewer_agent="developer",
            review_skill="code_review",
            target_artifact_type="source_code",
        )
        workflow.add_phase(p3)

        # Phase 4: Testing
        p4 = Phase(name="testing")
        p4.add_task("qa_engineer", "test_plan_design")
        p4.add_task("qa_engineer", "test_case_design")
        p4.add_task("qa_engineer", "test_automation")
        p4.review_gate = ReviewGate(
            reviewer_agent="qa_engineer",
            review_skill="test_review",
            target_artifact_type="automated_tests",
        )
        workflow.add_phase(p4)

        return workflow
