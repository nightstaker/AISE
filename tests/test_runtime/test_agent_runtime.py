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


class TestAgentRuntimeTrace:
    def test_trace_written_on_success(self, agent_md_file, skills_dir, mock_create_deep_agent, tmp_path):
        import json

        from langchain_core.messages import AIMessage

        _, mock_agent = mock_create_deep_agent
        mock_agent.invoke.return_value = {"messages": [AIMessage(content="Done")]}

        trace_dir = tmp_path / "trace"
        runtime = AgentRuntime(
            agent_md=agent_md_file,
            skills_dir=skills_dir,
            model="openai:gpt-4o",
            trace_dir=trace_dir,
        )
        runtime.evoke()
        runtime.handle_message("hello")

        files = sorted(trace_dir.glob("*.json"))
        assert len(files) == 1, f"expected 1 trace file, got {len(files)}: {files}"
        record = json.loads(files[0].read_text())
        assert record["status"] == "completed"
        assert record["agent"] == "TestAgent"
        assert record["response"] == "Done"
        assert "llm_calls" in record
        assert record["call_id"].endswith("_0001")

    def test_trace_written_on_exception(self, agent_md_file, skills_dir, mock_create_deep_agent, tmp_path):
        import json

        _, mock_agent = mock_create_deep_agent
        mock_agent.invoke.side_effect = RuntimeError("Recursion limit of 160 reached without hitting a stop condition.")

        trace_dir = tmp_path / "trace"
        runtime = AgentRuntime(
            agent_md=agent_md_file,
            skills_dir=skills_dir,
            model="openai:gpt-4o",
            trace_dir=trace_dir,
        )
        runtime.evoke()
        with pytest.raises(RuntimeError, match="Recursion limit"):
            runtime.handle_message("hello")

        files = sorted(trace_dir.glob("*.json"))
        assert len(files) == 1, f"expected 1 trace file, got {len(files)}: {files}"
        record = json.loads(files[0].read_text())
        assert record["status"] == "failed"
        assert "Recursion limit" in record["error"]
        assert record["error_type"] == "RuntimeError"

    def test_default_recursion_limit_is_240(self, agent_md_file, skills_dir, mock_create_deep_agent):
        from langchain_core.messages import AIMessage

        _, mock_agent = mock_create_deep_agent
        mock_agent.invoke.return_value = {"messages": [AIMessage(content="ok")]}

        runtime = AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        runtime.evoke()
        runtime.handle_message("hi")

        _, kwargs = mock_agent.invoke.call_args
        assert kwargs["config"]["recursion_limit"] == 240


class TestAgentRuntimeTodos:
    def test_on_todos_update_fired_on_write_todos(self, agent_md_file, skills_dir, mock_create_deep_agent):
        """When the deepagents-internal write_todos tool fires, the
        on_todos_update callback should receive the todos list. We simulate
        this by driving the TraceLLMCallback attached via handle_message."""
        from langchain_core.messages import AIMessage

        _, mock_agent = mock_create_deep_agent
        captured: list[list[dict]] = []

        def simulate_write_todos(state, config=None):
            # Find the TraceLLMCallback and simulate a write_todos tool_start.
            callbacks = (config or {}).get("callbacks") or []
            for cb in callbacks:
                cb.on_tool_start(
                    serialized={"name": "write_todos"},
                    input_str="",
                    run_id=__import__("uuid").uuid4(),
                    inputs={
                        "todos": [
                            {"content": "Step A", "activeForm": "Doing A", "status": "in_progress"},
                            {"content": "Step B", "activeForm": "Doing B", "status": "pending"},
                        ]
                    },
                )
            return {"messages": [AIMessage(content="done")]}

        mock_agent.invoke.side_effect = simulate_write_todos

        runtime = AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        runtime.evoke()
        runtime.handle_message("hi", on_todos_update=captured.append)

        assert len(captured) == 1
        assert captured[0][0]["content"] == "Step A"
        assert captured[0][0]["status"] == "in_progress"


class TestExecuteToolBinding:
    """End-to-end: verify the ``execute`` tool is bound to a real
    ``CompiledStateGraph`` built via ``create_deep_agent``.

    Prior to the SandboxFilesystemBackend subclassing fix, the policy
    backend used ``setattr`` to attach ``execute``/``aexecute`` methods,
    but deepagents' ``FilesystemMiddleware`` checks
    ``isinstance(backend, SandboxBackendProtocol)`` to decide whether to
    register the tool. That check returned False (non-runtime-checkable
    ABC), so the ``execute`` tool was silently absent — worker agents'
    LLMs correctly reported "I don't have a tool to execute arbitrary
    shell commands" (dispatch e13a04cd449d, 2026-04-18).
    """

    def test_execute_tool_bound_on_deep_agent(self, agent_md_file, skills_dir, tmp_path):
        from langchain_core.language_models.fake_chat_models import (
            GenericFakeChatModel,
        )
        from langchain_core.messages import AIMessage

        from aise.runtime.agent_runtime import AgentRuntime
        from aise.runtime.policy_backend import make_policy_backend

        # A real (non-mock) create_deep_agent run — required to prove the
        # fix end-to-end. Use a GenericFakeChatModel so no real API calls
        # happen.
        model = GenericFakeChatModel(messages=iter([AIMessage(content="ok")]))
        backend = make_policy_backend(tmp_path)
        runtime = AgentRuntime(
            agent_md=agent_md_file,
            skills_dir=skills_dir,
            model=model,
            backend=backend,
        )
        tool_node = runtime._agent.nodes["tools"].bound
        tool_names = set(tool_node.tools_by_name.keys())
        assert "execute" in tool_names, f"execute tool must be bound on worker deep agents; got {sorted(tool_names)}"


class TestSummarizationPatch:
    """Validate the deepagents SummarizationMiddleware max_arg_length override.

    Without this patch, the default 2000-byte threshold truncates past
    ``write_file.content`` arguments to a 43-byte marker, which weak LLMs
    then copy back into new write_file calls — destroying the real file
    on disk (observed in dispatch 0b83037d0155).
    """

    def test_summarization_defaults_include_max_length(self):
        from deepagents import graph as da_graph

        from aise.runtime.agent_runtime import _SUMMARIZATION_MAX_ARG_LENGTH

        # Build a lightweight stand-in model that satisfies the
        # ``has_profile`` branch of ``_compute_summarization_defaults``.
        class _FakeModel:
            profile = {"max_input_tokens": 200_000}

        defaults = da_graph._compute_summarization_defaults(_FakeModel())
        truncate = defaults.get("truncate_args_settings") or {}
        assert truncate.get("max_length") == _SUMMARIZATION_MAX_ARG_LENGTH

    def test_patch_is_idempotent(self):
        from aise.runtime.agent_runtime import (
            _install_summarization_max_arg_length_patch,
        )

        # Running a second time must not re-wrap the already-patched function.
        _install_summarization_max_arg_length_patch()
        _install_summarization_max_arg_length_patch()

        from deepagents import graph as da_graph

        class _FakeModel:
            profile = {"max_input_tokens": 200_000}

        # Still a single max_length override, not nested.
        defaults = da_graph._compute_summarization_defaults(_FakeModel())
        truncate = defaults.get("truncate_args_settings") or {}
        assert "max_length" in truncate


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
