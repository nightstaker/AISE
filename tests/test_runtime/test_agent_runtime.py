"""Tests for AgentRuntime."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aise.runtime.agent_runtime import AgentRuntime
from aise.runtime.models import AgentState

SAMPLE_AGENT_MD = """\
---
name: TestAgent
description: A test agent
version: 1.0.0
---

# System Prompt

You are a test agent.

## Skills

- test_skill: A test skill
"""


@pytest.fixture
def agent_md_file(tmp_path: Path) -> Path:
    f = tmp_path / "agent.md"
    f.write_text(SAMPLE_AGENT_MD)
    return f


@pytest.fixture
def skills_dir(tmp_path: Path) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    return d


@pytest.fixture
def mock_create_deep_agent():
    from langchain_core.messages import AIMessage

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {"messages": [AIMessage(content="Hello from agent!")]}

    with patch("aise.runtime.agent_runtime.create_deep_agent", return_value=mock_agent) as mock_factory:
        yield mock_factory, mock_agent


class TestAgentRuntimeLifecycle:
    def test_init_creates_agent(self, agent_md_file, skills_dir, mock_create_deep_agent):
        mock_factory, _ = mock_create_deep_agent
        runtime = AgentRuntime(
            agent_md=agent_md_file,
            skills_dir=skills_dir,
            model="openai:gpt-4o",
        )
        assert runtime.state == AgentState.CREATED
        assert runtime.name == "TestAgent"
        mock_factory.assert_called_once()

    def test_evoke_activates(self, agent_md_file, skills_dir, mock_create_deep_agent):
        runtime = AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        runtime.evoke()
        assert runtime.state == AgentState.ACTIVE

    def test_evoke_idempotent(self, agent_md_file, skills_dir, mock_create_deep_agent):
        runtime = AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        runtime.evoke()
        runtime.evoke()  # Should not raise
        assert runtime.state == AgentState.ACTIVE

    def test_stop(self, agent_md_file, skills_dir, mock_create_deep_agent):
        runtime = AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        runtime.evoke()
        runtime.stop()
        assert runtime.state == AgentState.STOPPED

    def test_re_evoke_after_stop(self, agent_md_file, skills_dir, mock_create_deep_agent):
        runtime = AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        runtime.evoke()
        runtime.stop()
        runtime.evoke()
        assert runtime.state == AgentState.ACTIVE


class TestAgentRuntimeMessaging:
    def test_handle_message_requires_active(self, agent_md_file, skills_dir, mock_create_deep_agent):
        runtime = AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        with pytest.raises(RuntimeError, match="not active"):
            runtime.handle_message("hello")

    def test_handle_message_success(self, agent_md_file, skills_dir, mock_create_deep_agent):
        _, mock_agent = mock_create_deep_agent
        # Set up mock to return a proper response
        from langchain_core.messages import AIMessage

        mock_agent.invoke.return_value = {"messages": [AIMessage(content="Response text")]}

        runtime = AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        runtime.evoke()
        response = runtime.handle_message("hello")
        assert response == "Response text"
        mock_agent.invoke.assert_called_once()

    def test_handle_message_after_stop_raises(self, agent_md_file, skills_dir, mock_create_deep_agent):
        runtime = AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        runtime.evoke()
        runtime.stop()
        with pytest.raises(RuntimeError, match="not active"):
            runtime.handle_message("hello")


class TestAgentRuntimeCard:
    def test_agent_card_generated(self, agent_md_file, skills_dir, mock_create_deep_agent):
        runtime = AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        card = runtime.agent_card
        assert card.name == "TestAgent"
        assert card.description == "A test agent"
        assert len(card.skills) >= 1

    def test_agent_card_dict(self, agent_md_file, skills_dir, mock_create_deep_agent):
        runtime = AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        d = runtime.get_agent_card_dict()
        assert d["name"] == "TestAgent"
        assert "skills" in d
        assert "capabilities" in d
        assert d["defaultInputModes"] == ["text"]
