"""Tests for RuntimeManager."""

from unittest.mock import MagicMock, patch

import pytest

from aise.runtime.manager import RuntimeManager, _discover_agent_md_files
from aise.runtime.models import AgentState


class TestDiscoverAgentMdFiles:
    def test_discovers_existing_md_files(self):
        files = _discover_agent_md_files()
        names = {f.stem for f in files}
        assert "developer" in names
        assert "architect" in names
        assert "product_manager" in names
        assert "qa_engineer" in names
        assert "project_manager" in names
        assert "rd_director" in names

    def test_all_files_are_md(self):
        files = _discover_agent_md_files()
        assert all(f.suffix == ".md" for f in files)


@pytest.fixture
def mock_create_deep_agent():
    """Mock create_deep_agent and _build_llm so tests don't need a real LLM."""
    from langchain_core.messages import AIMessage

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {"messages": [AIMessage(content="ok")]}

    mock_llm = MagicMock()

    with (
        patch("aise.runtime.agent_runtime.create_deep_agent", return_value=mock_agent),
        patch("aise.runtime.manager._build_llm", return_value=mock_llm),
    ):
        yield


class TestRuntimeManager:
    def test_start_discovers_and_inits(self, mock_create_deep_agent):
        manager = RuntimeManager()
        manager.start()
        assert len(manager.runtimes) >= 6
        assert "developer" in manager.runtimes
        assert "architect" in manager.runtimes
        assert "product_manager" in manager.runtimes
        manager.stop()

    def test_runtimes_are_active(self, mock_create_deep_agent):
        manager = RuntimeManager()
        manager.start()
        for rt in manager.runtimes.values():
            assert rt.state == AgentState.ACTIVE
        manager.stop()

    def test_start_idempotent(self, mock_create_deep_agent):
        manager = RuntimeManager()
        manager.start()
        count = len(manager.runtimes)
        manager.start()  # Should not double-register
        assert len(manager.runtimes) == count
        manager.stop()

    def test_stop_clears_runtimes(self, mock_create_deep_agent):
        manager = RuntimeManager()
        manager.start()
        assert len(manager.runtimes) > 0
        manager.stop()
        assert len(manager.runtimes) == 0

    def test_get_runtime(self, mock_create_deep_agent):
        manager = RuntimeManager()
        manager.start()
        rt = manager.get_runtime("developer")
        assert rt is not None
        assert rt.name == "developer"
        assert manager.get_runtime("nonexistent") is None
        manager.stop()

    def test_runtimes_are_agent_runtime_instances(self, mock_create_deep_agent):
        from aise.runtime.agent_runtime import AgentRuntime

        manager = RuntimeManager()
        manager.start()
        for rt in manager.runtimes.values():
            assert isinstance(rt, AgentRuntime)
        manager.stop()


class TestRuntimeManagerStatus:
    def test_get_agents_status_structure(self, mock_create_deep_agent):
        manager = RuntimeManager()
        manager.start()
        status = manager.get_agents_status()
        assert len(status) >= 6

        dev = next((a for a in status if a["name"] == "developer"), None)
        assert dev is not None
        assert dev["source"] == "runtime"
        assert dev["status"] == "standby"
        assert "agent_id" in dev
        assert isinstance(dev["skills"], list)
        assert len(dev["skills"]) > 0
        manager.stop()

    def test_agent_card_present(self, mock_create_deep_agent):
        manager = RuntimeManager()
        manager.start()
        status = manager.get_agents_status()
        dev = next(a for a in status if a["name"] == "developer")

        card = dev["agent_card"]
        assert card["name"] == "developer"
        assert "skills" in card
        assert "capabilities" in card
        assert "model" in card
        assert isinstance(card["skills"], list)
        assert len(card["skills"]) > 0
        # Each skill should have id, name, description
        skill = card["skills"][0]
        assert "id" in skill
        assert "name" in skill
        assert "description" in skill
        manager.stop()

    def test_model_info_present(self, mock_create_deep_agent):
        manager = RuntimeManager()
        manager.start()
        status = manager.get_agents_status()
        dev = next(a for a in status if a["name"] == "developer")

        model = dev["model"]
        assert "provider" in model
        assert "model" in model
        manager.stop()

    def test_stop_then_status_empty(self, mock_create_deep_agent):
        manager = RuntimeManager()
        manager.start()
        manager.stop()
        assert manager.get_agents_status() == []
