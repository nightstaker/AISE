"""Tests for the generic primitive tools."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aise.runtime.runtime_config import RuntimeConfig, ShellConfig
from aise.runtime.tool_primitives import (
    ToolContext,
    WorkflowState,
    build_orchestrator_tools,
    make_completion_tool,
    make_discovery_tools,
    make_dispatch_tools,
    make_shell_tool,
)


def _mock_runtime(name: str, role: str = "worker", response: str = "ok"):
    """Build a fake AgentRuntime for the manager registry."""
    rt = MagicMock()
    rt.name = name
    rt.handle_message.return_value = response
    rt.get_agent_card_dict.return_value = {
        "name": name,
        "description": f"{name} agent",
        "skills": [],
        "capabilities": {},
    }
    rt.definition = MagicMock()
    rt.definition.role = role
    return rt


@pytest.fixture
def fake_manager():
    mgr = MagicMock()
    mgr.runtimes = {
        "developer": _mock_runtime("developer", "worker"),
        "qa": _mock_runtime("qa", "worker"),
        "project_manager": _mock_runtime("project_manager", "orchestrator"),
    }
    mgr.get_runtime = lambda n: mgr.runtimes.get(n)
    return mgr


@pytest.fixture
def ctx(tmp_path: Path, fake_manager):
    return ToolContext(
        manager=fake_manager,
        project_root=tmp_path,
        config=RuntimeConfig(),
        workflow_state=WorkflowState(),
    )


# -- Discovery -------------------------------------------------------------


class TestDiscoveryTools:
    def test_list_processes_returns_real_processes(self, ctx):
        tools = make_discovery_tools(ctx)
        list_proc = next(t for t in tools if t.name == "list_processes")
        result = json.loads(list_proc.invoke({}))
        ids = [p["process_id"] for p in result["processes"]]
        assert "waterfall_standard_v1" in ids

    def test_get_process_round_trip(self, ctx):
        tools = make_discovery_tools(ctx)
        get_proc = next(t for t in tools if t.name == "get_process")
        result = get_proc.invoke({"process_file": "waterfall.process.md"})
        assert "waterfall" in result.lower()

    def test_get_process_not_found(self, ctx):
        tools = make_discovery_tools(ctx)
        get_proc = next(t for t in tools if t.name == "get_process")
        result = json.loads(get_proc.invoke({"process_file": "ghost.md"}))
        assert "error" in result

    def test_list_agents_excludes_orchestrator(self, ctx):
        tools = make_discovery_tools(ctx)
        list_ag = next(t for t in tools if t.name == "list_agents")
        result = json.loads(list_ag.invoke({}))
        names = [a["name"] for a in result["agents"]]
        assert "developer" in names
        assert "qa" in names
        assert "project_manager" not in names

    def test_list_agents_excludes_legacy_pm_without_role(self, tmp_path: Path):
        """An agent named 'project_manager' is excluded even without role:orchestrator."""
        mgr = MagicMock()
        mgr.runtimes = {
            "developer": _mock_runtime("developer", role=""),
            "project_manager": _mock_runtime("project_manager", role=""),
        }
        ctx_ = ToolContext(
            manager=mgr,
            project_root=tmp_path,
            config=RuntimeConfig(),
            workflow_state=WorkflowState(),
        )
        tools = make_discovery_tools(ctx_)
        list_ag = next(t for t in tools if t.name == "list_agents")
        result = json.loads(list_ag.invoke({}))
        names = [a["name"] for a in result["agents"]]
        assert "developer" in names
        assert "project_manager" not in names


# -- Dispatch --------------------------------------------------------------


class TestDispatchTools:
    def test_dispatch_task_success(self, ctx):
        tools = make_dispatch_tools(ctx)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        result = json.loads(
            dispatch.invoke(
                {
                    "agent_name": "developer",
                    "task_description": "implement",
                    "step_id": "s1",
                    "phase": "implementation",
                }
            )
        )
        assert result["type"] == "task_response"
        assert result["from"] == "developer"
        assert result["status"] == "completed"

    def test_dispatch_task_not_found(self, ctx):
        tools = make_dispatch_tools(ctx)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        result = json.loads(dispatch.invoke({"agent_name": "ghost", "task_description": "x"}))
        assert result["status"] == "failed"
        assert "not found" in result["error"]

    def test_dispatch_task_records_events(self, ctx):
        tools = make_dispatch_tools(ctx)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        dispatch.invoke({"agent_name": "developer", "task_description": "x", "phase": "p"})
        types = [e["type"] for e in ctx.event_log]
        assert "task_request" in types
        assert "task_response" in types
        assert "stage_update" in types

    def test_dispatch_task_max_dispatches_cap(self, ctx):
        ctx.config = RuntimeConfig()
        ctx.config.safety_limits.max_dispatches = 1
        tools = make_dispatch_tools(ctx)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        # First dispatch ok
        json.loads(dispatch.invoke({"agent_name": "developer", "task_description": "x"}))
        # Second exceeds the cap
        result = json.loads(dispatch.invoke({"agent_name": "developer", "task_description": "y"}))
        assert result["status"] == "failed"
        assert "Maximum dispatches" in result["error"]

    def test_dispatch_tasks_parallel(self, ctx):
        tools = make_dispatch_tools(ctx)
        parallel = next(t for t in tools if t.name == "dispatch_tasks_parallel")
        payload = json.dumps(
            [
                {"agent_name": "developer", "task_description": "a"},
                {"agent_name": "qa", "task_description": "b"},
            ]
        )
        result = json.loads(parallel.invoke({"tasks_json": payload}))
        assert result["completed"] == 2
        assert result["total"] == 2


# -- Shell -----------------------------------------------------------------


class TestShellTool:
    def test_shell_refuses_non_allowlisted(self, ctx):
        tool = make_shell_tool(ctx)
        result = json.loads(tool.invoke({"command": "rm -rf /"}))
        assert result["status"] == "refused"

    def test_shell_runs_python_version(self, ctx):
        tool = make_shell_tool(ctx)
        result = json.loads(tool.invoke({"command": "python --version"}))
        assert result["status"] == "completed"
        assert result["exit_code"] == 0

    def test_shell_cwd_must_stay_inside_project(self, ctx):
        tool = make_shell_tool(ctx)
        result = json.loads(tool.invoke({"command": "python --version", "cwd": "../escape"}))
        assert result["status"] == "refused"

    def test_shell_unknown_executable(self, tmp_path):
        # With shell=True, unknown commands return exit_code=127 (not FileNotFoundError).
        ctx_ = ToolContext(
            manager=MagicMock(runtimes={}),
            project_root=tmp_path,
            config=RuntimeConfig(shell=ShellConfig(allowlist=("definitely-not-here",))),
            workflow_state=WorkflowState(),
        )
        tool = make_shell_tool(ctx_)
        result = json.loads(tool.invoke({"command": "definitely-not-here"}))
        assert result["status"] == "completed"
        assert result["exit_code"] != 0  # 127 = command not found

    def test_shell_strips_cd_prefix(self, ctx):
        """cd /path && command should strip cd and run command in project root."""
        tool = make_shell_tool(ctx)
        result = json.loads(tool.invoke({"command": "cd /tmp && python --version"}))
        assert result["status"] == "completed"
        assert result["exit_code"] == 0

    def test_shell_cd_only_is_harmless(self, ctx):
        """cd /path alone is harmless (no strip needed, just runs cd in subprocess)."""
        tool = make_shell_tool(ctx)
        result = json.loads(tool.invoke({"command": "cd /tmp"}))
        # cd alone is allowed by allowlist (_SHELL_BUILTINS), exits 0, does nothing
        assert result["status"] == "completed"

    def test_shell_cd_with_pytest(self, ctx):
        """cd /path && pytest should work (cd stripped, pytest runs in project root)."""
        tool = make_shell_tool(ctx)
        # pytest with no tests returns exit_code 5 (no tests collected) not failure
        result = json.loads(tool.invoke({"command": "cd /home/user/AISE && python -m pytest --co -q 2>&1 | head -5"}))
        assert result["status"] == "completed"


# -- Completion ------------------------------------------------------------


class TestEventDedup:
    """Regression guards for the run-detail A2A task log cleanliness.

    Source symptom: ``run_3d87cefb4c`` page showed 14+ duplicate
    ``stage_update`` rows for one phase and 20+ identical ``todos_update``
    rows for one taskId, making the timeline unreadable.
    """

    def test_consecutive_identical_stage_updates_deduped(self, ctx):
        ctx.emit({"type": "stage_update", "stage": "implementation", "status": "started"})
        ctx.emit({"type": "stage_update", "stage": "implementation", "status": "started"})
        ctx.emit({"type": "stage_update", "stage": "implementation", "status": "started"})
        stage_events = [e for e in ctx.event_log if e.get("type") == "stage_update"]
        assert len(stage_events) == 1

    def test_stage_update_re_emits_on_change(self, ctx):
        ctx.emit({"type": "stage_update", "stage": "implementation", "status": "started"})
        ctx.emit({"type": "stage_update", "stage": "implementation", "status": "started"})
        ctx.emit({"type": "stage_update", "stage": "testing", "status": "started"})
        ctx.emit({"type": "stage_update", "stage": "testing", "status": "started"})
        stages = [e["stage"] for e in ctx.event_log if e.get("type") == "stage_update"]
        assert stages == ["implementation", "testing"]

    def test_consecutive_identical_todos_update_deduped(self, ctx):
        todos = [{"content": "A", "status": "in_progress"}, {"content": "B", "status": "pending"}]
        for _ in range(20):
            ctx.emit({"type": "todos_update", "taskId": "tA", "todos": todos})
        todo_events = [e for e in ctx.event_log if e.get("type") == "todos_update"]
        assert len(todo_events) == 1

    def test_todos_update_re_emits_when_list_changes(self, ctx):
        t1 = [{"content": "A", "status": "in_progress"}]
        t2 = [{"content": "A", "status": "completed"}]
        ctx.emit({"type": "todos_update", "taskId": "tA", "todos": t1})
        ctx.emit({"type": "todos_update", "taskId": "tA", "todos": t1})
        ctx.emit({"type": "todos_update", "taskId": "tA", "todos": t2})
        ctx.emit({"type": "todos_update", "taskId": "tA", "todos": t2})
        events = [e for e in ctx.event_log if e.get("type") == "todos_update"]
        assert len(events) == 2
        assert events[0]["todos"][0]["status"] == "in_progress"
        assert events[1]["todos"][0]["status"] == "completed"

    def test_todos_dedup_is_per_task_id(self, ctx):
        todos = [{"content": "A", "status": "pending"}]
        ctx.emit({"type": "todos_update", "taskId": "tA", "todos": todos})
        ctx.emit({"type": "todos_update", "taskId": "tB", "todos": todos})
        events = [e for e in ctx.event_log if e.get("type") == "todos_update"]
        assert len(events) == 2


class TestCompletionTool:
    def test_mark_complete_sets_state(self, ctx):
        tool = make_completion_tool(ctx)
        json.loads(tool.invoke({"report": "All done. Delivered."}))
        assert ctx.workflow_state.is_complete
        assert ctx.workflow_state.final_report == "All done. Delivered."

    def test_mark_complete_emits_event(self, ctx):
        tool = make_completion_tool(ctx)
        tool.invoke({"report": "summary"})
        types = [e["type"] for e in ctx.event_log]
        assert "workflow_complete" in types

    def test_mark_complete_second_call_refused(self, ctx):
        """Regression guard for the double-delivery_report pathology.

        Observed on project_3-snake (2026-04-18): PM called
        ``mark_complete`` twice in a row, the second invocation
        overwriting a 1478-char report with an 852-char one. Once a
        workflow is complete, the tool must refuse further calls and
        keep the first report intact.
        """
        tool = make_completion_tool(ctx)
        tool.invoke({"report": "original report, 1478 chars worth of text"})
        first_len = len(ctx.workflow_state.final_report)
        result = json.loads(tool.invoke({"report": "shorter overwrite"}))
        assert result["status"] == "refused"
        assert ctx.workflow_state.final_report == "original report, 1478 chars worth of text"
        assert len(ctx.workflow_state.final_report) == first_len
        # Only ONE workflow_complete event should have been emitted.
        completes = [e for e in ctx.event_log if e.get("type") == "workflow_complete"]
        assert len(completes) == 1


class TestDispatchTaskCompletionGuard:
    """Once ``mark_complete`` has fired, further dispatches must be refused.

    Regression guard for the pathology observed on project_3-snake
    (2026-04-18): PM dispatched ``delivery_report`` a second time AFTER
    calling ``mark_complete``, which then triggered a second
    ``mark_complete`` that overwrote the first report.
    """

    def test_dispatch_refused_after_mark_complete(self, ctx):
        tools = make_dispatch_tools(ctx)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        ctx.workflow_state.is_complete = True
        result = json.loads(dispatch.invoke({"agent_name": "developer", "task_description": "x"}))
        assert result["status"] == "refused"
        assert "already marked complete" in result["error"]

    def test_dispatch_refused_emits_no_task_request(self, ctx):
        tools = make_dispatch_tools(ctx)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        ctx.workflow_state.is_complete = True
        dispatch.invoke({"agent_name": "developer", "task_description": "x"})
        # A refused dispatch must not pollute the event log with a
        # task_request (that would make the UI think work was started).
        assert not any(e.get("type") == "task_request" for e in ctx.event_log)

    def test_normal_dispatch_before_complete_still_works(self, ctx):
        tools = make_dispatch_tools(ctx)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        result = json.loads(dispatch.invoke({"agent_name": "developer", "task_description": "x"}))
        assert result["status"] == "completed"


class TestDispatchTaskRetryWithContext:
    """A dispatch that returns empty or misses its declared artifacts
    must retry once with a context-augmented prompt that quotes the
    previous response. No agent-, tool-, or file-specific wording.
    """

    def test_retry_on_empty_response(self, tmp_path, fake_manager):
        from aise.runtime.tool_primitives import (
            ToolContext,
            WorkflowState,
            make_dispatch_tools,
        )

        # Fake runtime that returns empty on first call, real content on second.
        rt = fake_manager.runtimes["developer"]
        rt.handle_message.side_effect = ["", "done"]
        ctx_ = ToolContext(
            manager=fake_manager,
            project_root=tmp_path,
            config=RuntimeConfig(),
            workflow_state=WorkflowState(),
        )
        tools = make_dispatch_tools(ctx_)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        result = json.loads(dispatch.invoke({"agent_name": "developer", "task_description": "build X"}))
        assert result["status"] == "completed"
        assert result["payload"]["output_preview"] == "done"
        assert result["payload"]["retries"] == 1
        assert rt.handle_message.call_count == 2
        # Second call must have been the retry prompt, not the raw task.
        second_prompt = rt.handle_message.call_args_list[1].args[0]
        assert "[Retry context]" in second_prompt
        assert "Original task:\nbuild X" in second_prompt
        assert "(empty)" in second_prompt  # previous was empty

    def test_no_retry_when_response_is_non_empty_and_no_artifacts_required(self, tmp_path, fake_manager):
        from aise.runtime.tool_primitives import (
            ToolContext,
            WorkflowState,
            make_dispatch_tools,
        )

        rt = fake_manager.runtimes["developer"]
        rt.handle_message.return_value = "first-try success"
        rt.handle_message.side_effect = None
        ctx_ = ToolContext(
            manager=fake_manager,
            project_root=tmp_path,
            config=RuntimeConfig(),
            workflow_state=WorkflowState(),
        )
        tools = make_dispatch_tools(ctx_)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        result = json.loads(dispatch.invoke({"agent_name": "developer", "task_description": "task"}))
        assert result["payload"]["retries"] == 0
        assert rt.handle_message.call_count == 1

    def test_retry_on_missing_expected_artifact(self, tmp_path, fake_manager):
        """If ``expected_artifacts`` includes a path that never appears,
        or that appears but is trivially small, the dispatch retries
        once with context."""
        from aise.runtime.tool_primitives import (
            ToolContext,
            WorkflowState,
            make_dispatch_tools,
        )

        rt = fake_manager.runtimes["developer"]
        # Both attempts return non-empty text but the artifact is
        # never written — the retry fires purely on artifact absence.
        rt.handle_message.side_effect = ["first output", "second output"]
        ctx_ = ToolContext(
            manager=fake_manager,
            project_root=tmp_path,
            config=RuntimeConfig(),
            workflow_state=WorkflowState(),
        )
        tools = make_dispatch_tools(ctx_)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        result = json.loads(
            dispatch.invoke(
                {
                    "agent_name": "developer",
                    "task_description": "write it",
                    "expected_artifacts": ["docs/expected.md"],
                }
            )
        )
        assert result["payload"]["retries"] == 1
        assert rt.handle_message.call_count == 2
        # Previous response ("first output") must appear verbatim in the retry prompt.
        second_prompt = rt.handle_message.call_args_list[1].args[0]
        assert "first output" in second_prompt

    def test_no_retry_when_artifact_is_present_and_large_enough(self, tmp_path, fake_manager):
        from aise.runtime.tool_primitives import (
            ToolContext,
            WorkflowState,
            make_dispatch_tools,
        )

        (tmp_path / "docs").mkdir()
        # 200 bytes — well above the 64-byte minimum.
        (tmp_path / "docs" / "expected.md").write_text("x" * 200)

        rt = fake_manager.runtimes["developer"]
        rt.handle_message.side_effect = None
        rt.handle_message.return_value = "done"
        ctx_ = ToolContext(
            manager=fake_manager,
            project_root=tmp_path,
            config=RuntimeConfig(),
            workflow_state=WorkflowState(),
        )
        tools = make_dispatch_tools(ctx_)
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        result = json.loads(
            dispatch.invoke(
                {
                    "agent_name": "developer",
                    "task_description": "write it",
                    "expected_artifacts": ["docs/expected.md"],
                }
            )
        )
        assert result["payload"]["retries"] == 0
        assert rt.handle_message.call_count == 1

    def test_retry_prompt_has_no_agent_or_tool_specific_content(self, tmp_path, fake_manager):
        """The retry prompt template must be role- and tool-neutral so
        it applies uniformly to every agent. This test pins that
        contract: no agent name, no specific tool name, no filename
        should be baked into the template itself."""
        from aise.runtime.tool_primitives import _build_retry_prompt

        prompt = _build_retry_prompt(
            original_task="anything",
            previous_response="prev response text",
        )
        # Must not mention any specific agent, tool, or filename.
        banned = [
            "architect",
            "developer",
            "qa_engineer",
            "project_manager",
            "product_manager",
            "write_file",
            "edit_file",
            "execute",
            "pytest",
            "docs/",
            "src/",
            "tests/",
            "tdd",
            ".md",
            ".py",
        ]
        lowered = prompt.lower()
        for needle in banned:
            assert needle.lower() not in lowered, f"retry template leaked customized token: {needle!r}"


class TestDispatchTasksParallelForwardsExpectedArtifacts:
    def test_parallel_forwards_expected_artifacts(self, tmp_path, fake_manager):
        """``dispatch_tasks_parallel`` must forward ``expected_artifacts``
        through to each inner ``dispatch_task``, otherwise the per-task
        artifact contract is silently dropped."""
        from aise.runtime.tool_primitives import (
            ToolContext,
            WorkflowState,
            make_dispatch_tools,
        )

        rt = fake_manager.runtimes["developer"]
        rt.handle_message.side_effect = ["one", "retry-one", "two", "retry-two"]
        ctx_ = ToolContext(
            manager=fake_manager,
            project_root=tmp_path,
            config=RuntimeConfig(),
            workflow_state=WorkflowState(),
        )
        tools = make_dispatch_tools(ctx_)
        parallel = next(t for t in tools if t.name == "dispatch_tasks_parallel")
        payload = json.dumps(
            [
                {
                    "agent_name": "developer",
                    "task_description": "a",
                    "expected_artifacts": ["docs/a.md"],
                },
                {
                    "agent_name": "developer",
                    "task_description": "b",
                    "expected_artifacts": ["docs/b.md"],
                },
            ]
        )
        result = json.loads(parallel.invoke({"tasks_json": payload}))
        # Each task's artifact is missing → each must retry once.
        assert result["total"] == 2
        retries = sorted(item["payload"]["retries"] for item in result["parallel_results"])
        assert retries == [1, 1]


# -- Aggregate -------------------------------------------------------------


class TestBuildOrchestratorTools:
    def test_full_toolset(self, ctx):
        tools = build_orchestrator_tools(ctx)
        names = {t.name for t in tools}
        assert names == {
            "list_processes",
            "get_process",
            "list_agents",
            "dispatch_task",
            "dispatch_tasks_parallel",
            "execute_shell",
            "mark_complete",
        }
