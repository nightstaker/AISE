"""Tests for the DeepOrchestrator high-level interface."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage

from aise.config import ModelConfig, ProjectConfig
from aise.core.agent import AgentRole
from aise.core.artifact import Artifact, ArtifactType
from aise.core.orchestrator import Orchestrator
from aise.core.skill import Skill, SkillContext
from aise.langchain.deep_orchestrator import DeepOrchestrator

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


class _EchoSkill(Skill):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echo skill"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={"echoed": input_data},
            producer="pm",
        )


def _make_orchestrator(num_agents: int = 1) -> Orchestrator:
    """Create a minimal Orchestrator with mock agents."""
    from aise.core.agent import Agent

    orch = Orchestrator()

    for i in range(num_agents):
        bus = orch.message_bus
        store = orch.artifact_store
        agent = Agent(
            name=f"product_manager{'_' + str(i) if i > 0 else ''}",
            role=AgentRole.PRODUCT_MANAGER,
            message_bus=bus,
            artifact_store=store,
            model_config=ModelConfig(provider="openai", model="gpt-4o"),
        )
        agent.register_skill(_EchoSkill())
        orch.register_agent(agent)

    return orch


@pytest.fixture()
def project_config() -> ProjectConfig:
    return ProjectConfig(
        project_name="DeepTest",
        default_model=ModelConfig(provider="openai", model="gpt-4o", api_key="test"),
    )


@pytest.fixture()
def orchestrator() -> Orchestrator:
    return _make_orchestrator()


# ---------------------------------------------------------------------------
# Tests: DeepOrchestrator construction
# ---------------------------------------------------------------------------


def test_deep_orchestrator_init(orchestrator: Orchestrator) -> None:
    deep = DeepOrchestrator(orchestrator)
    assert deep.orchestrator is orchestrator
    assert deep._graph is None


def test_from_orchestrator_factory(
    orchestrator: Orchestrator,
    project_config: ProjectConfig,
) -> None:
    deep = DeepOrchestrator.from_orchestrator(orchestrator, config=project_config)
    assert isinstance(deep, DeepOrchestrator)
    assert deep.config is project_config


def test_repr_before_build(orchestrator: Orchestrator) -> None:
    deep = DeepOrchestrator(orchestrator)
    assert "not built" in repr(deep)


# ---------------------------------------------------------------------------
# Tests: artifact_store and agents delegation
# ---------------------------------------------------------------------------


def test_artifact_store_delegates_to_orchestrator(orchestrator: Orchestrator) -> None:
    deep = DeepOrchestrator(orchestrator)
    assert deep.artifact_store is orchestrator.artifact_store


def test_agents_delegates_to_orchestrator(orchestrator: Orchestrator) -> None:
    deep = DeepOrchestrator(orchestrator)
    assert deep.agents is orchestrator.agents or deep.agents == orchestrator.agents


# ---------------------------------------------------------------------------
# Tests: execute_task backward compatibility
# ---------------------------------------------------------------------------


def test_execute_task_delegates_to_orchestrator(orchestrator: Orchestrator) -> None:
    deep = DeepOrchestrator(orchestrator)
    artifact_id = deep.execute_task(
        agent_name="product_manager",
        skill_name="echo",
        input_data={"raw_requirements": "test"},
        project_name="TestProject",
    )
    assert isinstance(artifact_id, str)
    artifact = orchestrator.artifact_store.get(artifact_id)
    assert artifact is not None


# ---------------------------------------------------------------------------
# Tests: build()
# ---------------------------------------------------------------------------


@pytest.fixture()
def _patch_llm():
    """Patch LLM creation to avoid requiring a real API key in unit tests."""
    with (
        patch("aise.langchain.agent_node._build_llm") as mock_build,
        patch("aise.langchain.supervisor._build_supervisor_llm") as mock_sup,
    ):
        mock_llm = MagicMock()
        mock_llm.with_structured_output.return_value = MagicMock()
        mock_build.return_value = mock_llm
        mock_sup.return_value = mock_llm
        with patch("aise.langchain.agent_node.create_agent") as mock_react:
            mock_agent = MagicMock()
            mock_agent.invoke.return_value = {"messages": [AIMessage(content="done")]}
            mock_react.return_value = mock_agent
            yield


def test_build_creates_graph(
    orchestrator: Orchestrator,
    project_config: ProjectConfig,
    _patch_llm,
) -> None:
    deep = DeepOrchestrator(orchestrator, project_config=project_config)
    deep.build()
    assert deep._graph is not None
    assert "product_manager" in deep._agent_nodes


def test_build_repr_shows_built(
    orchestrator: Orchestrator,
    project_config: ProjectConfig,
    _patch_llm,
) -> None:
    deep = DeepOrchestrator(orchestrator, project_config=project_config)
    deep.build()
    assert "built" in repr(deep)


# ---------------------------------------------------------------------------
# Tests: run_workflow (with mocked graph)
# ---------------------------------------------------------------------------


def _stub_graph_success(initial_state: dict) -> dict:
    """Stub that simulates a completed workflow."""
    return {
        **initial_state,
        "phase_results": {
            "requirements_product_manager": "completed",
            "design_architect": "completed",
            "implementation_developer": "completed",
            "testing_qa_engineer": "completed",
        },
        "artifact_ids": ["art1", "art2"],
        "messages": [AIMessage(content="All phases done")],
        "current_phase": "complete",
        "next_agent": "FINISH",
    }


def test_run_workflow_success(
    orchestrator: Orchestrator,
    project_config: ProjectConfig,
    _patch_llm,
) -> None:
    deep = DeepOrchestrator(orchestrator, project_config=project_config)
    deep.build()

    # Patch the compiled graph's invoke method
    mock_graph = MagicMock()
    mock_graph.invoke.side_effect = _stub_graph_success
    deep._graph = mock_graph

    result = deep.run_workflow(
        {"raw_requirements": "Build a REST API"},
        project_name="MyProject",
    )

    assert result["status"] == "completed"
    assert "requirements_product_manager" in result["phase_results"]
    assert "art1" in result["artifact_ids"]
    mock_graph.invoke.assert_called_once()


def test_run_workflow_handles_exception(
    orchestrator: Orchestrator,
    project_config: ProjectConfig,
    _patch_llm,
) -> None:
    deep = DeepOrchestrator(orchestrator, project_config=project_config)
    deep.build()

    mock_graph = MagicMock()
    mock_graph.invoke.side_effect = RuntimeError("graph crashed")
    deep._graph = mock_graph

    result = deep.run_workflow({"raw_requirements": "test"})

    assert result["status"] == "error"
    assert "graph crashed" in result["error"]
    assert result["phase_results"] == {}


def test_run_workflow_builds_graph_lazily(
    orchestrator: Orchestrator,
    project_config: ProjectConfig,
    _patch_llm,
) -> None:
    """Graph should be built automatically if run_workflow is called without build()."""
    deep = DeepOrchestrator(orchestrator, project_config=project_config)
    assert deep._graph is None

    mock_graph = MagicMock()
    mock_graph.invoke.side_effect = _stub_graph_success

    # Intercept build to inject mock after real build runs
    original_build = deep.build

    def patched_build():
        original_build()
        deep._graph = mock_graph

    deep.build = patched_build  # type: ignore[method-assign]

    result = deep.run_workflow({"raw_requirements": "lazy build test"})
    assert result["status"] == "completed"


def test_run_workflow_uses_project_name_from_config(
    orchestrator: Orchestrator,
    project_config: ProjectConfig,
    _patch_llm,
) -> None:
    """When no explicit project_name is given, config.project_name is used."""
    deep = DeepOrchestrator(orchestrator, project_config=project_config)
    deep.build()

    captured_states: list[dict] = []

    def capture_and_return(state: dict) -> dict:
        captured_states.append(state)
        return _stub_graph_success(state)

    mock_graph = MagicMock()
    mock_graph.invoke.side_effect = capture_and_return
    deep._graph = mock_graph

    deep.run_workflow({"raw_requirements": "test"})  # no explicit project_name

    assert captured_states[0]["project_name"] == project_config.project_name
