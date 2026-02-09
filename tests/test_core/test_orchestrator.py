"""Tests for the orchestrator."""

from typing import Any

import pytest

from aise.core.agent import Agent, AgentRole
from aise.core.artifact import Artifact, ArtifactType
from aise.core.orchestrator import Orchestrator
from aise.core.skill import Skill, SkillContext
from aise.core.workflow import Phase, Workflow


class EchoSkill(Skill):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes input"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content=input_data,
            producer="test",
        )


class TestOrchestrator:
    def test_register_and_get_agent(self):
        orch = Orchestrator()
        bus = orch.message_bus
        store = orch.artifact_store
        agent = Agent("dev", AgentRole.DEVELOPER, bus, store)
        orch.register_agent(agent)

        assert orch.get_agent("dev") is agent
        assert len(orch.agents) == 1

    def test_get_agents_by_role(self):
        orch = Orchestrator()
        bus, store = orch.message_bus, orch.artifact_store
        a1 = Agent("dev1", AgentRole.DEVELOPER, bus, store)
        a2 = Agent("dev2", AgentRole.DEVELOPER, bus, store)
        a3 = Agent("pm", AgentRole.PRODUCT_MANAGER, bus, store)
        orch.register_agent(a1)
        orch.register_agent(a2)
        orch.register_agent(a3)

        devs = orch.get_agents_by_role(AgentRole.DEVELOPER)
        assert len(devs) == 2

    def test_execute_task(self):
        orch = Orchestrator()
        bus, store = orch.message_bus, orch.artifact_store
        agent = Agent("worker", AgentRole.DEVELOPER, bus, store)
        agent.register_skill(EchoSkill())
        orch.register_agent(agent)

        artifact_id = orch.execute_task("worker", "echo", {"msg": "hi"})
        artifact = store.get(artifact_id)
        assert artifact is not None
        assert artifact.content == {"msg": "hi"}

    def test_execute_task_unknown_agent(self):
        orch = Orchestrator()
        with pytest.raises(ValueError, match="No agent"):
            orch.execute_task("nobody", "echo", {})

    def test_run_workflow(self):
        orch = Orchestrator()
        bus, store = orch.message_bus, orch.artifact_store
        agent = Agent("worker", AgentRole.DEVELOPER, bus, store)
        agent.register_skill(EchoSkill())
        orch.register_agent(agent)

        wf = Workflow(name="simple")
        p = Phase(name="phase1")
        p.add_task("worker", "echo")
        wf.add_phase(p)

        results = orch.run_workflow(wf, {"input": "data"})
        assert len(results) == 1
        assert results[0]["status"] == "completed"
