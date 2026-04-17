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
