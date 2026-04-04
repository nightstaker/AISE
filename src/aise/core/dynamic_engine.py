"""AI-First Dynamic Workflow Engine — replaces static pipeline orchestration.

The DynamicEngine bridges the AIPlanner's ExecutionPlan with the actual
Agent/Skill execution system. Instead of the static:

    create_default_workflow → Phase → Task → executor

It provides:

    AIPlanner → ExecutionPlan → DynamicEngine.execute(plan) → results

Key differences from the static WorkflowEngine:
1. No hardcoded phase ordering — execution order comes from the plan
2. Automatic re-planning on failure (AIPlanner.replan())
3. Artifact-aware: skips steps whose outputs already exist
4. Progress tracking with per-step status and timing
5. Pluggable LLM for planning (separate from execution LLM)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ..utils.logging import get_logger
from .ai_planner import AIPlanner, ExecutionPlan, PlannerContext, PlanStep
from .artifact import ArtifactStore, ArtifactType
from .process_registry import ProcessRegistry

logger = get_logger(__name__)


class StepStatus(Enum):
    """Execution status of a single plan step."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepResult:
    """Result of executing a single plan step."""

    process_id: str
    agent: str
    status: StepStatus
    artifact_id: str | None = None
    error: str | None = None
    duration_seconds: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ExecutionResult:
    """Complete result of a dynamic workflow execution."""

    plan: ExecutionPlan
    step_results: list[StepResult]
    status: str  # "completed" | "partial" | "failed"
    total_duration_seconds: float = 0.0
    replans: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def completed_steps(self) -> list[StepResult]:
        return [r for r in self.step_results if r.status == StepStatus.COMPLETED]

    @property
    def failed_steps(self) -> list[StepResult]:
        return [r for r in self.step_results if r.status == StepStatus.FAILED]

    @property
    def artifact_ids(self) -> list[str]:
        return [r.artifact_id for r in self.step_results if r.artifact_id]


# Type for the executor function: (agent_name, skill_name, input_data, project_name) -> artifact_id
Executor = Callable[[str, str, dict[str, Any], str], str]


class DynamicEngine:
    """Execute AIPlanner-generated plans against the actual agent system.

    This is the AI-First replacement for the static WorkflowEngine.
    It takes an ExecutionPlan and drives it to completion, handling
    failures via re-planning.

    Usage:
        registry = ProcessRegistry.build_default()
        planner = AIPlanner.from_llm_client(registry, llm)
        engine = DynamicEngine(registry, planner, artifact_store)

        context = PlannerContext(user_requirements="Build a REST API")
        result = engine.run(context, executor, project_name="MyAPI")
    """

    def __init__(
        self,
        registry: ProcessRegistry,
        planner: AIPlanner,
        artifact_store: ArtifactStore,
        max_replans: int = 2,
    ) -> None:
        self.registry = registry
        self.planner = planner
        self.artifact_store = artifact_store
        self.max_replans = max_replans

    def run(
        self,
        context: PlannerContext,
        executor: Executor,
        project_name: str = "",
    ) -> ExecutionResult:
        """Run a complete AI-planned workflow.

        1. Generate plan from context
        2. Validate plan
        3. Execute steps in dependency order
        4. On failure: replan and continue
        5. Return complete results
        """
        start_time = time.monotonic()

        # Step 1: Generate initial plan
        plan = self.planner.generate_plan(context)
        logger.info(
            "Dynamic execution starting: goal=%s steps=%d project=%s",
            plan.goal,
            len(plan.steps),
            project_name,
        )

        # Step 2: Validate and auto-resolve missing dependencies
        plan = self._auto_resolve_dependencies(plan)
        errors = self.planner.validate_plan(plan)
        if errors:
            logger.warning("Plan validation warnings: %s", errors)
            # Try to fix or use fallback
            plan = self.planner._fallback_plan(context)

        # Step 3: Execute with replan loop
        all_results: list[StepResult] = []
        replans = 0
        current_plan = plan
        completed_artifacts: dict[ArtifactType, str] = dict(context.available_artifacts)

        while replans <= self.max_replans:
            results, failed_step = self._execute_plan(
                current_plan,
                executor,
                project_name,
                completed_artifacts,
            )
            all_results.extend(results)

            # Update completed artifacts
            for result in results:
                if result.status == StepStatus.COMPLETED and result.artifact_id:
                    proc = self.registry.get(result.process_id)
                    if proc:
                        for art_type in proc.output_artifact_types:
                            completed_artifacts[art_type] = result.artifact_id

            if failed_step is None:
                # All steps completed
                total_time = time.monotonic() - start_time
                logger.info(
                    "Dynamic execution completed: steps=%d artifacts=%d time=%.1fs",
                    len(all_results),
                    sum(1 for r in all_results if r.artifact_id),
                    total_time,
                )
                return ExecutionResult(
                    plan=plan,
                    step_results=all_results,
                    status="completed",
                    total_duration_seconds=total_time,
                    replans=replans,
                )

            # Replan
            replans += 1
            if replans > self.max_replans:
                break

            logger.info(
                "Replanning after failure: step=%s error=%s replan=%d/%d",
                failed_step.process_id,
                failed_step.error,
                replans,
                self.max_replans,
            )
            current_plan = self.planner.replan(
                original_plan=current_plan,
                failed_step_id=failed_step.process_id,
                error=failed_step.error or "Unknown error",
                completed_artifacts=completed_artifacts,
            )

        # Exhausted replans
        total_time = time.monotonic() - start_time
        completed_count = sum(1 for r in all_results if r.status == StepStatus.COMPLETED)
        status = "partial" if completed_count > 0 else "failed"

        logger.warning(
            "Dynamic execution ended with failures: status=%s completed=%d failed=%d replans=%d",
            status,
            completed_count,
            sum(1 for r in all_results if r.status == StepStatus.FAILED),
            replans,
        )
        return ExecutionResult(
            plan=plan,
            step_results=all_results,
            status=status,
            total_duration_seconds=total_time,
            replans=replans,
        )

    def run_with_plan(
        self,
        plan: ExecutionPlan,
        executor: Executor,
        project_name: str = "",
        available_artifacts: dict[ArtifactType, str] | None = None,
    ) -> ExecutionResult:
        """Execute a pre-generated plan (skip the planning step)."""
        start_time = time.monotonic()
        completed_artifacts = dict(available_artifacts or {})

        results, failed_step = self._execute_plan(
            plan,
            executor,
            project_name,
            completed_artifacts,
        )

        total_time = time.monotonic() - start_time
        if failed_step:
            status = "partial" if any(r.status == StepStatus.COMPLETED for r in results) else "failed"
        else:
            status = "completed"

        return ExecutionResult(
            plan=plan,
            step_results=results,
            status=status,
            total_duration_seconds=total_time,
        )

    def _execute_plan(
        self,
        plan: ExecutionPlan,
        executor: Executor,
        project_name: str,
        completed_artifacts: dict[ArtifactType, str],
    ) -> tuple[list[StepResult], StepResult | None]:
        """Execute plan steps in topological order.

        Returns:
            (results, failed_step) — failed_step is None if all succeeded.
        """
        ordered_steps = plan.execution_order()
        results: list[StepResult] = []
        completed_step_ids: set[str] = set()

        for step in ordered_steps:
            # Check if we can skip this step
            if self._should_skip(step, completed_artifacts):
                result = StepResult(
                    process_id=step.process_id,
                    agent=step.agent,
                    status=StepStatus.SKIPPED,
                    metadata={"reason": "output artifacts already available"},
                )
                results.append(result)
                completed_step_ids.add(step.process_id)
                logger.info("Step skipped (artifacts exist): %s", step.process_id)
                continue

            # Check dependencies are satisfied
            deps_ok = all(d in completed_step_ids for d in step.depends_on_steps)
            if not deps_ok:
                result = StepResult(
                    process_id=step.process_id,
                    agent=step.agent,
                    status=StepStatus.SKIPPED,
                    metadata={"reason": "unmet dependencies"},
                )
                results.append(result)
                logger.warning(
                    "Step skipped (unmet deps): %s depends_on=%s completed=%s",
                    step.process_id,
                    step.depends_on_steps,
                    completed_step_ids,
                )
                continue

            # Execute the step
            result = self._execute_step(step, executor, project_name, completed_artifacts)
            results.append(result)

            if result.status == StepStatus.COMPLETED:
                completed_step_ids.add(step.process_id)
                # Track produced artifacts
                if result.artifact_id:
                    proc = self.registry.get(step.process_id)
                    if proc:
                        for art_type in proc.output_artifact_types:
                            completed_artifacts[art_type] = result.artifact_id
            elif result.status == StepStatus.FAILED:
                return results, result

        return results, None

    def _execute_step(
        self,
        step: PlanStep,
        executor: Executor,
        project_name: str,
        completed_artifacts: dict[ArtifactType, str],
    ) -> StepResult:
        """Execute a single plan step."""
        proc = self.registry.get(step.process_id)
        if proc is None:
            return StepResult(
                process_id=step.process_id,
                agent=step.agent,
                status=StepStatus.FAILED,
                error=f"Process '{step.process_id}' not found in registry",
            )

        # Build input data from input_mapping and available artifacts
        input_data = dict(step.input_mapping)
        for art_type, art_id in completed_artifacts.items():
            # Auto-inject available artifacts by type name
            input_data.setdefault(art_type.value, art_id)

        logger.info(
            "Step executing: process=%s agent=%s input_keys=%s",
            step.process_id,
            step.agent,
            sorted(input_data.keys()),
        )

        start_time = time.monotonic()
        try:
            artifact_id = executor(step.agent, step.process_id, input_data, project_name)
            duration = time.monotonic() - start_time
            logger.info(
                "Step completed: process=%s agent=%s artifact=%s time=%.1fs",
                step.process_id,
                step.agent,
                artifact_id,
                duration,
            )
            return StepResult(
                process_id=step.process_id,
                agent=step.agent,
                status=StepStatus.COMPLETED,
                artifact_id=artifact_id,
                duration_seconds=duration,
            )
        except Exception as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "Step failed: process=%s agent=%s error=%s time=%.1fs",
                step.process_id,
                step.agent,
                exc,
                duration,
            )
            return StepResult(
                process_id=step.process_id,
                agent=step.agent,
                status=StepStatus.FAILED,
                error=str(exc),
                duration_seconds=duration,
            )

    def _auto_resolve_dependencies(
        self,
        plan: ExecutionPlan,
    ) -> ExecutionPlan:
        """Check each step's artifact dependencies and prepend missing producers.

        If the plan jumps straight to architecture without requirements,
        this will auto-insert the requirements step.
        """
        available = set()  # Track what artifacts the plan will produce
        existing_process_ids = {s.process_id for s in plan.steps}
        prepend: list[PlanStep] = []
        prepend_ids: set[str] = set()

        for step in plan.steps:
            proc = self.registry.get(step.process_id)
            if proc is None:
                continue

            for dep_art in proc.depends_on_artifacts:
                if dep_art not in available:
                    # Need a producer — find one
                    chain = self.registry.resolve_dependency_chain(dep_art, available.copy())
                    for p in chain:
                        if p.id not in existing_process_ids and p.id not in prepend_ids:
                            logger.info(
                                "Auto-resolving dependency: %s needs %s, adding %s",
                                step.process_id,
                                dep_art.value,
                                p.id,
                            )
                            agent = p.agent_roles[0] if p.agent_roles else "developer"
                            arts = [a.value for a in p.output_artifact_types]
                            prepend.append(
                                PlanStep(
                                    process_id=p.id,
                                    agent=agent,
                                    rationale=f"Auto-resolved: produces {arts}",
                                    input_mapping={},
                                    depends_on_steps=[],
                                )
                            )
                            prepend_ids.add(p.id)
                            for a in p.output_artifact_types:
                                available.add(a)

            for a in proc.output_artifact_types:
                available.add(a)

        if prepend:
            logger.info(
                "Auto-resolved %d missing dependency steps: %s",
                len(prepend),
                [s.process_id for s in prepend],
            )
            # Fix depends_on for original steps
            all_new_ids = {s.process_id for s in prepend}
            for step in plan.steps:
                proc = self.registry.get(step.process_id)
                if proc:
                    for dep_art in proc.depends_on_artifacts:
                        producers = self.registry.find_producers(dep_art)
                        for p in producers:
                            if p.id in all_new_ids and p.id not in step.depends_on_steps:
                                step.depends_on_steps.append(p.id)

            return ExecutionPlan(
                goal=plan.goal,
                steps=prepend + plan.steps,
                reasoning=plan.reasoning + f" (auto-resolved {len(prepend)} missing dependencies)",
            )

        return plan

    def _should_skip(
        self,
        step: PlanStep,
        completed_artifacts: dict[ArtifactType, str],
    ) -> bool:
        """Check if a step can be skipped because its outputs already exist."""
        proc = self.registry.get(step.process_id)
        if proc is None:
            return False

        # Skip if ALL output artifacts are already available
        if not proc.output_artifact_types:
            return False

        return all(art_type in completed_artifacts for art_type in proc.output_artifact_types)
