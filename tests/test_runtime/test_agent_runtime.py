"""Tests for AgentRuntime."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aise.runtime.agent_runtime import AgentRuntime, _load_inline_skill_content
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


class TestSystemPromptAssembly:
    """The final system_prompt passed to ``create_deep_agent`` must:

    - append a path-policy block telling the LLM not to use absolute host paths
    - inline every SKILL.md body (so we can stop passing ``skills=`` to
      ``create_deep_agent`` and prevent deepagents' SkillsMiddleware from
      leaking AISE's absolute source-tree paths into the prompt)
    - NOT contain any absolute host path (``/home/``, ``/etc/``, etc.)
    """

    def test_system_prompt_includes_path_policy(self, agent_md_file, skills_dir, mock_create_deep_agent):
        mock_factory, _ = mock_create_deep_agent
        AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        _, kwargs = mock_factory.call_args
        prompt = kwargs.get("system_prompt", "")
        assert "File Path Policy" in prompt
        assert "relative path" in prompt.lower()
        assert "/home" in prompt  # appears inside a "Forbidden" list, not a skill path
        # But "/home/ntstaker" — the concrete AISE absolute — must NOT appear:
        assert "/home/ntstaker/workspace/AISE" not in prompt
        assert "/home/ntstaker" not in prompt

    def test_system_prompt_does_not_pass_skills_kwarg(self, agent_md_file, skills_dir, mock_create_deep_agent):
        """Regression: ``create_deep_agent`` must NOT be called with
        ``skills=``. Passing skills would re-activate deepagents'
        SkillsMiddleware, which re-injects the absolute source-tree
        path into the system prompt."""
        mock_factory, _ = mock_create_deep_agent
        AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        _, kwargs = mock_factory.call_args
        assert "skills" not in kwargs or kwargs["skills"] is None

    def test_system_prompt_inlines_declared_skill_bodies(self, agent_md_file, skills_dir, mock_create_deep_agent):
        """Skills in ``skills_dir/<name>/SKILL.md`` are inlined into the
        system prompt when ``<name>`` matches one of the agent's declared
        skills (parsed from the ``## Skills`` block in agent.md)."""
        # SAMPLE_AGENT_MD declares ``test_skill`` — so a skill directory
        # named ``test_skill`` is the one that should be inlined.
        skill_dir = skills_dir / "test_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# test_skill\n\nThis is a MAGIC_SKILL_MARKER body.\n")
        mock_factory, _ = mock_create_deep_agent
        AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        _, kwargs = mock_factory.call_args
        prompt = kwargs.get("system_prompt", "")
        assert "## Available Skills" in prompt
        assert "### test_skill" in prompt
        assert "MAGIC_SKILL_MARKER" in prompt

    def test_system_prompt_excludes_undeclared_skill_bodies(self, agent_md_file, skills_dir, mock_create_deep_agent):
        """Regression guard for PR #101: a ``SKILL.md`` in ``skills_dir``
        that the agent does NOT declare in its ``## Skills`` block must
        not be inlined into the prompt. Previously every skill was
        broadcast to every agent, so developer-specific TDD guidance
        leaked into the architect's prompt and caused 4/4 architect
        dispatches to exit without tool calls."""
        declared_dir = skills_dir / "test_skill"  # declared in SAMPLE_AGENT_MD
        declared_dir.mkdir()
        (declared_dir / "SKILL.md").write_text("# test_skill\ndeclared body\n")
        undeclared_dir = skills_dir / "tdd"  # NOT declared by SAMPLE_AGENT_MD
        undeclared_dir.mkdir()
        (undeclared_dir / "SKILL.md").write_text("# tdd\nUNDECLARED_SKILL_MARKER: write tests first, then src.\n")
        mock_factory, _ = mock_create_deep_agent
        AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        _, kwargs = mock_factory.call_args
        prompt = kwargs.get("system_prompt", "")
        assert "### test_skill" in prompt
        assert "### tdd" not in prompt
        assert "UNDECLARED_SKILL_MARKER" not in prompt

    def test_system_prompt_no_absolute_aise_paths_with_skills(self, agent_md_file, skills_dir, mock_create_deep_agent):
        """Even with a skill present, the resulting prompt should have
        zero references to ``/home/*/AISE`` — the skill body is inlined
        by filename (``### test_skill``) not path."""
        skill_dir = skills_dir / "test_skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text("# test_skill\ncontent\n")
        mock_factory, _ = mock_create_deep_agent
        AgentRuntime(agent_md=agent_md_file, skills_dir=skills_dir, model="openai:gpt-4o")
        _, kwargs = mock_factory.call_args
        prompt = kwargs.get("system_prompt", "")
        assert str(skills_dir) not in prompt, f"skills_dir absolute path leaked into prompt: {skills_dir}"


class TestLoadInlineSkillContentFilter:
    """Unit tests for the per-agent skill filter in
    ``_load_inline_skill_content``. The filter (added after PR #101
    leaked developer-only TDD guidance into every agent's prompt) must:

    - when called with ``declared_skill_names=None``, load every skill
      in the directory (legacy behavior, used by tests that don't care);
    - when called with a set, load ONLY skills whose directory name is
      a member of that set.
    """

    def _write_skill(self, skills_dir: Path, name: str, body: str) -> None:
        d = skills_dir / name
        d.mkdir()
        (d / "SKILL.md").write_text(body)

    def test_none_loads_everything(self, skills_dir):
        self._write_skill(skills_dir, "tdd", "# tdd\nbody\n")
        self._write_skill(skills_dir, "design", "# design\nbody\n")
        got = _load_inline_skill_content(skills_dir, None)
        assert {name for name, _ in got} == {"tdd", "design"}

    def test_empty_set_loads_nothing(self, skills_dir):
        self._write_skill(skills_dir, "tdd", "# tdd\nbody\n")
        got = _load_inline_skill_content(skills_dir, set())
        assert got == []

    def test_filters_by_declared_names(self, skills_dir):
        self._write_skill(skills_dir, "tdd", "# tdd\ntdd body\n")
        self._write_skill(skills_dir, "design", "# design\ndesign body\n")
        self._write_skill(skills_dir, "review", "# review\nreview body\n")
        got = _load_inline_skill_content(skills_dir, {"tdd", "review"})
        assert {name for name, _ in got} == {"tdd", "review"}

    def test_missing_skills_dir_returns_empty(self, tmp_path):
        got = _load_inline_skill_content(tmp_path / "does_not_exist", {"tdd"})
        assert got == []


class TestRealAgentPromptsSkillIsolation:
    """End-to-end regression guard using the actual agent.md files and
    the actual ``_runtime_skills/`` directory shipped with the repo.
    PR #101 inlined every ``*/SKILL.md`` into every agent's system
    prompt; the only skill present was ``tdd/SKILL.md`` (intended for
    developer), so architect, product_manager, and qa_engineer prompts
    all ended up containing RED/GREEN/VERIFY instructions that
    contradicted their roles. This test pins the fix.
    """

    AGENTS_DIR = Path(__file__).resolve().parents[2] / "src" / "aise" / "agents"
    SKILLS_DIR = AGENTS_DIR / "_runtime_skills"

    def _prompt_for(self, agent_name: str, mock_factory) -> str:
        agent_md = self.AGENTS_DIR / f"{agent_name}.md"
        assert agent_md.is_file(), f"missing fixture: {agent_md}"
        AgentRuntime(agent_md=agent_md, skills_dir=self.SKILLS_DIR, model="openai:gpt-4o")
        _, kwargs = mock_factory.call_args
        return kwargs.get("system_prompt", "") or ""

    def test_developer_prompt_contains_tdd_skill(self, mock_create_deep_agent):
        """Positive: developer declares ``tdd`` in its ``## Skills``
        block, so the TDD body must appear in its prompt."""
        mock_factory, _ = mock_create_deep_agent
        prompt = self._prompt_for("developer", mock_factory)
        assert "### tdd" in prompt
        # Check for a stable phrase from tdd/SKILL.md so a future
        # rename in the body triggers a visible failure:
        assert "Test-Driven" in prompt or "test" in prompt.lower()

    def test_architect_prompt_does_not_contain_tdd_skill(self, mock_create_deep_agent):
        """Negative (the PR #101 regression guard): architect does not
        declare ``tdd`` in its ``## Skills`` block, so the TDD body
        must NOT appear in its prompt."""
        mock_factory, _ = mock_create_deep_agent
        prompt = self._prompt_for("architect", mock_factory)
        assert "### tdd" not in prompt, (
            "TDD skill body leaked into architect prompt — this is the PR #101 "
            "regression. Architect does not declare tdd in its ## Skills; the "
            "filter in _load_inline_skill_content must exclude it."
        )

    def test_product_manager_prompt_does_not_contain_tdd_skill(self, mock_create_deep_agent):
        mock_factory, _ = mock_create_deep_agent
        prompt = self._prompt_for("project_manager", mock_factory)
        assert "### tdd" not in prompt

    def test_qa_engineer_prompt_does_not_contain_tdd_skill(self, mock_create_deep_agent):
        mock_factory, _ = mock_create_deep_agent
        qa_md = self.AGENTS_DIR / "qa_engineer.md"
        if not qa_md.is_file():
            pytest.skip("qa_engineer.md not present in this tree")
        prompt = self._prompt_for("qa_engineer", mock_factory)
        assert "### tdd" not in prompt


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
