"""Tests for Orchestrator.run_dynamic_workflow integration."""

from __future__ import annotations

from typing import Any

from aise.core.agent import Agent, AgentRole
from aise.core.artifact import Artifact, ArtifactStatus, ArtifactType
from aise.core.orchestrator import Orchestrator
from aise.core.skill import Skill, SkillContext

# ---------------------------------------------------------------------------
# Stub skill for testing
# ---------------------------------------------------------------------------


class StubSkill(Skill):
    """A minimal skill that returns a fixed artifact."""

    def __init__(self, skill_name: str, artifact_type: ArtifactType):
        self._name = skill_name
        self._artifact_type = artifact_type

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Stub skill: {self._name}"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=self._artifact_type,
            content={"stub": True, "skill": self._name},
            producer=self._name,
            status=ArtifactStatus.DRAFT,
        )


def _setup_orchestrator() -> Orchestrator:
    """Build an orchestrator with stub agents/skills for dynamic workflow testing."""
    orch = Orchestrator()
    bus = orch.message_bus
    store = orch.artifact_store

    # Product Manager
    pm = Agent(name="product_manager", role=AgentRole.PRODUCT_MANAGER, message_bus=bus, artifact_store=store)
    pm.register_skill(StubSkill("requirement_analysis", ArtifactType.REQUIREMENTS))
    pm.register_skill(StubSkill("deep_product_workflow", ArtifactType.REQUIREMENTS))
    orch.register_agent(pm)

    # Architect
    arch = Agent(name="architect", role=AgentRole.ARCHITECT, message_bus=bus, artifact_store=store)
    arch.register_skill(StubSkill("system_design", ArtifactType.ARCHITECTURE_DESIGN))
    arch.register_skill(StubSkill("deep_architecture_workflow", ArtifactType.ARCHITECTURE_DESIGN))
    orch.register_agent(arch)

    # Developer
    dev = Agent(name="developer", role=AgentRole.DEVELOPER, message_bus=bus, artifact_store=store)
    dev.register_skill(StubSkill("code_generation", ArtifactType.SOURCE_CODE))
    dev.register_skill(StubSkill("deep_developer_workflow", ArtifactType.SOURCE_CODE))
    orch.register_agent(dev)

    # QA
    qa = Agent(name="qa_engineer", role=AgentRole.QA_ENGINEER, message_bus=bus, artifact_store=store)
    qa.register_skill(StubSkill("test_plan_design", ArtifactType.TEST_PLAN))
    qa.register_skill(StubSkill("deep_testing_workflow", ArtifactType.TEST_PLAN))
    orch.register_agent(qa)

    return orch


class TestOrchestratorDynamicWorkflow:
    """Test the AI-First dynamic workflow via Orchestrator."""

    def test_dynamic_workflow_runs_without_llm(self):
        """Without LLM, falls back to dependency resolution."""
        orch = _setup_orchestrator()

        result = orch.run_dynamic_workflow(
            project_input={"raw_requirements": "Build a REST API"},
            project_name="TestAPI",
        )

        assert result["status"] in ("completed", "partial")
        assert isinstance(result["step_results"], list)
        assert isinstance(result["plan"], dict)
        assert result["plan"]["goal"]

    def test_dynamic_workflow_produces_artifacts(self):
        """Dynamic workflow should produce artifacts tracked in the store."""
        orch = _setup_orchestrator()

        result = orch.run_dynamic_workflow(
            project_input={"raw_requirements": "Build a CLI tool"},
            project_name="TestCLI",
        )

        # Should have artifact IDs from completed steps
        completed = [s for s in result["step_results"] if s["status"] == "completed"]
        assert len(completed) > 0

        # Verify artifacts exist in the store
        for step in completed:
            if step["artifact_id"]:
                art = orch.artifact_store.get(step["artifact_id"])
                assert art is not None

    def test_dynamic_workflow_with_existing_artifacts(self):
        """When artifacts already exist, corresponding steps should be skipped."""
        orch = _setup_orchestrator()

        # Pre-populate requirements artifact
        req_artifact = Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={"text": "pre-existing requirements"},
            producer="test",
        )
        orch.artifact_store.store(req_artifact)

        # Use REQUIREMENTS as goal (not SOURCE_CODE which has a deeper chain)
        result = orch.run_dynamic_workflow(
            project_input={"raw_requirements": "Build something"},
            project_name="TestSkip",
            goal_artifacts=[ArtifactType.REQUIREMENTS],
        )

        # The plan should be empty or all skipped (requirements already exist)
        assert result["status"] == "completed"
        if result["step_results"]:
            skipped = [s for s in result["step_results"] if s["status"] == "skipped"]
            assert len(skipped) > 0

    def test_dynamic_workflow_with_goal_artifacts(self):
        """Custom goal artifacts change what the planner targets."""
        orch = _setup_orchestrator()

        result = orch.run_dynamic_workflow(
            project_input={"raw_requirements": "Design a system"},
            project_name="TestDesign",
            goal_artifacts=[ArtifactType.ARCHITECTURE_DESIGN],
        )

        assert result["status"] in ("completed", "partial")
        # Plan should target architecture design
        assert "design" in result["plan"]["goal"].lower() or len(result["step_results"]) > 0

    def test_dynamic_workflow_returns_plan_metadata(self):
        """Result includes the generated plan for transparency."""
        orch = _setup_orchestrator()

        result = orch.run_dynamic_workflow(
            project_input={"raw_requirements": "Build a web app"},
            project_name="TestMeta",
        )

        plan = result["plan"]
        assert "goal" in plan
        assert "reasoning" in plan
        assert "steps" in plan
        assert isinstance(plan["steps"], list)

    def test_both_workflows_coexist(self):
        """run_default_workflow and run_dynamic_workflow can both be used."""
        orch = _setup_orchestrator()

        # Static workflow still works
        static_result = orch.run_default_workflow(
            project_input={"raw_requirements": "Build something"},
            project_name="StaticTest",
        )
        assert isinstance(static_result, list)

        # Clear store for dynamic test
        orch.artifact_store.clear()

        # Dynamic workflow also works
        dynamic_result = orch.run_dynamic_workflow(
            project_input={"raw_requirements": "Build something"},
            project_name="DynamicTest",
        )
        assert isinstance(dynamic_result, dict)
        assert "status" in dynamic_result
