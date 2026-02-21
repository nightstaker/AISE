"""Tests for the LangChain agent node factory."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from aise.config import ModelConfig
from aise.core.agent import Agent, AgentRole
from aise.core.artifact import Artifact, ArtifactStore, ArtifactType
from aise.core.message import MessageBus
from aise.core.skill import Skill, SkillContext
from aise.langchain.agent_node import (
    _DEFAULT_SYSTEM_PROMPT,
    AGENT_SYSTEM_PROMPTS,
    _build_llm,
    _suggest_skills_for_phase,
    make_agent_node,
)

# ---------------------------------------------------------------------------
# Helpers / Fixtures
# ---------------------------------------------------------------------------


class _SimpleSkill(Skill):
    @property
    def name(self) -> str:
        return "simple_skill"

    @property
    def description(self) -> str:
        return "A simple test skill."

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={"done": True},
            producer="test_agent",
        )


@pytest.fixture()
def artifact_store() -> ArtifactStore:
    return ArtifactStore()


@pytest.fixture()
def skill_context(artifact_store: ArtifactStore) -> SkillContext:
    return SkillContext(
        artifact_store=artifact_store,
        project_name="TestProject",
        parameters={},
        model_config=ModelConfig(provider="openai", model="gpt-4o", api_key="test"),
    )


@pytest.fixture()
def test_agent(artifact_store: ArtifactStore) -> Agent:
    bus = MessageBus()
    agent = Agent(
        name="product_manager",
        role=AgentRole.PRODUCT_MANAGER,
        message_bus=bus,
        artifact_store=artifact_store,
        model_config=ModelConfig(provider="openai", model="gpt-4o", api_key="test"),
    )
    agent.register_skill(_SimpleSkill())
    return agent


def _make_workflow_state(phase: str = "requirements") -> dict[str, Any]:
    return {
        "messages": [HumanMessage(content="start")],
        "project_name": "TestProject",
        "project_input": {"raw_requirements": "Build a service"},
        "current_phase": phase,
        "phase_results": {},
        "artifact_ids": [],
        "next_agent": "product_manager",
        "error": None,
        "iteration": 0,
    }


# ---------------------------------------------------------------------------
# Tests: AGENT_SYSTEM_PROMPTS
# ---------------------------------------------------------------------------


def test_system_prompts_cover_core_agents() -> None:
    """All four primary SDLC agents must have a system prompt."""
    for role in ("product_manager", "architect", "developer", "qa_engineer"):
        assert role in AGENT_SYSTEM_PROMPTS
        assert len(AGENT_SYSTEM_PROMPTS[role]) > 50  # non-trivial content


def test_default_system_prompt_is_non_empty() -> None:
    assert len(_DEFAULT_SYSTEM_PROMPT) > 10


# ---------------------------------------------------------------------------
# Tests: _build_llm
# ---------------------------------------------------------------------------


def test_build_llm_returns_chat_openai() -> None:
    from langchain_openai import ChatOpenAI

    config = ModelConfig(provider="openai", model="gpt-4o", api_key="test-key")
    llm = _build_llm(config)
    assert isinstance(llm, ChatOpenAI)


def test_build_llm_uses_base_url_when_set() -> None:
    from langchain_openai import ChatOpenAI

    config = ModelConfig(
        provider="custom",
        model="custom-model",
        api_key="key",
        base_url="https://custom.example.com/v1",
    )
    llm = _build_llm(config)
    assert isinstance(llm, ChatOpenAI)


# ---------------------------------------------------------------------------
# Tests: make_agent_node
# ---------------------------------------------------------------------------


def test_make_agent_node_returns_callable(
    test_agent: Agent,
    skill_context: SkillContext,
) -> None:
    with patch("aise.langchain.agent_node.create_runtime_agent") as mock_create_runtime:
        mock_create_runtime.return_value = MagicMock()
        node_fn = make_agent_node(test_agent, skill_context)
    assert callable(node_fn)


def test_agent_node_name_matches_agent(
    test_agent: Agent,
    skill_context: SkillContext,
) -> None:
    with patch("aise.langchain.agent_node.create_runtime_agent") as mock_create_runtime:
        mock_create_runtime.return_value = MagicMock()
        node_fn = make_agent_node(test_agent, skill_context)
    assert node_fn.__name__ == "product_manager"


def test_agent_node_returns_dict_with_messages_and_phase_results(
    test_agent: Agent,
    skill_context: SkillContext,
) -> None:
    """Agent node must return a dict with 'messages' and 'phase_results' keys."""
    mock_result = {"messages": [AIMessage(content="Work done")]}

    with patch("aise.langchain.agent_node.create_runtime_agent") as mock_create_runtime:
        mock_runtime = MagicMock()
        mock_runtime.invoke.return_value = mock_result
        mock_create_runtime.return_value = mock_runtime

        node_fn2 = make_agent_node(test_agent, skill_context)
        state = _make_workflow_state("requirements")
        result = node_fn2(state)

    assert "messages" in result
    assert "phase_results" in result
    assert result["phase_results"].get("requirements_product_manager") == "completed"


def test_agent_node_handles_react_exception(
    test_agent: Agent,
    skill_context: SkillContext,
) -> None:
    """Agent node must handle ReAct agent exceptions gracefully."""
    with patch("aise.langchain.agent_node.create_runtime_agent") as mock_create_runtime:
        mock_runtime = MagicMock()
        mock_runtime.invoke.side_effect = RuntimeError("LLM API error")
        mock_create_runtime.return_value = mock_runtime

        node_fn = make_agent_node(test_agent, skill_context)
        state = _make_workflow_state("requirements")
        result = node_fn(state)

    assert "messages" in result
    assert "error" in result
    assert "LLM API error" in result["error"]


def test_agent_node_uses_correct_system_prompt(
    test_agent: Agent,
    skill_context: SkillContext,
) -> None:
    """make_agent_node must pass the role-appropriate system prompt to runtime builder."""
    with patch("aise.langchain.agent_node.create_runtime_agent") as mock_create_runtime:
        mock_create_runtime.return_value = MagicMock()
        make_agent_node(test_agent, skill_context)

        prompt_arg = mock_create_runtime.call_args.args[2]
        expected_prompt = AGENT_SYSTEM_PROMPTS.get(test_agent.name, _DEFAULT_SYSTEM_PROMPT)
        assert prompt_arg == expected_prompt


def test_agent_node_clears_error_on_success(
    test_agent: Agent,
    skill_context: SkillContext,
) -> None:
    """A successful agent node execution should set error to None."""
    with patch("aise.langchain.agent_node.create_runtime_agent") as mock_create_runtime:
        mock_runtime = MagicMock()
        mock_runtime.invoke.return_value = {"messages": [AIMessage(content="done")]}
        mock_create_runtime.return_value = mock_runtime

        node_fn = make_agent_node(test_agent, skill_context)
        state = _make_workflow_state()
        result = node_fn(state)

    assert result.get("error") is None


def test_suggest_skills_for_phase_uses_agent_playbook_order() -> None:
    skills = [
        "product_review",
        "requirement_analysis",
        "product_design",
        "system_feature_analysis",
        "custom_skill",
    ]
    ordered = _suggest_skills_for_phase("product_manager", "requirements", skills)

    assert ordered[:4] == [
        "requirement_analysis",
        "system_feature_analysis",
        "product_design",
        "product_review",
    ]
    assert ordered[-1] == "custom_skill"
