"""Tests for PlanVisualizer — plan rendering in various formats."""

from __future__ import annotations

from aise.core.ai_planner import ExecutionPlan, PlanStep
from aise.core.artifact import ArtifactType
from aise.core.plan_visualizer import PlanVisualizer
from aise.core.process_registry import ProcessCapability, ProcessDescriptor, ProcessRegistry


def _sample_plan() -> ExecutionPlan:
    return ExecutionPlan(
        goal="Build a REST API",
        steps=[
            PlanStep("requirement_analysis", "product_manager", "First analyze reqs"),
            PlanStep(
                "system_design",
                "architect",
                "Then design",
                depends_on_steps=["requirement_analysis"],
            ),
            PlanStep(
                "code_generation",
                "developer",
                "Finally code",
                depends_on_steps=["system_design"],
            ),
        ],
        reasoning="Standard SDLC approach",
    )


def _sample_registry() -> ProcessRegistry:
    registry = ProcessRegistry()
    registry.register(
        ProcessDescriptor(
            id="requirement_analysis",
            name="Requirement Analysis",
            description="Parse requirements into structured format",
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
            description="Create architecture design",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=[],
            output_artifact_types=[ArtifactType.ARCHITECTURE_DESIGN],
            capabilities=[ProcessCapability.DESIGN],
        )
    )
    return registry


class TestMermaidOutput:
    def test_basic_mermaid(self):
        viz = PlanVisualizer()
        result = viz.to_mermaid(_sample_plan())
        assert "graph TD" in result
        assert "requirement_analysis" in result
        assert "system_design" in result
        assert "-->" in result

    def test_mermaid_contains_agents(self):
        viz = PlanVisualizer()
        result = viz.to_mermaid(_sample_plan())
        assert "product_manager" in result
        assert "architect" in result

    def test_mermaid_dependency_edges(self):
        viz = PlanVisualizer()
        result = viz.to_mermaid(_sample_plan())
        assert "requirement_analysis --> system_design" in result
        assert "system_design --> code_generation" in result

    def test_empty_plan_mermaid(self):
        plan = ExecutionPlan(goal="Empty", steps=[], reasoning="Nothing")
        viz = PlanVisualizer()
        result = viz.to_mermaid(plan)
        assert "graph TD" in result


class TestTextTable:
    def test_basic_table(self):
        viz = PlanVisualizer()
        result = viz.to_text_table(_sample_plan())
        assert "Build a REST API" in result
        assert "requirement_analysis" in result
        assert "product_manager" in result
        assert "#1" not in result.split("\n")[4]  # First step has no deps

    def test_dependency_references(self):
        viz = PlanVisualizer()
        result = viz.to_text_table(_sample_plan())
        lines = result.split("\n")
        # Find the system_design row — should reference #1
        design_line = [line for line in lines if "system_design" in line]
        assert design_line
        assert "#1" in design_line[0]

    def test_empty_plan_table(self):
        plan = ExecutionPlan(goal="Empty", steps=[], reasoning="Nothing")
        viz = PlanVisualizer()
        result = viz.to_text_table(plan)
        assert "empty plan" in result.lower()

    def test_table_has_total(self):
        viz = PlanVisualizer()
        result = viz.to_text_table(_sample_plan())
        assert "Total steps: 3" in result


class TestSummary:
    def test_basic_summary(self):
        viz = PlanVisualizer()
        result = viz.to_summary(_sample_plan())
        assert "3 steps" in result
        assert "→" in result
        assert "requirement_analysis" in result

    def test_empty_summary(self):
        plan = ExecutionPlan(goal="Empty", steps=[], reasoning="Nothing")
        viz = PlanVisualizer()
        result = viz.to_summary(plan)
        assert "empty" in result.lower()


class TestConfirmationPrompt:
    def test_basic_prompt(self):
        registry = _sample_registry()
        viz = PlanVisualizer(registry=registry)
        result = viz.to_confirmation_prompt(_sample_plan())
        assert "AI-Generated" in result
        assert "Build a REST API" in result
        assert "requirement_analysis" in result
        assert "Parse requirements" in result  # Description from registry

    def test_prompt_shows_rationale(self):
        viz = PlanVisualizer()
        result = viz.to_confirmation_prompt(_sample_plan())
        assert "First analyze reqs" in result

    def test_prompt_without_registry(self):
        viz = PlanVisualizer()
        result = viz.to_confirmation_prompt(_sample_plan())
        assert "requirement_analysis" in result
        assert "Total:" in result
