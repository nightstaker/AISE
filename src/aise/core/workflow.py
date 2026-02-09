"""Workflow and pipeline engine for orchestrating development phases."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


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
    max_iterations: int = 3


@dataclass
class Phase:
    """A phase in the development pipeline."""

    name: str
    tasks: list[Task] = field(default_factory=list)
    review_gate: ReviewGate | None = None
    status: PhaseStatus = PhaseStatus.PENDING

    def add_task(
        self, agent: str, skill: str, input_data: dict[str, Any] | None = None
    ) -> Task:
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

        phase.status = PhaseStatus.IN_PROGRESS
        results = {}

        for task in phase.tasks:
            task.status = PhaseStatus.IN_PROGRESS
            try:
                artifact_id = executor(task.agent, task.skill, task.input_data)
                task.result_artifact_id = artifact_id
                task.status = PhaseStatus.COMPLETED
                results[task.key] = {"status": "success", "artifact_id": artifact_id}
            except Exception as e:
                task.status = PhaseStatus.FAILED
                results[task.key] = {"status": "error", "error": str(e)}

        all_succeeded = all(t.status == PhaseStatus.COMPLETED for t in phase.tasks)

        if all_succeeded and phase.review_gate:
            phase.status = PhaseStatus.IN_REVIEW
        elif all_succeeded:
            phase.status = PhaseStatus.COMPLETED
        else:
            phase.status = PhaseStatus.FAILED

        return {"phase": phase.name, "status": phase.status.value, "tasks": results}

    def run_review(self, workflow: Workflow, executor) -> dict[str, Any]:
        """Run the review gate for the current phase.

        Returns:
            Dict with review results including 'approved' boolean.
        """
        phase = workflow.current_phase
        if phase is None or phase.review_gate is None:
            return {"approved": True}

        gate = phase.review_gate
        try:
            artifact_id = executor(
                gate.reviewer_agent,
                gate.review_skill,
                {
                    "target_artifact_type": gate.target_artifact_type,
                },
            )
            phase.status = PhaseStatus.COMPLETED
            return {"approved": True, "artifact_id": artifact_id}
        except Exception as e:
            return {"approved": False, "error": str(e)}

    @staticmethod
    def create_default_workflow() -> Workflow:
        """Create the standard software development workflow."""
        workflow = Workflow(name="default_sdlc")

        # Phase 1: Requirements
        p1 = Phase(name="requirements")
        p1.add_task("product_manager", "requirement_analysis")
        p1.add_task("product_manager", "user_story_writing")
        p1.add_task("product_manager", "product_design")
        p1.review_gate = ReviewGate(
            reviewer_agent="product_manager",
            review_skill="product_review",
            target_artifact_type="prd",
        )
        workflow.add_phase(p1)

        # Phase 2: Architecture & Design
        p2 = Phase(name="design")
        p2.add_task("architect", "system_design")
        p2.add_task("architect", "api_design")
        p2.add_task("architect", "tech_stack_selection")
        p2.review_gate = ReviewGate(
            reviewer_agent="architect",
            review_skill="architecture_review",
            target_artifact_type="architecture_design",
        )
        workflow.add_phase(p2)

        # Phase 3: Implementation
        p3 = Phase(name="implementation")
        p3.add_task("developer", "code_generation")
        p3.add_task("developer", "unit_test_writing")
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
