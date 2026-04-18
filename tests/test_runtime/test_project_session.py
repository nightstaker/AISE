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


class TestPhase4EntryPointContract:
    """The Phase 4 prompt must instruct the developer to produce an
    entry-point file that is *runnable by its language's convention*,
    not just an importable class. The orchestrator then extracts the
    ``RUN:`` line from the developer's response and smoke-tests it.

    Regression guard: the old Phase 4 prompt said "Write src/main.py"
    with the TDD-first instruction, which led developers (following TDD
    literally) to write a ``GameApp`` class with no ``if __name__ ==
    "__main__":`` block — the file was importable but ``python
    src/main.py`` did nothing.
    """

    def test_phase4_prompt_is_language_agnostic(self, session):
        # Exercise the real phase builder via session (same helper used
        # by session.run()).
        phases = session._build_phase_prompts("Build a thing")
        main_entry = dict(phases).get("main_entry", "")
        # Prompt names multiple languages — not Python-only.
        assert "src/main.py" in main_entry
        assert "src/index.js" in main_entry or "node" in main_entry.lower()
        assert "go run" in main_entry.lower() or "main.go" in main_entry
        assert "cargo run" in main_entry.lower() or "main.rs" in main_entry

    def test_phase4_prompt_requires_run_line(self, session):
        phases = session._build_phase_prompts("Build a thing")
        main_entry = dict(phases).get("main_entry", "")
        # RUN: contract is described.
        assert "RUN:" in main_entry
        assert "execute_shell" in main_entry or "execute(" in main_entry
        # Smoke-test semantics: timeout is success.
        assert "timeout" in main_entry.lower()
        assert "ImportError" in main_entry or "startup" in main_entry.lower()

    def test_phase4_prompt_has_retry_loop(self, session):
        phases = session._build_phase_prompts("Build a thing")
        main_entry = dict(phases).get("main_entry", "")
        # Retry up to 3 attempts on failure — matches Phase 3's pattern.
        assert "3 attempts" in main_entry or "3 attempts" in main_entry.lower()

    def test_developer_md_describes_run_contract(self):
        """developer.md must teach the developer agent how to produce the
        RUN: line the orchestrator expects."""
        from pathlib import Path as _P

        import aise

        md_path = _P(aise.__file__).resolve().parent / "agents" / "developer.md"
        body = md_path.read_text(encoding="utf-8")
        assert "Entry Point Files" in body
        assert "RUN:" in body
        # Language-agnostic — examples cover at least Python + one other.
        assert "python src/main.py" in body
        assert "node src/index.js" in body or "cargo run" in body or "go run" in body
        # The timeout-is-success semantics must be documented.
        assert "timeout" in body.lower()


class TestPhase6DeliveryReport:
    """Phase 6 must produce a real delivery report with measured metrics,
    not the old three-bullet handwave ("modules implemented, test results,
    known issues"). The prompt drives the PM through concrete data
    gathering via execute_shell + dispatch to product_manager.
    """

    def test_phase6_prompt_collects_implementation_metrics(self, session):
        phases = session._build_phase_prompts("Build a thing")
        delivery = dict(phases).get("delivery", "")
        # Runs shell commands to count files / LOC / tests / coverage.
        assert "execute_shell" in delivery or "execute(" in delivery
        # Source counting via find + wc -l (language-agnostic multi-ext).
        assert "wc -l" in delivery
        assert "find src" in delivery
        # Test counting via pytest --collect-only.
        assert "--collect-only" in delivery or "collect-only" in delivery
        # Coverage attempted but optional — must mention --cov.
        assert "--cov" in delivery

    def test_phase6_prompt_dispatches_product_manager(self, session):
        phases = session._build_phase_prompts("Build a thing")
        delivery = dict(phases).get("delivery", "")
        # PM agent dispatches the write step to product_manager.
        assert "product_manager" in delivery
        # Explicit file name.
        assert "docs/delivery_report.md" in delivery
        # Required sections appear in the task description.
        for section in (
            "Executive Summary",
            "Design",
            "Implementation Metrics",
            "Testing Metrics",
            "Known Issues",
        ):
            assert section in delivery, f"delivery prompt missing '{section}' section"

    def test_phase6_prompt_forbids_fabricated_numbers(self, session):
        phases = session._build_phase_prompts("Build a thing")
        delivery = dict(phases).get("delivery", "")
        # Explicit anti-fabrication clause — PM must cite real outputs.
        assert (
            "do not invent numbers" in delivery.lower()
            or "do not fabricate" in delivery.lower()
            or "do not guess" in delivery.lower()
        )

    def test_phase6_prompt_ends_with_mark_complete(self, session):
        phases = session._build_phase_prompts("Build a thing")
        delivery = dict(phases).get("delivery", "")
        # Last step is mark_complete; any earlier phase prompt says "Do NOT
        # call mark_complete", so this is the one phase where it fires.
        assert "mark_complete" in delivery
        # And the report in docs/delivery_report.md is referenced.
        assert "docs/delivery_report.md" in delivery

    def test_product_manager_md_acknowledges_delivery_report(self):
        """product_manager.md must explicitly accept delivery-report
        tasks and warn against fabricating numbers. Otherwise the
        agent might refuse the dispatch as out of scope."""
        from pathlib import Path as _P

        import aise

        md_path = _P(aise.__file__).resolve().parent / "agents" / "product_manager.md"
        body = md_path.read_text(encoding="utf-8")
        assert "delivery_report.md" in body
        # Anti-fabrication warning so PM cites numbers verbatim.
        assert "verbatim" in body.lower() or "do not invent" in body.lower()


class TestPostPhaseArtifactVerification:
    """Regression guard for the project_3-snake Phase 1 bug (2026-04-18):
    the product_manager dispatch silently returned without writing
    docs/requirement.md (weak-LLM empty-AIMessage pathology). The
    orchestrator happily moved on because it only checked the
    dispatch's ``status`` field, not the actual artifact.

    Each artifact-producing phase must now verify its expected file
    exists and re-dispatch ONCE if it's missing or too small. Phases
    covered:

    - Phase 1 → docs/requirement.md
    - Phase 2 → docs/architecture.md
    - Phase 5 → tests/test_integration.py
    - Phase 6 → docs/delivery_report.md

    Phase 3 has no single canonical artifact (one per module), and its
    own "pytest must pass" retry already implicitly verifies files.
    Phase 4 has its own ``RUN:``-line smoke test.
    """

    def _prompt(self, session, name):
        return dict(session._build_phase_prompts("Build a thing")).get(name, "")

    def test_phase1_verifies_requirement_md(self, session):
        prompt = self._prompt(session, "requirements")
        assert "docs/requirement.md" in prompt
        assert "test -f docs/requirement.md" in prompt
        assert "re-dispatch" in prompt.lower()
        assert "2 attempts" in prompt

    def test_phase2_verifies_architecture_md(self, session):
        prompt = self._prompt(session, "architecture")
        assert "docs/architecture.md" in prompt
        assert "test -f docs/architecture.md" in prompt
        assert "re-dispatch" in prompt.lower()
        assert "2 attempts" in prompt

    def test_phase5_verifies_test_integration_py(self, session):
        prompt = self._prompt(session, "qa_testing")
        assert "tests/test_integration.py" in prompt
        assert "test -f tests/test_integration.py" in prompt
        assert "re-dispatch" in prompt.lower()
        assert "2 attempts" in prompt

    def test_phase6_verifies_delivery_report_md(self, session):
        prompt = self._prompt(session, "delivery")
        assert "docs/delivery_report.md" in prompt
        assert "test -f docs/delivery_report.md" in prompt
        assert "re-dispatch" in prompt.lower()
        # Phase 6 is still the one that calls mark_complete.
        assert "mark_complete" in prompt


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
