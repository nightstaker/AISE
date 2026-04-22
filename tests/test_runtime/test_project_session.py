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

    def test_architect_md_requires_mermaid_diagrams(self):
        """architect.md must instruct the agent to produce Mermaid
        diagrams (inside fenced code blocks) for all design visuals,
        not ASCII art or external images. Pins the contract for every
        architecture document the agent writes."""
        from pathlib import Path as _P

        import aise

        md_path = _P(aise.__file__).resolve().parent / "agents" / "architect.md"
        body = md_path.read_text(encoding="utf-8")
        lowered = body.lower()
        assert "mermaid" in lowered
        assert "```mermaid" in body
        # Explicit bans to prevent regressions.
        assert "ascii art" in lowered
        # Behavioral diagram types must remain named so the agent picks
        # the right one for non-architecture views.
        assert any(
            kind in body
            for kind in (
                "sequenceDiagram",
                "stateDiagram",
                "erDiagram",
                "flowchart",
            )
        )

    def test_architect_md_requires_c4_for_architecture_views(self):
        """Architecture views (system context, container decomposition,
        component decomposition) must be C4 diagrams. architect.md
        lists the required C4 Mermaid types and mandates minimum
        coverage so the agent cannot drop any level."""
        from pathlib import Path as _P

        import aise

        md_path = _P(aise.__file__).resolve().parent / "agents" / "architect.md"
        body = md_path.read_text(encoding="utf-8")
        # The three minimum-required C4 levels must be named explicitly.
        for c4_type in ("C4Context", "C4Container", "C4Component"):
            assert c4_type in body, f"architect.md must name the {c4_type} Mermaid type"
        # The C4 model itself should be referenced by name so future
        # maintainers can find the relevant docs.
        assert "C4 model" in body or "C4 diagram" in body

    def test_product_manager_md_requires_mermaid_for_diagrams(self):
        """product_manager.md must instruct the PM to use Mermaid for
        any diagrams it includes in requirement or delivery documents."""
        from pathlib import Path as _P

        import aise

        md_path = _P(aise.__file__).resolve().parent / "agents" / "product_manager.md"
        body = md_path.read_text(encoding="utf-8")
        assert "mermaid" in body.lower()
        assert "```mermaid" in body

    def test_phase2_prompt_requires_mermaid_diagrams(self, session):
        """The architecture-phase prompt must tell the PM to instruct
        the architect to produce Mermaid diagrams. Without this, the
        architect.md text is necessary but not sufficient — the PM
        needs the explicit reminder in the dispatch description."""
        phases = session._build_phase_prompts("Build a thing")
        architecture = dict(phases).get("architecture", "")
        lowered = architecture.lower()
        assert "mermaid" in lowered
        # And the phase prompt should say "no ASCII art" (or an
        # equivalent) so the architect can't sidestep the requirement.
        assert "ascii art" in lowered or "no ascii" in lowered

    def test_phase2_prompt_requires_c4_architecture_diagrams(self, session):
        """The architecture-phase prompt must reinforce the C4
        requirement at dispatch time so the PM cannot drop it even if
        the architect system prompt is weakened in a future edit."""
        phases = session._build_phase_prompts("Build a thing")
        architecture = dict(phases).get("architecture", "")
        for c4_type in ("C4Context", "C4Container", "C4Component"):
            assert c4_type in architecture, f"phase-2 prompt must name the {c4_type} requirement"

    # --- New skills: code_inspection + mermaid --------------------------

    def test_developer_md_declares_code_inspection_skill(self):
        """developer.md must declare ``code_inspection`` in its
        ``## Skills`` block so the skill body gets inlined by the
        per-agent filter."""
        from pathlib import Path as _P

        import aise

        md_path = _P(aise.__file__).resolve().parent / "agents" / "developer.md"
        body = md_path.read_text(encoding="utf-8")
        assert "code_inspection" in body
        # The developer's own system prompt must reference the skill
        # so the agent runs it, not just declare it in the skill list.
        assert "analyzer" in body.lower()

    def test_architect_md_declares_mermaid_skill(self):
        """architect.md must declare ``mermaid`` so the validation
        skill body is inlined into its system prompt."""
        from pathlib import Path as _P

        import aise

        md_path = _P(aise.__file__).resolve().parent / "agents" / "architect.md"
        body = md_path.read_text(encoding="utf-8")
        assert "mermaid" in body.lower()
        # Body should reference the skill in the Skills bullet AND the
        # MANDATORY validation note in the system prompt.
        assert "Diagram Validation" in body or "mermaid skill" in body.lower()

    def test_product_manager_md_declares_mermaid_skill(self):
        from pathlib import Path as _P

        import aise

        md_path = _P(aise.__file__).resolve().parent / "agents" / "product_manager.md"
        body = md_path.read_text(encoding="utf-8")
        assert "mermaid" in body.lower()
        assert "Diagram Validation" in body or "mermaid skill" in body.lower()

    def test_product_manager_md_requires_use_case_diagram_per_requirement(self):
        """PM.md must instruct the agent to draw a Mermaid use case
        diagram for every requirement. Without this, the requirement
        document is prose-only and loses the visual actor→use-case
        mapping."""
        from pathlib import Path as _P

        import aise

        md_path = _P(aise.__file__).resolve().parent / "agents" / "product_manager.md"
        body = md_path.read_text(encoding="utf-8")
        lowered = body.lower()
        assert "use case diagram" in lowered
        # The actor + use-case shape conventions must be spelled out
        # so the agent doesn't invent its own incompatible notation.
        assert "actor_" in body
        assert "uc_" in body

    def test_phase1_prompt_requires_use_case_diagram(self, session):
        """The requirements-phase prompt must carry the use-case-diagram
        requirement through to the architect-agnostic dispatch, so even
        a weakened PM.md still receives the instruction."""
        phases = session._build_phase_prompts("Build a thing")
        requirements = dict(phases).get("requirements", "")
        lowered = requirements.lower()
        assert "use case diagram" in lowered
        # Actor + use-case shape identifiers must be in the prompt so
        # the PM writes correct Mermaid.
        assert "actor_" in requirements
        assert "uc_" in requirements

    def test_phase1_prompt_requires_mermaid_validation(self, session):
        """Phase 1 prompt must instruct the PM to validate Mermaid
        blocks after writing the requirement document."""
        phases = session._build_phase_prompts("Build a thing")
        requirements = dict(phases).get("requirements", "")
        assert "mermaid" in requirements.lower()

    def test_phase2_prompt_requires_mermaid_validation(self, session):
        """Phase 2 prompt must instruct the architect to validate
        Mermaid blocks after writing the architecture document."""
        phases = session._build_phase_prompts("Build a thing")
        architecture = dict(phases).get("architecture", "")
        assert "mermaid" in architecture.lower()

    def test_phase3_prompt_requires_code_inspection(self, session):
        """Phase 3 prompt must instruct the developer to run the
        static analyzer via the ``code_inspection`` skill after tests
        pass."""
        phases = session._build_phase_prompts("Build a thing")
        implementation = dict(phases).get("implementation", "")
        assert "code_inspection" in implementation
        assert "ruff" in implementation or "static analyzer" in implementation.lower()

    def test_code_inspection_skill_file_exists(self):
        """The ``code_inspection`` skill body must live at the
        expected path so the runtime's per-agent filter can inline it
        into the developer prompt."""
        from pathlib import Path as _P

        import aise

        skill = _P(aise.__file__).resolve().parent / "agents" / "_runtime_skills" / "code_inspection" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8")
        # Language → toolset mapping table must cover the main
        # languages the developer works in.
        for tool in ("ruff", "mypy", "eslint", "tsc", "go vet", "cargo clippy"):
            assert tool in body, f"code_inspection skill must list {tool}"

    def test_mermaid_skill_file_exists(self):
        """The ``mermaid`` skill body must live at the expected path."""
        from pathlib import Path as _P

        import aise

        skill = _P(aise.__file__).resolve().parent / "agents" / "_runtime_skills" / "mermaid" / "SKILL.md"
        assert skill.is_file()
        body = skill.read_text(encoding="utf-8")
        # The skill must name the validation tool and include a
        # fallback self-review checklist for when mmdc is absent.
        assert "mmdc" in body
        assert "self-review" in body.lower() or "manual" in body.lower()


class TestProjectSessionPhaseEvents:
    def test_phase_plan_emitted_once(self, session):
        """The session emits a single ``phase_plan`` before any phase runs."""
        session._pm_runtime.handle_message.return_value = ""
        session.run("Build something")
        plans = [e for e in session.task_log if e.get("type") == "phase_plan"]
        assert len(plans) == 1
        plan = plans[0]
        assert plan["total"] > 0
        assert isinstance(plan["phases"], list)
        assert len(plan["phases"]) == plan["total"]
        assert plan["start_phase_idx"] == 0

    def test_phase_start_complete_pair_per_phase(self, session):
        """Every phase that runs emits both a start and a complete event."""
        session._pm_runtime.handle_message.return_value = ""
        session.run("Build something")
        starts = [e for e in session.task_log if e.get("type") == "phase_start"]
        completes = [e for e in session.task_log if e.get("type") == "phase_complete"]
        assert len(starts) == len(completes)
        # idx sequence is monotonic.
        assert [e["phase_idx"] for e in starts] == sorted(e["phase_idx"] for e in starts)

    def test_start_phase_idx_skips_earlier_phases(self, started_manager):
        """Resuming at phase N skips phases 0..N-1 entirely."""
        with patch.object(ProjectSession, "_build_pm_runtime") as mock_build:
            pm_rt = MagicMock()
            pm_rt.handle_message.return_value = ""
            mock_build.return_value = pm_rt
            sess = ProjectSession(started_manager, start_phase_idx=2)
            sess.run("Resume me")
        starts = [e for e in sess.task_log if e.get("type") == "phase_start"]
        # All emitted phase_start events should have idx >= 2.
        assert starts, "expected at least one phase_start after resume"
        assert all(e["phase_idx"] >= 2 for e in starts)
        # A phase_resume event should also be emitted.
        resumes = [e for e in sess.task_log if e.get("type") == "phase_resume"]
        assert len(resumes) == 1
        assert resumes[0]["phase_idx"] == 2

    def test_start_phase_idx_zero_emits_no_resume(self, session):
        """Normal runs don't emit phase_resume — only retries do."""
        session._pm_runtime.handle_message.return_value = ""
        session.run("Fresh run")
        resumes = [e for e in session.task_log if e.get("type") == "phase_resume"]
        assert resumes == []


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
