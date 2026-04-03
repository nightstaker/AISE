"""Tests for the AI-First Dynamic Workflow Engine."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

from aise.core.ai_planner import AIPlanner, ExecutionPlan, PlannerContext, PlanStep
from aise.core.artifact import ArtifactStore, ArtifactType
from aise.core.dynamic_engine import DynamicEngine, ExecutionResult, StepResult, StepStatus
from aise.core.process_registry import ProcessCapability, ProcessDescriptor, ProcessRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _build_test_registry() -> ProcessRegistry:
    """Build a minimal registry for testing."""
    registry = ProcessRegistry()

    registry.register(
        ProcessDescriptor(
            id="requirement_analysis",
            name="Requirement Analysis",
            description="Analyze requirements",
            agent_roles=["product_manager"],
            phase_affinity=["requirements"],
            input_keys=["raw_requirements"],
            output_artifact_types=[ArtifactType.REQUIREMENTS],
            capabilities=[ProcessCapability.ANALYSIS],
        )
    )
    registry.register(
        ProcessDescriptor(
            id="system_design",
            name="System Design",
            description="Create architecture",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=["requirements"],
            output_artifact_types=[ArtifactType.ARCHITECTURE_DESIGN],
            capabilities=[ProcessCapability.DESIGN],
            depends_on_artifacts=[ArtifactType.REQUIREMENTS],
        )
    )
    registry.register(
        ProcessDescriptor(
            id="code_generation",
            name="Code Generation",
            description="Generate code",
            agent_roles=["developer"],
            phase_affinity=["implementation"],
            input_keys=["requirements"],
            output_artifact_types=[ArtifactType.SOURCE_CODE],
            capabilities=[ProcessCapability.GENERATION],
            depends_on_artifacts=[ArtifactType.ARCHITECTURE_DESIGN],
        )
    )
    return registry


def _build_simple_plan() -> ExecutionPlan:
    """Build a simple 3-step plan for testing."""
    return ExecutionPlan(
        goal="Build a system",
        steps=[
            PlanStep(
                process_id="requirement_analysis",
                agent="product_manager",
                rationale="Analyze reqs first",
            ),
            PlanStep(
                process_id="system_design",
                agent="architect",
                rationale="Then design",
                depends_on_steps=["requirement_analysis"],
            ),
            PlanStep(
                process_id="code_generation",
                agent="developer",
                rationale="Then implement",
                depends_on_steps=["system_design"],
            ),
        ],
        reasoning="Standard SDLC flow",
    )


def _mock_executor(results: dict[str, str | Exception]) -> Any:
    """Create a mock executor that returns predefined results."""

    def executor(agent: str, skill: str, input_data: dict, project_name: str) -> str:
        result = results.get(skill)
        if isinstance(result, Exception):
            raise result
        return result or f"artifact_{skill}"

    return executor


def _mock_planner(plan: ExecutionPlan) -> AIPlanner:
    """Create a mock AIPlanner that returns a fixed plan."""
    registry = _build_test_registry()
    planner = AIPlanner(registry=registry)
    planner.generate_plan = MagicMock(return_value=plan)
    planner.validate_plan = MagicMock(return_value=[])
    planner.replan = MagicMock(return_value=plan)
    return planner


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestStepResult:
    def test_basic_creation(self):
        result = StepResult(
            process_id="test",
            agent="dev",
            status=StepStatus.COMPLETED,
            artifact_id="art_123",
        )
        assert result.process_id == "test"
        assert result.status == StepStatus.COMPLETED
        assert result.artifact_id == "art_123"

    def test_failed_result(self):
        result = StepResult(
            process_id="test",
            agent="dev",
            status=StepStatus.FAILED,
            error="Something broke",
        )
        assert result.status == StepStatus.FAILED
        assert result.error == "Something broke"


class TestExecutionResult:
    def test_completed_steps(self):
        result = ExecutionResult(
            plan=_build_simple_plan(),
            step_results=[
                StepResult("a", "dev", StepStatus.COMPLETED, "art_1"),
                StepResult("b", "dev", StepStatus.FAILED, error="err"),
                StepResult("c", "dev", StepStatus.SKIPPED),
            ],
            status="partial",
        )
        assert len(result.completed_steps) == 1
        assert len(result.failed_steps) == 1
        assert result.artifact_ids == ["art_1"]


class TestDynamicEngineExecution:
    """Test the core execution loop of DynamicEngine."""

    def test_successful_full_execution(self):
        """All 3 steps succeed in dependency order."""
        registry = _build_test_registry()
        planner = _mock_planner(_build_simple_plan())
        store = ArtifactStore()
        engine = DynamicEngine(registry, planner, store)

        executor = _mock_executor(
            {
                "requirement_analysis": "art_req",
                "system_design": "art_design",
                "code_generation": "art_code",
            }
        )
        context = PlannerContext(user_requirements="Build something")
        result = engine.run(context, executor, "TestProject")

        assert result.status == "completed"
        assert len(result.completed_steps) == 3
        assert result.replans == 0
        assert "art_req" in result.artifact_ids
        assert "art_design" in result.artifact_ids
        assert "art_code" in result.artifact_ids

    def test_step_failure_triggers_replan(self):
        """When a step fails, engine replans and retries."""
        registry = _build_test_registry()
        store = ArtifactStore()

        # First plan has 3 steps, design fails
        first_plan = _build_simple_plan()

        # Recovery plan has only the design + code steps
        recovery_plan = ExecutionPlan(
            goal="Recovery",
            steps=[
                PlanStep("system_design", "architect", "retry design"),
                PlanStep("code_generation", "developer", "then code", depends_on_steps=["system_design"]),
            ],
            reasoning="Recovery after design failure",
        )

        planner = AIPlanner(registry=registry)
        planner.generate_plan = MagicMock(return_value=first_plan)
        planner.validate_plan = MagicMock(return_value=[])
        planner.replan = MagicMock(return_value=recovery_plan)

        call_count = {"system_design": 0}

        def executor(agent, skill, input_data, project_name):
            if skill == "system_design":
                call_count["system_design"] += 1
                if call_count["system_design"] == 1:
                    raise RuntimeError("Design failed")
            return f"art_{skill}"

        context = PlannerContext(user_requirements="Build something")
        result = engine = DynamicEngine(registry, planner, store, max_replans=2)
        result = engine.run(context, executor, "TestProject")

        assert result.replans >= 1
        planner.replan.assert_called_once()

    def test_exhausted_replans_returns_partial(self):
        """After max replans, engine returns partial/failed status."""
        registry = _build_test_registry()
        store = ArtifactStore()

        plan = ExecutionPlan(
            goal="Test",
            steps=[PlanStep("requirement_analysis", "product_manager", "analyze")],
            reasoning="Simple plan",
        )

        planner = AIPlanner(registry=registry)
        planner.generate_plan = MagicMock(return_value=plan)
        planner.validate_plan = MagicMock(return_value=[])
        planner.replan = MagicMock(return_value=plan)

        def failing_executor(agent, skill, input_data, project_name):
            raise RuntimeError("Always fails")

        engine = DynamicEngine(registry, planner, store, max_replans=1)
        context = PlannerContext(user_requirements="fail test")
        result = engine.run(context, failing_executor, "TestProject")

        assert result.status == "failed"
        assert result.replans <= 2  # initial attempt + up to max_replans retries
        assert len(result.failed_steps) >= 1

    def test_skip_steps_with_existing_artifacts(self):
        """Steps whose output artifacts exist are skipped."""
        registry = _build_test_registry()
        store = ArtifactStore()

        plan = _build_simple_plan()
        planner = _mock_planner(plan)

        # Requirements already available
        context = PlannerContext(
            user_requirements="Build something",
            available_artifacts={ArtifactType.REQUIREMENTS: "existing_req_id"},
        )

        executor = _mock_executor(
            {
                "system_design": "art_design",
                "code_generation": "art_code",
            }
        )

        engine = DynamicEngine(registry, planner, store)
        result = engine.run(context, executor, "TestProject")

        assert result.status == "completed"
        # requirement_analysis should be skipped
        skipped = [r for r in result.step_results if r.status == StepStatus.SKIPPED]
        assert len(skipped) >= 1
        assert skipped[0].process_id == "requirement_analysis"

    def test_dependency_order_enforced(self):
        """Steps execute in topological order respecting dependencies."""
        registry = _build_test_registry()
        store = ArtifactStore()

        plan = _build_simple_plan()
        planner = _mock_planner(plan)

        execution_order = []

        def tracking_executor(agent, skill, input_data, project_name):
            execution_order.append(skill)
            return f"art_{skill}"

        context = PlannerContext(user_requirements="Build something")
        engine = DynamicEngine(registry, planner, store)
        engine.run(context, tracking_executor, "TestProject")

        assert execution_order == [
            "requirement_analysis",
            "system_design",
            "code_generation",
        ]


class TestDynamicEngineRunWithPlan:
    """Test run_with_plan (skip planning step)."""

    def test_run_with_prebuilt_plan(self):
        registry = _build_test_registry()
        store = ArtifactStore()
        planner = _mock_planner(_build_simple_plan())
        engine = DynamicEngine(registry, planner, store)

        executor = _mock_executor(
            {
                "requirement_analysis": "art_req",
                "system_design": "art_design",
                "code_generation": "art_code",
            }
        )

        plan = _build_simple_plan()
        result = engine.run_with_plan(plan, executor, "TestProject")

        assert result.status == "completed"
        assert len(result.completed_steps) == 3

    def test_run_with_plan_and_existing_artifacts(self):
        """Pre-available artifacts cause steps to be skipped."""
        registry = _build_test_registry()
        store = ArtifactStore()
        planner = _mock_planner(_build_simple_plan())
        engine = DynamicEngine(registry, planner, store)

        executor = _mock_executor(
            {
                "code_generation": "art_code",
            }
        )

        plan = _build_simple_plan()
        result = engine.run_with_plan(
            plan,
            executor,
            "TestProject",
            available_artifacts={
                ArtifactType.REQUIREMENTS: "existing_req",
                ArtifactType.ARCHITECTURE_DESIGN: "existing_arch",
            },
        )

        assert result.status == "completed"
        skipped = [r for r in result.step_results if r.status == StepStatus.SKIPPED]
        assert len(skipped) == 2  # req analysis + system design skipped


class TestDynamicEngineEdgeCases:
    """Edge cases and error handling."""

    def test_unknown_process_in_plan(self):
        """Plan referencing unknown process returns failed step."""
        registry = _build_test_registry()
        store = ArtifactStore()

        plan = ExecutionPlan(
            goal="Test",
            steps=[PlanStep("nonexistent_process", "dev", "do something")],
            reasoning="Bad plan",
        )
        planner = _mock_planner(plan)
        engine = DynamicEngine(registry, planner, store)

        executor = _mock_executor({})
        result = engine.run_with_plan(plan, executor, "Test")

        assert len(result.failed_steps) == 1
        assert "not found" in result.failed_steps[0].error

    def test_unmet_dependencies_skip_step(self):
        """Steps with unmet dependencies are skipped."""
        registry = _build_test_registry()
        store = ArtifactStore()

        # code_generation depends on system_design, but system_design not in plan
        plan = ExecutionPlan(
            goal="Test",
            steps=[
                PlanStep("code_generation", "developer", "code it", depends_on_steps=["system_design"]),
            ],
            reasoning="Incomplete plan",
        )
        planner = _mock_planner(plan)
        engine = DynamicEngine(registry, planner, store)

        executor = _mock_executor({})
        result = engine.run_with_plan(plan, executor, "Test")

        skipped = [r for r in result.step_results if r.status == StepStatus.SKIPPED]
        assert len(skipped) == 1
        assert "unmet" in skipped[0].metadata.get("reason", "")

    def test_empty_plan(self):
        """Empty plan completes immediately."""
        registry = _build_test_registry()
        store = ArtifactStore()

        plan = ExecutionPlan(goal="Nothing", steps=[], reasoning="Empty")
        planner = _mock_planner(plan)
        engine = DynamicEngine(registry, planner, store)

        executor = _mock_executor({})
        result = engine.run_with_plan(plan, executor, "Test")

        assert result.status == "completed"
        assert len(result.step_results) == 0

    def test_duration_tracking(self):
        """Each step tracks execution duration."""
        registry = _build_test_registry()
        store = ArtifactStore()

        plan = ExecutionPlan(
            goal="Test",
            steps=[PlanStep("requirement_analysis", "product_manager", "analyze")],
            reasoning="Timing test",
        )
        planner = _mock_planner(plan)
        engine = DynamicEngine(registry, planner, store)

        executor = _mock_executor({"requirement_analysis": "art_req"})
        result = engine.run_with_plan(plan, executor, "Test")

        assert result.step_results[0].duration_seconds >= 0
        assert result.total_duration_seconds >= 0
