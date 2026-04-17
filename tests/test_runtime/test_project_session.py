"""Tests for ProjectSession orchestration tools."""

import json
from unittest.mock import MagicMock, patch

import pytest

from aise.runtime.project_session import ProjectSession, _parse_process_header


class TestParseProcessHeader:
    def test_parse_waterfall(self):
        text = (
            "# Waterfall\n"
            "- process_id: waterfall_standard_v1\n"
            "- name: Sequential Waterfall Lifecycle\n"
            "- work_type: structured_development\n"
            "- keywords: waterfall, sequential\n"
            "- summary: A linear approach\n"
        )
        info = _parse_process_header(text)
        assert info["process_id"] == "waterfall_standard_v1"
        assert info["name"] == "Sequential Waterfall Lifecycle"
        assert info["work_type"] == "structured_development"
        assert "waterfall" in info["keywords"]


@pytest.fixture
def started_manager():
    """A RuntimeManager with agents loaded (all LLM calls mocked)."""
    from langchain_core.messages import AIMessage

    mock_agent = MagicMock()
    mock_agent.invoke.return_value = {"messages": [AIMessage(content="Done")]}
    mock_llm = MagicMock()

    with (
        patch("aise.runtime.agent_runtime.create_deep_agent", return_value=mock_agent),
        patch("aise.runtime.manager._build_llm", return_value=mock_llm),
    ):
        from aise.runtime.manager import RuntimeManager

        mgr = RuntimeManager()
        mgr.start()
        yield mgr
        mgr.stop()


@pytest.fixture
def session(started_manager):
    """A ProjectSession with the PM runtime mocked out."""
    with patch.object(ProjectSession, "_build_pm_runtime") as mock_build:
        pm_rt = MagicMock()
        pm_rt.handle_message.return_value = "Project completed successfully."
        mock_build.return_value = pm_rt
        sess = ProjectSession(started_manager)
        yield sess


class TestProjectSessionTools:
    def test_list_processes_tool(self, session):
        tools = session._make_tools()
        list_procs = next(t for t in tools if t.name == "list_processes")
        result = json.loads(list_procs.invoke({}))
        procs = result["processes"]
        assert len(procs) >= 2
        ids = [p["process_id"] for p in procs]
        assert "waterfall_standard_v1" in ids
        assert "agile_sprint_v1" in ids

    def test_get_process_tool(self, session):
        tools = session._make_tools()
        get_proc = next(t for t in tools if t.name == "get_process")
        result = get_proc.invoke({"process_file": "waterfall.process.md"})
        assert "waterfall" in result.lower()

    def test_get_process_not_found(self, session):
        tools = session._make_tools()
        get_proc = next(t for t in tools if t.name == "get_process")
        result = json.loads(get_proc.invoke({"process_file": "nonexistent.md"}))
        assert "error" in result

    def test_list_agents_tool(self, session):
        tools = session._make_tools()
        list_ag = next(t for t in tools if t.name == "list_agents")
        result = json.loads(list_ag.invoke({}))
        agents = result["agents"]
        names = [a["name"] for a in agents]
        assert "developer" in names
        assert "architect" in names
        assert "project_manager" not in names  # excludes self

    def test_dispatch_task_tool(self, session):
        tools = session._make_tools()
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        result = json.loads(
            dispatch.invoke(
                {
                    "agent_name": "developer",
                    "task_description": "Generate user model code",
                    "step_id": "impl_1",
                    "phase": "implementation",
                }
            )
        )
        assert result["type"] == "task_response"
        assert result["from"] == "developer"
        assert result["status"] == "completed"

    def test_dispatch_task_agent_not_found(self, session):
        tools = session._make_tools()
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        result = json.loads(
            dispatch.invoke(
                {
                    "agent_name": "nonexistent",
                    "task_description": "do something",
                }
            )
        )
        assert result["status"] == "failed"
        assert "not found" in result["error"]

    def test_task_log_recorded(self, session):
        tools = session._make_tools()
        dispatch = next(t for t in tools if t.name == "dispatch_task")
        dispatch.invoke(
            {
                "agent_name": "developer",
                "task_description": "test task",
            }
        )
        # stage_update (execution) + task_request + task_response
        types = [e["type"] for e in session.task_log]
        assert "stage_update" in types
        assert "task_request" in types
        assert "task_response" in types


class TestProjectSessionRun:
    def test_run_calls_pm_runtime(self, session):
        # Simulate a phased workflow. mark_complete is only honored in the
        # last phase, so we call it on the 6th invocation (the delivery phase).
        call_count = [0]
        report = (
            "Project delivery report: all phases completed successfully. "
            "Requirements analyzed, architecture designed, code implemented, tests passed."
        )

        def mock_handle(msg, **kwargs):
            call_count[0] += 1
            # On the LAST phase (delivery), call mark_complete
            if call_count[0] == 6:
                tools = session._make_tools()
                mark = next(t for t in tools if t.name == "mark_complete")
                mark.invoke({"report": report})
                return "Delivery report written."
            return "Phase done."

        session._pm_runtime.handle_message.side_effect = mock_handle

        result = session.run("Build a REST API")
        assert "delivery report" in result.lower()
        # 6 phases should have been invoked
        assert call_count[0] == 6
