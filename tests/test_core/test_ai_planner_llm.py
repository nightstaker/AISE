"""Tests for AIPlanner with real LLM integration.

Verifies that AIPlanner can:
1. Accept a LLMClient instance and generate plans via LLM
2. Handle reasoning model responses (thinking prefix before JSON)
3. Recover gracefully from malformed LLM output
4. Generate correct prompts with catalog, context, and constraints
5. Replan after step failure with completed artifact context
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock

from aise.core.ai_planner import AIPlanner, ExecutionPlan, PlannerContext, PlanStep
from aise.core.artifact import ArtifactType
from aise.core.process_registry import ProcessRegistry

# ── Fixtures ──────────────────────────────────────────────────────────────


def _make_registry() -> ProcessRegistry:
    return ProcessRegistry.build_default()


def _mock_llm_client(response: str) -> MagicMock:
    """Create a mock LLMClient that returns the given response."""
    client = MagicMock()
    client.complete.return_value = response
    return client


def _valid_plan_json(
    goal: str = "Build a snake game",
    steps: list[dict[str, Any]] | None = None,
) -> str:
    if steps is None:
        steps = [
            {
                "process_id": "deep_product_workflow",
                "agent": "product_manager",
                "rationale": "Analyze requirements comprehensively",
                "input_mapping": {},
                "depends_on_steps": [],
            },
            {
                "process_id": "deep_architecture_workflow",
                "agent": "architect",
                "rationale": "Design system architecture based on requirements",
                "input_mapping": {},
                "depends_on_steps": ["deep_product_workflow"],
            },
            {
                "process_id": "deep_developer_workflow",
                "agent": "developer",
                "rationale": "Implement the designed system",
                "input_mapping": {},
                "depends_on_steps": ["deep_architecture_workflow"],
            },
        ]
    return json.dumps(
        {"goal": goal, "reasoning": "Standard SDLC flow", "steps": steps},
        ensure_ascii=False,
    )


# ── Tests: LLM Client Integration ────────────────────────────────────────


class TestAIPlannerWithLLMClient:
    """Test AIPlanner instantiation and usage with LLMClient."""

    def test_create_with_llm_client(self):
        registry = _make_registry()
        client = _mock_llm_client(_valid_plan_json())
        planner = AIPlanner.from_llm_client(registry, client)

        ctx = PlannerContext(
            user_requirements="Build a snake game",
            project_name="SnakeGame",
        )
        plan = planner.generate_plan(ctx)

        assert len(plan.steps) == 3
        assert plan.steps[0].process_id == "deep_product_workflow"
        assert plan.steps[0].agent == "product_manager"
        client.complete.assert_called_once()

    def test_llm_receives_correct_messages(self):
        registry = _make_registry()
        client = _mock_llm_client(_valid_plan_json())
        planner = AIPlanner.from_llm_client(registry, client)

        ctx = PlannerContext(
            user_requirements="Build a web API",
            project_name="WebAPI",
        )
        planner.generate_plan(ctx)

        call_args = client.complete.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        # System message should contain catalog
        assert "process_id" in messages[0]["content"]
        # User message should contain requirements
        assert "Build a web API" in messages[1]["content"]

    def test_llm_prompt_includes_available_artifacts(self):
        registry = _make_registry()
        client = _mock_llm_client(_valid_plan_json())
        planner = AIPlanner.from_llm_client(registry, client)

        ctx = PlannerContext(
            user_requirements="Build a game",
            available_artifacts={ArtifactType.REQUIREMENTS: "req-001"},
        )
        planner.generate_plan(ctx)

        call_args = client.complete.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        user_msg = messages[1]["content"]
        assert "Already Available" in user_msg
        assert "req-001" in user_msg

    def test_llm_prompt_includes_goal_artifacts(self):
        registry = _make_registry()
        client = _mock_llm_client(_valid_plan_json())
        planner = AIPlanner.from_llm_client(registry, client)

        ctx = PlannerContext(
            user_requirements="Design only",
            goal_artifacts=[ArtifactType.ARCHITECTURE_DESIGN],
        )
        planner.generate_plan(ctx)

        call_args = client.complete.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        user_msg = messages[1]["content"]
        assert "architecture_design" in user_msg

    def test_llm_prompt_includes_constraints(self):
        registry = _make_registry()
        client = _mock_llm_client(_valid_plan_json())
        planner = AIPlanner.from_llm_client(registry, client)

        ctx = PlannerContext(
            user_requirements="Build something",
            constraints=["Must use TDD", "No external APIs"],
        )
        planner.generate_plan(ctx)

        call_args = client.complete.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        user_msg = messages[1]["content"]
        assert "Must use TDD" in user_msg
        assert "No external APIs" in user_msg


# ── Tests: Reasoning Model Handling ───────────────────────────────────────


class TestReasoningModelResponses:
    """Test that AIPlanner handles reasoning model outputs correctly."""

    def test_json_with_thinking_prefix(self):
        thinking = (
            "<reasoning>\nLet me analyze the requirements...\n"
            "The user wants a snake game, so I need:\n"
            "1. Requirements analysis\n2. Architecture design\n3. Implementation\n"
            "</reasoning>\n\n"
        )
        response = thinking + _valid_plan_json()
        client = _mock_llm_client(response)
        planner = AIPlanner.from_llm_client(_make_registry(), client)

        plan = planner.generate_plan(PlannerContext(user_requirements="Snake game"))
        assert len(plan.steps) == 3
        assert plan.goal == "Build a snake game"

    def test_json_with_markdown_fences(self):
        response = "Here's my plan:\n```json\n" + _valid_plan_json() + "\n```"
        client = _mock_llm_client(response)
        planner = AIPlanner.from_llm_client(_make_registry(), client)

        plan = planner.generate_plan(PlannerContext(user_requirements="Snake game"))
        assert len(plan.steps) == 3

    def test_skeleton_json_before_real_payload(self):
        """LLM emits a small skeleton {steps: []} before the real plan."""
        skeleton = '{"steps": []}\n\nActually, here is the full plan:\n'
        response = skeleton + _valid_plan_json()
        client = _mock_llm_client(response)
        planner = AIPlanner.from_llm_client(_make_registry(), client)

        plan = planner.generate_plan(PlannerContext(user_requirements="Snake game"))
        # Should pick the largest JSON (the real plan with 3 steps)
        assert len(plan.steps) == 3

    def test_completely_invalid_response_falls_back(self):
        client = _mock_llm_client("I don't understand the request, sorry!")
        planner = AIPlanner.from_llm_client(_make_registry(), client)

        plan = planner.generate_plan(PlannerContext(user_requirements="Snake game"))
        # Should use fallback plan
        assert len(plan.steps) > 0
        assert (
            "Fallback" in plan.reasoning or "fallback" in plan.reasoning.lower() or "LLM unavailable" in plan.reasoning
        )


# ── Tests: Replan with LLM ───────────────────────────────────────────────


class TestReplanWithLLM:
    """Test re-planning after step failure."""

    def test_replan_generates_recovery(self):
        recovery_steps = [
            {
                "process_id": "deep_architecture_workflow",
                "agent": "architect",
                "rationale": "Retry architecture design after failure",
                "input_mapping": {},
                "depends_on_steps": [],
            },
            {
                "process_id": "deep_developer_workflow",
                "agent": "developer",
                "rationale": "Continue with implementation",
                "input_mapping": {},
                "depends_on_steps": ["deep_architecture_workflow"],
            },
        ]
        recovery_json = json.dumps(
            {
                "goal": "Recover from architecture failure",
                "reasoning": "Requirements already done, retry from design",
                "steps": recovery_steps,
            }
        )

        client = _mock_llm_client(recovery_json)
        planner = AIPlanner.from_llm_client(_make_registry(), client)

        original = ExecutionPlan(
            goal="Build a snake game",
            steps=[
                PlanStep("deep_product_workflow", "product_manager", "reqs"),
                PlanStep("deep_architecture_workflow", "architect", "design"),
                PlanStep("deep_developer_workflow", "developer", "code"),
            ],
            reasoning="Original plan",
        )

        recovery = planner.replan(
            original,
            failed_step_id="deep_architecture_workflow",
            error="LLM timeout",
            completed_artifacts={ArtifactType.REQUIREMENTS: "req-001"},
        )

        assert len(recovery.steps) == 2
        assert recovery.steps[0].process_id == "deep_architecture_workflow"
        client.complete.assert_called_once()

    def test_replan_prompt_includes_error_context(self):
        client = _mock_llm_client(_valid_plan_json())
        planner = AIPlanner.from_llm_client(_make_registry(), client)

        original = ExecutionPlan(
            goal="Build something",
            steps=[
                PlanStep("deep_product_workflow", "product_manager", "reqs"),
            ],
            reasoning="Original",
        )

        planner.replan(
            original,
            failed_step_id="deep_product_workflow",
            error="Rate limit exceeded",
            completed_artifacts={},
        )

        call_args = client.complete.call_args
        messages = call_args[0][0] if call_args[0] else call_args[1]["messages"]
        user_msg = messages[1]["content"]
        assert "Rate limit exceeded" in user_msg
        assert "deep_product_workflow" in user_msg

    def test_replan_falls_back_on_llm_failure(self):
        client = _mock_llm_client("")
        client.complete.side_effect = RuntimeError("Connection refused")
        planner = AIPlanner.from_llm_client(_make_registry(), client)

        original = ExecutionPlan(
            goal="Build something",
            steps=[
                PlanStep("deep_product_workflow", "product_manager", "reqs"),
                PlanStep("deep_architecture_workflow", "architect", "design"),
            ],
            reasoning="Original",
        )

        recovery = planner.replan(
            original,
            failed_step_id="deep_product_workflow",
            error="Connection refused",
            completed_artifacts={},
        )

        # Should contain the failed step + remaining
        assert len(recovery.steps) >= 1
        step_ids = [s.process_id for s in recovery.steps]
        assert "deep_product_workflow" in step_ids


# ── Tests: Plan Validation ────────────────────────────────────────────────


class TestPlanValidationWithRegistry:
    """Test validation of LLM-generated plans against registry."""

    def test_valid_plan_passes(self):
        planner = AIPlanner(_make_registry())
        plan = ExecutionPlan(
            goal="test",
            steps=[
                PlanStep("deep_product_workflow", "product_manager", "reqs"),
                PlanStep(
                    "deep_architecture_workflow",
                    "architect",
                    "design",
                    depends_on_steps=["deep_product_workflow"],
                ),
            ],
            reasoning="test",
        )
        errors = planner.validate_plan(plan)
        assert errors == []

    def test_invalid_process_id(self):
        planner = AIPlanner(_make_registry())
        plan = ExecutionPlan(
            goal="test",
            steps=[PlanStep("nonexistent_process", "developer", "bad")],
            reasoning="test",
        )
        errors = planner.validate_plan(plan)
        assert any("not found" in e for e in errors)

    def test_invalid_agent_for_process(self):
        planner = AIPlanner(_make_registry())
        plan = ExecutionPlan(
            goal="test",
            steps=[PlanStep("deep_product_workflow", "developer", "wrong agent")],
            reasoning="test",
        )
        errors = planner.validate_plan(plan)
        assert any("not valid" in e for e in errors)

    def test_circular_dependency_detected(self):
        planner = AIPlanner(_make_registry())
        plan = ExecutionPlan(
            goal="test",
            steps=[
                PlanStep(
                    "deep_product_workflow", "product_manager", "a", depends_on_steps=["deep_architecture_workflow"]
                ),
                PlanStep("deep_architecture_workflow", "architect", "b", depends_on_steps=["deep_product_workflow"]),
            ],
            reasoning="test",
        )
        errors = planner.validate_plan(plan)
        assert any("Circular" in e for e in errors)


# ── Tests: Prompt Construction ────────────────────────────────────────────


class TestPromptConstruction:
    """Test that prompts sent to LLM are well-formed."""

    def test_system_message_has_catalog(self):
        registry = _make_registry()
        client = _mock_llm_client(_valid_plan_json())
        planner = AIPlanner.from_llm_client(registry, client)

        planner.generate_plan(PlannerContext(user_requirements="test"))

        messages = client.complete.call_args[0][0]
        system = messages[0]["content"]
        # Catalog should list actual process IDs
        assert "deep_product_workflow" in system
        assert "deep_architecture_workflow" in system

    def test_catalog_includes_descriptions(self):
        registry = _make_registry()
        client = _mock_llm_client(_valid_plan_json())
        planner = AIPlanner.from_llm_client(registry, client)

        planner.generate_plan(PlannerContext(user_requirements="test"))

        messages = client.complete.call_args[0][0]
        system = messages[0]["content"]
        # Should contain some descriptive content from registry
        assert "agent_roles" in system

    def test_user_message_has_requirements(self):
        registry = _make_registry()
        client = _mock_llm_client(_valid_plan_json())
        planner = AIPlanner.from_llm_client(registry, client)

        planner.generate_plan(PlannerContext(user_requirements="Build a REST API for user management"))

        messages = client.complete.call_args[0][0]
        user = messages[1]["content"]
        assert "Build a REST API for user management" in user
