"""Tests for the AI-First Dynamic Planner.

The AIPlanner takes user requirements + ProcessRegistry catalog, and uses
an LLM to dynamically generate an execution plan. No hardcoded phase ordering.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from aise.core.ai_planner import (
    AIPlanner,
    ExecutionPlan,
    PlannerContext,
    PlanStep,
)
from aise.core.artifact import ArtifactType
from aise.core.process_registry import (
    ProcessCapability,
    ProcessDescriptor,
    ProcessRegistry,
)


@pytest.fixture
def sample_registry():
    """A minimal registry with 3 processes forming a chain."""
    registry = ProcessRegistry()
    registry.register(
        ProcessDescriptor(
            id="req_analysis",
            name="Requirement Analysis",
            description="Analyze raw requirements into structured format",
            agent_roles=["product_manager"],
            phase_affinity=["requirements"],
            input_keys=["raw_requirements"],
            output_artifact_types=[ArtifactType.REQUIREMENTS],
            capabilities=[ProcessCapability.ANALYSIS],
            depends_on_artifacts=[],
        )
    )
    registry.register(
        ProcessDescriptor(
            id="system_design",
            name="System Design",
            description="Create system architecture from requirements",
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
            id="code_gen",
            name="Code Generation",
            description="Generate source code from architecture",
            agent_roles=["developer"],
            phase_affinity=["implementation"],
            input_keys=["system_design"],
            output_artifact_types=[ArtifactType.SOURCE_CODE],
            capabilities=[ProcessCapability.GENERATION],
            depends_on_artifacts=[ArtifactType.ARCHITECTURE_DESIGN],
        )
    )
    return registry


class TestPlanStep:
    """Test PlanStep data class."""

    def test_creation(self):
        step = PlanStep(
            process_id="req_analysis",
            agent="product_manager",
            rationale="Need to analyze requirements first",
            input_mapping={"raw_requirements": "$user_input"},
            depends_on_steps=[],
        )
        assert step.process_id == "req_analysis"
        assert step.agent == "product_manager"
        assert step.depends_on_steps == []

    def test_step_serialization(self):
        step = PlanStep(
            process_id="code_gen",
            agent="developer",
            rationale="Generate code after design",
            input_mapping={},
            depends_on_steps=["system_design"],
        )
        d = step.to_dict()
        assert isinstance(d, dict)
        json.dumps(d)


class TestExecutionPlan:
    """Test ExecutionPlan creation and validation."""

    def test_plan_creation(self):
        steps = [
            PlanStep("req_analysis", "pm", "First step", {}, []),
            PlanStep("system_design", "arch", "Second step", {}, ["req_analysis"]),
        ]
        plan = ExecutionPlan(
            goal="Build a REST API",
            steps=steps,
            reasoning="Standard SDLC flow",
        )
        assert len(plan.steps) == 2
        assert plan.goal == "Build a REST API"

    def test_plan_validates_no_circular_deps(self):
        """Plan with circular dependencies should be detected."""
        steps = [
            PlanStep("a", "agent1", "", {}, ["b"]),
            PlanStep("b", "agent2", "", {}, ["a"]),
        ]
        plan = ExecutionPlan(goal="test", steps=steps, reasoning="")
        errors = plan.validate()
        assert any("circular" in e.lower() or "cycle" in e.lower() for e in errors)

    def test_plan_validates_unknown_dependency(self):
        """Steps referencing non-existent steps should be flagged."""
        steps = [
            PlanStep("a", "agent1", "", {}, ["nonexistent"]),
        ]
        plan = ExecutionPlan(goal="test", steps=steps, reasoning="")
        errors = plan.validate()
        assert any("nonexistent" in e.lower() for e in errors)

    def test_valid_plan_has_no_errors(self):
        steps = [
            PlanStep("req_analysis", "pm", "Start", {}, []),
            PlanStep("system_design", "arch", "Then design", {}, ["req_analysis"]),
        ]
        plan = ExecutionPlan(goal="test", steps=steps, reasoning="ok")
        assert plan.validate() == []

    def test_plan_execution_order(self):
        """Topological sort of plan steps."""
        steps = [
            PlanStep("c", "dev", "", {}, ["b"]),
            PlanStep("a", "pm", "", {}, []),
            PlanStep("b", "arch", "", {}, ["a"]),
        ]
        plan = ExecutionPlan(goal="test", steps=steps, reasoning="")
        order = plan.execution_order()
        ids = [s.process_id for s in order]
        assert ids.index("a") < ids.index("b")
        assert ids.index("b") < ids.index("c")


class TestPlannerContext:
    """Test the context object that feeds the planner."""

    def test_context_creation(self):
        ctx = PlannerContext(
            user_requirements="Build a snake game",
            available_artifacts={},
            constraints=["Must use Python", "Must have tests"],
        )
        assert "snake" in ctx.user_requirements.lower()
        assert len(ctx.constraints) == 2

    def test_context_with_existing_artifacts(self):
        """When artifacts already exist, planner should skip those steps."""
        ctx = PlannerContext(
            user_requirements="Continue from design phase",
            available_artifacts={
                ArtifactType.REQUIREMENTS: "req_artifact_123",
            },
            constraints=[],
        )
        assert ArtifactType.REQUIREMENTS in ctx.available_artifacts


class TestAIPlanner:
    """Test the AI-driven planner."""

    def test_planner_with_mock_llm(self, sample_registry):
        """Planner uses LLM to generate plan from registry catalog."""
        mock_llm_response = json.dumps(
            {
                "goal": "Build a REST API",
                "reasoning": "Standard 3-step flow",
                "steps": [
                    {
                        "process_id": "req_analysis",
                        "agent": "product_manager",
                        "rationale": "Analyze requirements first",
                        "input_mapping": {"raw_requirements": "$user_input"},
                        "depends_on_steps": [],
                    },
                    {
                        "process_id": "system_design",
                        "agent": "architect",
                        "rationale": "Design system architecture",
                        "input_mapping": {"requirements": "$req_analysis.output"},
                        "depends_on_steps": ["req_analysis"],
                    },
                    {
                        "process_id": "code_gen",
                        "agent": "developer",
                        "rationale": "Generate source code",
                        "input_mapping": {"system_design": "$system_design.output"},
                        "depends_on_steps": ["system_design"],
                    },
                ],
            }
        )

        planner = AIPlanner(registry=sample_registry)
        context = PlannerContext(
            user_requirements="Build a REST API for user management",
            available_artifacts={},
            constraints=[],
        )

        with patch.object(planner, "_call_llm", return_value=mock_llm_response):
            plan = planner.generate_plan(context)

        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) == 3
        assert plan.validate() == []
        order = plan.execution_order()
        ids = [s.process_id for s in order]
        assert ids == ["req_analysis", "system_design", "code_gen"]

    def test_planner_skips_satisfied_artifacts(self, sample_registry):
        """If requirements artifact already exists, planner should skip req_analysis."""
        mock_llm_response = json.dumps(
            {
                "goal": "Continue from design",
                "reasoning": "Requirements already exist, start from design",
                "steps": [
                    {
                        "process_id": "system_design",
                        "agent": "architect",
                        "rationale": "Requirements available, go to design",
                        "input_mapping": {},
                        "depends_on_steps": [],
                    },
                    {
                        "process_id": "code_gen",
                        "agent": "developer",
                        "rationale": "Then implement",
                        "input_mapping": {},
                        "depends_on_steps": ["system_design"],
                    },
                ],
            }
        )

        planner = AIPlanner(registry=sample_registry)
        context = PlannerContext(
            user_requirements="Continue development",
            available_artifacts={ArtifactType.REQUIREMENTS: "existing_req_id"},
            constraints=[],
        )

        with patch.object(planner, "_call_llm", return_value=mock_llm_response):
            plan = planner.generate_plan(context)

        assert len(plan.steps) == 2
        process_ids = [s.process_id for s in plan.steps]
        assert "req_analysis" not in process_ids

    def test_planner_validates_against_registry(self, sample_registry):
        """Plan referencing non-existent processes should be caught."""
        mock_llm_response = json.dumps(
            {
                "goal": "test",
                "reasoning": "test",
                "steps": [
                    {
                        "process_id": "nonexistent_skill",
                        "agent": "someone",
                        "rationale": "?",
                        "input_mapping": {},
                        "depends_on_steps": [],
                    },
                ],
            }
        )

        planner = AIPlanner(registry=sample_registry)
        context = PlannerContext(
            user_requirements="test",
            available_artifacts={},
            constraints=[],
        )

        with patch.object(planner, "_call_llm", return_value=mock_llm_response):
            plan = planner.generate_plan(context)

        errors = planner.validate_plan(plan)
        assert any("nonexistent_skill" in e.lower() or "not found" in e.lower() for e in errors)

    def test_planner_fallback_on_llm_failure(self, sample_registry):
        """If LLM fails, planner should fall back to dependency-chain resolution."""
        planner = AIPlanner(registry=sample_registry)
        context = PlannerContext(
            user_requirements="Build something with source code",
            available_artifacts={},
            constraints=[],
            goal_artifacts=[ArtifactType.SOURCE_CODE],
        )

        with patch.object(planner, "_call_llm", side_effect=Exception("LLM unavailable")):
            plan = planner.generate_plan(context)

        # Should fall back to registry's dependency chain
        assert isinstance(plan, ExecutionPlan)
        assert len(plan.steps) >= 1
        process_ids = [s.process_id for s in plan.steps]
        # Must include code_gen at minimum
        assert "code_gen" in process_ids

    def test_planner_prompt_includes_catalog(self, sample_registry):
        """The prompt sent to LLM must include the process catalog."""
        planner = AIPlanner(registry=sample_registry)
        context = PlannerContext(
            user_requirements="Build something",
            available_artifacts={},
            constraints=[],
        )

        captured_prompt = []

        def mock_call(prompt):
            captured_prompt.append(prompt)
            return json.dumps(
                {
                    "goal": "test",
                    "reasoning": "test",
                    "steps": [
                        {
                            "process_id": "req_analysis",
                            "agent": "product_manager",
                            "rationale": "start",
                            "input_mapping": {},
                            "depends_on_steps": [],
                        }
                    ],
                }
            )

        with patch.object(planner, "_call_llm", side_effect=mock_call):
            planner.generate_plan(context)

        assert len(captured_prompt) == 1
        prompt = captured_prompt[0]
        # Catalog info must be in prompt
        assert "req_analysis" in prompt
        assert "system_design" in prompt
        assert "code_gen" in prompt

    def test_replan_on_step_failure(self, sample_registry):
        """Planner can generate a recovery plan when a step fails."""
        planner = AIPlanner(registry=sample_registry)

        original_plan = ExecutionPlan(
            goal="Build API",
            steps=[
                PlanStep("req_analysis", "pm", "", {}, []),
                PlanStep("system_design", "arch", "", {}, ["req_analysis"]),
                PlanStep("code_gen", "dev", "", {}, ["system_design"]),
            ],
            reasoning="original",
        )

        mock_response = json.dumps(
            {
                "goal": "Recover after design failure",
                "reasoning": "Retry design with adjusted params",
                "steps": [
                    {
                        "process_id": "system_design",
                        "agent": "architect",
                        "rationale": "Retry design",
                        "input_mapping": {},
                        "depends_on_steps": [],
                    },
                    {
                        "process_id": "code_gen",
                        "agent": "developer",
                        "rationale": "Then implement",
                        "input_mapping": {},
                        "depends_on_steps": ["system_design"],
                    },
                ],
            }
        )

        with patch.object(planner, "_call_llm", return_value=mock_response):
            recovery_plan = planner.replan(
                original_plan=original_plan,
                failed_step_id="system_design",
                error="LLM returned invalid JSON",
                completed_artifacts={ArtifactType.REQUIREMENTS: "req_123"},
            )

        assert isinstance(recovery_plan, ExecutionPlan)
        assert len(recovery_plan.steps) == 2
