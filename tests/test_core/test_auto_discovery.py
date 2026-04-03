"""Tests for ProcessRegistry auto-discovery from live agents."""

from __future__ import annotations

from typing import Any

from aise.core.agent import Agent, AgentRole
from aise.core.artifact import Artifact, ArtifactStore, ArtifactType
from aise.core.message import MessageBus
from aise.core.process_registry import ProcessCapability, ProcessDescriptor, ProcessRegistry
from aise.core.skill import Skill, SkillContext


class StubSkill(Skill):
    def __init__(self, name: str, desc: str = ""):
        self._name = name
        self._desc = desc or f"Stub: {name}"

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._desc

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={"stub": True},
            producer=self._name,
        )


def _make_agent(name: str, role: AgentRole, skill_names: list[str]) -> Agent:
    bus = MessageBus()
    store = ArtifactStore()
    agent = Agent(name=name, role=role, message_bus=bus, artifact_store=store)
    for sn in skill_names:
        agent.register_skill(StubSkill(sn))
    return agent


class TestRegisterOrUpdate:
    def test_new_registration(self):
        registry = ProcessRegistry()
        desc = ProcessDescriptor(
            id="test_skill",
            name="Test",
            description="Test skill",
            agent_roles=["dev"],
            phase_affinity=[],
            input_keys=[],
            output_artifact_types=[],
            capabilities=[ProcessCapability.ANALYSIS],
        )
        result = registry.register_or_update(desc)
        assert result is True
        assert registry.get("test_skill") is not None

    def test_update_existing(self):
        registry = ProcessRegistry()
        desc1 = ProcessDescriptor(
            id="test_skill",
            name="Test v1",
            description="Version 1",
            agent_roles=["dev"],
            phase_affinity=[],
            input_keys=[],
            output_artifact_types=[ArtifactType.REQUIREMENTS],
            capabilities=[ProcessCapability.ANALYSIS],
        )
        registry.register(desc1)

        desc2 = ProcessDescriptor(
            id="test_skill",
            name="Test v2",
            description="Version 2",
            agent_roles=["architect"],
            phase_affinity=[],
            input_keys=[],
            output_artifact_types=[ArtifactType.ARCHITECTURE_DESIGN],
            capabilities=[ProcessCapability.DESIGN],
        )
        registry.register_or_update(desc2)

        updated = registry.get("test_skill")
        assert updated.name == "Test v2"
        assert updated.agent_roles == ["architect"]

    def test_update_cleans_old_indexes(self):
        registry = ProcessRegistry()
        desc1 = ProcessDescriptor(
            id="test_skill",
            name="Test",
            description="Test",
            agent_roles=["dev"],
            phase_affinity=[],
            input_keys=[],
            output_artifact_types=[ArtifactType.REQUIREMENTS],
            capabilities=[ProcessCapability.ANALYSIS],
        )
        registry.register(desc1)

        desc2 = ProcessDescriptor(
            id="test_skill",
            name="Test v2",
            description="Test v2",
            agent_roles=["architect"],
            phase_affinity=[],
            input_keys=[],
            output_artifact_types=[ArtifactType.ARCHITECTURE_DESIGN],
            capabilities=[ProcessCapability.DESIGN],
        )
        registry.register_or_update(desc2)

        # Old indexes should be cleaned
        assert registry.find_by_agent("dev") == []
        assert registry.find_by_agent("architect")[0].id == "test_skill"
        assert registry.find_producers(ArtifactType.REQUIREMENTS) == []
        assert registry.find_producers(ArtifactType.ARCHITECTURE_DESIGN)[0].id == "test_skill"


class TestAutoDiscovery:
    def test_discover_new_skills(self):
        registry = ProcessRegistry()
        agents = {
            "dev": _make_agent("dev", AgentRole.DEVELOPER, ["custom_code_gen", "special_refactor"]),
        }
        discovered = registry.auto_discover_from_agents(agents)
        assert discovered == 2
        assert registry.get("custom_code_gen") is not None
        assert registry.get("special_refactor") is not None

    def test_skip_existing_processes(self):
        registry = ProcessRegistry()
        desc = ProcessDescriptor(
            id="custom_code_gen",
            name="Custom Code Gen",
            description="Already registered",
            agent_roles=["dev"],
            phase_affinity=[],
            input_keys=[],
            output_artifact_types=[],
            capabilities=[ProcessCapability.GENERATION],
        )
        registry.register(desc)

        agents = {
            "dev": _make_agent("dev", AgentRole.DEVELOPER, ["custom_code_gen", "new_skill"]),
        }
        discovered = registry.auto_discover_from_agents(agents)
        assert discovered == 1
        # Original should not be overwritten
        assert registry.get("custom_code_gen").description == "Already registered"

    def test_infer_phase_from_name(self):
        registry = ProcessRegistry()
        agents = {
            "pm": _make_agent("pm", AgentRole.PRODUCT_MANAGER, ["advanced_requirement_parser"]),
            "dev": _make_agent("dev", AgentRole.DEVELOPER, ["code_optimizer"]),
            "qa": _make_agent("qa", AgentRole.QA_ENGINEER, ["integration_test_runner"]),
        }
        registry.auto_discover_from_agents(agents)

        req = registry.get("advanced_requirement_parser")
        assert "requirements" in req.phase_affinity

        code = registry.get("code_optimizer")
        assert "implementation" in code.phase_affinity

        test = registry.get("integration_test_runner")
        assert "testing" in test.phase_affinity

    def test_infer_capability_from_name(self):
        registry = ProcessRegistry()
        agents = {
            "dev": _make_agent(
                "dev",
                AgentRole.DEVELOPER,
                ["analysis_tool", "design_helper", "code_generator", "test_runner", "review_checker"],
            ),
        }
        registry.auto_discover_from_agents(agents)

        assert registry.get("analysis_tool").capabilities == [ProcessCapability.ANALYSIS]
        assert registry.get("design_helper").capabilities == [ProcessCapability.DESIGN]
        assert registry.get("code_generator").capabilities == [ProcessCapability.GENERATION]
        assert registry.get("test_runner").capabilities == [ProcessCapability.TESTING]
        assert registry.get("review_checker").capabilities == [ProcessCapability.REVIEW]

    def test_detect_deep_workflow(self):
        registry = ProcessRegistry()
        agents = {
            "dev": _make_agent("dev", AgentRole.DEVELOPER, ["deep_custom_workflow"]),
        }
        registry.auto_discover_from_agents(agents)

        desc = registry.get("deep_custom_workflow")
        assert desc.is_deep_workflow is True

    def test_empty_agents(self):
        registry = ProcessRegistry()
        discovered = registry.auto_discover_from_agents({})
        assert discovered == 0

    def test_discover_with_default_registry(self):
        """Auto-discover on top of default registry."""
        registry = ProcessRegistry.build_default()
        initial_count = len(registry.all())

        agents = {
            "dev": _make_agent("dev", AgentRole.DEVELOPER, ["brand_new_skill"]),
        }
        discovered = registry.auto_discover_from_agents(agents)

        assert discovered == 1
        assert len(registry.all()) == initial_count + 1
