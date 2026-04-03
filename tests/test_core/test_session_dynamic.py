"""Tests for OnDemandSession dynamic command and plan preview."""

from __future__ import annotations

from typing import Any

from aise.core.agent import Agent, AgentRole
from aise.core.artifact import Artifact, ArtifactType
from aise.core.orchestrator import Orchestrator
from aise.core.session import OnDemandSession, UserCommand, parse_command
from aise.core.skill import Skill, SkillContext


class StubSkill(Skill):
    def __init__(self, skill_name: str, artifact_type: ArtifactType):
        self._name = skill_name
        self._artifact_type = artifact_type

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Stub: {self._name}"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=self._artifact_type,
            content={
                "stub": True,
                "skill": self._name,
                "raw_input": input_data.get("raw_requirements", ""),
                "functional_requirements": ["FR-1"],
                "non_functional_requirements": ["NFR-1"],
            },
            producer=self._name,
        )


def _setup_session() -> OnDemandSession:
    orch = Orchestrator()
    bus = orch.message_bus
    store = orch.artifact_store

    pm = Agent("product_manager", AgentRole.PRODUCT_MANAGER, bus, store)
    pm.register_skill(StubSkill("requirement_analysis", ArtifactType.REQUIREMENTS))
    orch.register_agent(pm)

    arch = Agent("architect", AgentRole.ARCHITECT, bus, store)
    arch.register_skill(StubSkill("system_design", ArtifactType.ARCHITECTURE_DESIGN))
    orch.register_agent(arch)

    dev = Agent("developer", AgentRole.DEVELOPER, bus, store)
    dev.register_skill(StubSkill("code_generation", ArtifactType.SOURCE_CODE))
    orch.register_agent(dev)

    outputs: list[str] = []
    session = OnDemandSession(orch, "TestProject", output=outputs.append)
    return session


class TestDynamicCommand:
    def test_parse_dynamic_command(self):
        cmd, text = parse_command("dynamic")
        assert cmd == UserCommand.RUN_DYNAMIC

    def test_parse_ai_alias(self):
        cmd, text = parse_command("ai")
        assert cmd == UserCommand.RUN_DYNAMIC

    def test_parse_plan_alias(self):
        cmd, text = parse_command("plan source_code")
        assert cmd == UserCommand.RUN_DYNAMIC
        assert text == "source_code"

    def test_dynamic_without_requirements(self):
        session = _setup_session()
        result = session.handle_input("dynamic")
        assert result["status"] == "error"
        assert "requirements" in result["output"].lower()

    def test_dynamic_with_requirements(self):
        session = _setup_session()
        # Add requirement first
        session.handle_input("add Build a REST API")
        # Run dynamic
        result = session.handle_input("dynamic")
        assert result["status"] == "ok"
        assert "AI-First" in result["output"]

    def test_dynamic_shows_steps(self):
        session = _setup_session()
        session.handle_input("add Build a web app")
        result = session.handle_input("dynamic")
        assert "Steps:" in result["output"]

    def test_help_shows_dynamic(self):
        session = _setup_session()
        result = session.handle_input("help")
        assert "dynamic" in result["output"]


class TestPreviewPlan:
    def test_preview_text_format(self):
        orch = Orchestrator()
        bus = orch.message_bus
        store = orch.artifact_store

        pm = Agent("product_manager", AgentRole.PRODUCT_MANAGER, bus, store)
        pm.register_skill(StubSkill("requirement_analysis", ArtifactType.REQUIREMENTS))
        orch.register_agent(pm)

        result = orch.preview_dynamic_plan(
            {"raw_requirements": "Build something"},
            "TestProject",
            output_format="text",
        )
        assert "AI Execution Plan" in result

    def test_preview_mermaid_format(self):
        orch = Orchestrator()
        bus = orch.message_bus
        store = orch.artifact_store

        pm = Agent("product_manager", AgentRole.PRODUCT_MANAGER, bus, store)
        pm.register_skill(StubSkill("requirement_analysis", ArtifactType.REQUIREMENTS))
        orch.register_agent(pm)

        result = orch.preview_dynamic_plan(
            {"raw_requirements": "Build something"},
            "TestProject",
            output_format="mermaid",
        )
        assert "graph TD" in result

    def test_preview_summary_format(self):
        orch = Orchestrator()
        bus = orch.message_bus
        store = orch.artifact_store

        pm = Agent("product_manager", AgentRole.PRODUCT_MANAGER, bus, store)
        pm.register_skill(StubSkill("requirement_analysis", ArtifactType.REQUIREMENTS))
        orch.register_agent(pm)

        result = orch.preview_dynamic_plan(
            {"raw_requirements": "Build something"},
            "TestProject",
            output_format="summary",
        )
        assert "steps" in result

    def test_preview_confirm_format(self):
        orch = Orchestrator()
        bus = orch.message_bus
        store = orch.artifact_store

        pm = Agent("product_manager", AgentRole.PRODUCT_MANAGER, bus, store)
        pm.register_skill(StubSkill("requirement_analysis", ArtifactType.REQUIREMENTS))
        orch.register_agent(pm)

        result = orch.preview_dynamic_plan(
            {"raw_requirements": "Build something"},
            "TestProject",
            output_format="confirm",
        )
        assert "AI-Generated" in result
