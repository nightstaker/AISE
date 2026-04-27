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

    def test_dispatch_prepends_original_requirement_to_worker_prompt(self, session):
        """When the session has an original requirement, dispatch_task
        must prefix it onto the worker prompt so agents can mirror the
        user's natural language in docs/*.md. The emitted task_request
        event keeps the raw task_description unmodified so the log is
        not polluted by N copies of the requirement block.
        """
        session._ctx.original_requirement = "创建一个贪吃蛇游戏，需要方向键控制"
        tools = session._make_tools()
        dispatch = next(t for t in tools if t.name == "dispatch_task")

        # Capture what the worker's handle_message actually receives.
        captured = {}
        target = session._manager.get_runtime("developer")
        original_handle = target.handle_message

        def _capture(prompt, **kw):
            captured["prompt"] = prompt
            return original_handle(prompt, **kw)

        target.handle_message = _capture

        dispatch.invoke(
            {
                "agent_name": "developer",
                "task_description": "Implement module X",
            }
        )

        worker_prompt = captured["prompt"]
        assert "=== ORIGINAL USER REQUIREMENT" in worker_prompt
        assert "创建一个贪吃蛇游戏" in worker_prompt
        assert "=== END ORIGINAL REQUIREMENT ===" in worker_prompt
        assert "Implement module X" in worker_prompt

        # The emitted task_request payload keeps the raw description,
        # unpolluted by the prefix.
        requests = [e for e in session.task_log if e["type"] == "task_request"]
        assert requests, "expected at least one task_request event"
        assert requests[-1]["payload"]["task"] == "Implement module X"

    def test_dispatch_emits_token_usage_events(self, session):
        """dispatch_task must wire an ``on_token_usage`` callback into
        the worker's ``handle_message`` and surface each round-trip as
        a ``token_usage`` event on the orchestrator's event log so the
        web layer can aggregate per-WorkflowRun totals without parsing
        trace files at runtime.
        """
        tools = session._make_tools()
        dispatch = next(t for t in tools if t.name == "dispatch_task")

        target = session._manager.get_runtime("developer")
        original_handle = target.handle_message

        def _emit_two_calls(prompt, **kw):
            cb = kw.get("on_token_usage")
            if cb is not None:
                cb({"input_tokens": 10, "output_tokens": 4, "total_tokens": 14})
                cb({"input_tokens": 6, "output_tokens": 2, "total_tokens": 8})
            return original_handle(prompt, **kw)

        target.handle_message = _emit_two_calls

        dispatch.invoke(
            {
                "agent_name": "developer",
                "task_description": "produce something",
            }
        )

        token_events = [e for e in session.task_log if e["type"] == "token_usage"]
        assert len(token_events) == 2
        assert token_events[0]["agent"] == "developer"
        assert token_events[0]["input_tokens"] == 10
        assert token_events[0]["output_tokens"] == 4
        assert token_events[0]["total_tokens"] == 14
        # Second call gets summed by upstream consumers (web layer).
        assert token_events[1]["input_tokens"] == 6

    def test_dispatch_without_original_requirement_is_unchanged(self, session):
        """Default (empty) requirement means no prefix — preserves the
        existing contract for unit tests and any caller that invokes
        the primitive directly without setting the session requirement.
        """
        # Ensure nothing set it.
        session._ctx.original_requirement = ""
        tools = session._make_tools()
        dispatch = next(t for t in tools if t.name == "dispatch_task")

        captured = {}
        target = session._manager.get_runtime("developer")
        original_handle = target.handle_message

        def _capture(prompt, **kw):
            captured["prompt"] = prompt
            return original_handle(prompt, **kw)

        target.handle_message = _capture

        dispatch.invoke(
            {
                "agent_name": "developer",
                "task_description": "bare task",
            }
        )
        assert captured["prompt"] == "bare task"


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
        """Phase-6 reads test results from docs/qa_report.json (the QA
        engineer's structured output) instead of re-running pytest
        itself — running pytest twice introduces flakiness that hides
        QA-flagged failures. Source LOC is still gathered live via
        ``find`` + ``wc -l`` because QA does not produce that.
        """
        phases = session._build_phase_prompts("Build a thing")
        delivery = dict(phases).get("delivery", "")
        # Source-LOC commands: still language-agnostic via find + wc -l.
        assert "wc -l" in delivery
        assert "find src" in delivery
        # Test results: read structured QA report, NOT re-run pytest.
        assert "qa_report.json" in delivery, (
            "Phase 6 must read docs/qa_report.json instead of re-running "
            "pytest (avoids flakiness covering up QA findings)"
        )
        # Anti-regression: the prompt must NOT instruct the orchestrator
        # to run the full test suite or coverage tool. That belongs to
        # the QA engineer in Phase 5.
        bad_substrings = (
            "python -m pytest tests/ --cov",
            "python -m pytest tests/ -q",
            "go test ./... 2>&1",
            "cargo test 2>&1",
        )
        for bad in bad_substrings:
            assert bad not in delivery, (
                f"Phase 6 prompt re-runs the test suite ({bad!r}) — that "
                f"causes flaky overrides of QA findings. Read qa_report.json "
                f"instead."
            )

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
        # The anti-fabrication / read-qa-verbatim clause may be
        # word-wrapped across newlines, so collapse whitespace before
        # matching to make the assertion robust to template formatting.
        delivery = " ".join(dict(phases).get("delivery", "").split()).lower()
        # Either the explicit anti-fabrication clause, or the new
        # design's stronger "read qa_report verbatim" instruction.
        guards = (
            "do not invent numbers",
            "do not fabricate",
            "do not guess",
            "cite verbatim",
            "verbatim",
        )
        assert any(g in delivery for g in guards), (
            "Phase 6 prompt must include an anti-fabrication clause OR a "
            "read-qa-verbatim instruction so the PM cannot rewrite QA's "
            "structured findings"
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
        """Phase 3's code-inspection requirement is now embedded in
        the per-subsystem task description that ``dispatch_subsystems``
        renders deterministically (see
        ``tool_primitives._build_subsystem_task_description``), not in
        the orchestrator prompt itself. The orchestrator prompt only
        has to tell the orchestrator to call ``dispatch_subsystems``
        once; the rendered worker task is what carries the static-
        analyzer instruction.

        This test asserts the per-subsystem renderer references the
        ``static_check`` toolchain row so every developer dispatch
        gets the static-analysis step.
        """
        from aise.runtime.tool_primitives import (
            _LANGUAGE_TOOLCHAIN,
            _build_subsystem_task_description,
        )

        # Each language row must contain a static_check command — that
        # is the in-task instruction shown to the developer.
        for lang, row in _LANGUAGE_TOOLCHAIN.items():
            assert "static_check" in row, f"language {lang!r} toolchain missing static_check command"
        # Sanity: the rendered task description for one Python
        # subsystem must mention the analyzer phase explicitly.
        rendered = _build_subsystem_task_description(
            subsystem={
                "name": "core",
                "src_dir": "src/core/",
                "responsibilities": "x",
                "components": [{"name": "engine", "file": "src/core/engine.py", "responsibility": "y"}],
            },
            contract={"language": "python", "test_runner": "pytest", "static_analyzer": ["ruff", "mypy"]},
            phase="implementation",
        )
        assert "INSPECT" in rendered
        assert "static analyzer" in rendered.lower() or "ruff" in rendered

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


class TestDispatchCapDynamicFloor:
    """A1: ``ProjectSession`` raises ``max_dispatches`` to a per-run
    floor derived from the architect's stack contract so the cap
    auto-scales with the actual architecture.

    Regression for project_7-tower run_3f53c0dcc5: 30 dispatches was
    fewer than 5 subsystems + 32 components and the gameplay
    subsystem got truncated. The floor must be Σ(1 + components) +
    DISPATCH_FLOOR_BUFFER.
    """

    def _seed_contract(self, project_root, n_subsystems: int, comps_per: int) -> None:
        import json as _json

        docs = project_root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        subsystems = []
        for i in range(n_subsystems):
            subsystems.append(
                {
                    "name": f"sub{i}",
                    "src_dir": f"src/sub{i}/",
                    "components": [{"name": f"c{j}", "file": f"src/sub{i}/c{j}.py"} for j in range(comps_per)],
                }
            )
        (docs / "stack_contract.json").write_text(
            _json.dumps({"language": "python", "subsystems": subsystems}),
            encoding="utf-8",
        )

    def test_floor_raises_cap_when_contract_exceeds_default(self, started_manager, tmp_path):
        from unittest.mock import patch as _patch

        from aise.runtime.runtime_config import DISPATCH_FLOOR_BUFFER, RuntimeConfig

        # Force the default low so the contract clearly forces a raise
        # regardless of what the global default is set to.
        rc = RuntimeConfig()
        rc.safety_limits.max_dispatches = 10

        self._seed_contract(tmp_path, n_subsystems=5, comps_per=10)

        with _patch.object(ProjectSession, "_build_pm_runtime") as mock_build:
            pm_rt = MagicMock()
            pm_rt.handle_message.return_value = "ok"
            mock_build.return_value = pm_rt
            sess = ProjectSession(
                started_manager,
                project_root=tmp_path,
                runtime_config=rc,
            )
            sess._apply_dispatch_floor(reason="unit_test")

        # 5 subsystems × (1 skeleton + 10 components) = 55, plus buffer.
        expected_floor = 5 * (1 + 10) + DISPATCH_FLOOR_BUFFER
        assert sess._config.safety_limits.max_dispatches == expected_floor

        events = [e for e in sess.task_log if e.get("type") == "dispatch_cap_raised"]
        assert events, "expected a dispatch_cap_raised event"
        assert events[-1]["to"] == expected_floor
        assert events[-1]["from"] == 10

    def test_floor_does_not_lower_an_already_higher_cap(self, started_manager, tmp_path):
        from unittest.mock import patch as _patch

        from aise.runtime.runtime_config import RuntimeConfig

        rc = RuntimeConfig()
        rc.safety_limits.max_dispatches = 1024  # explicit project override

        self._seed_contract(tmp_path, n_subsystems=2, comps_per=2)

        with _patch.object(ProjectSession, "_build_pm_runtime") as mock_build:
            pm_rt = MagicMock()
            pm_rt.handle_message.return_value = "ok"
            mock_build.return_value = pm_rt
            sess = ProjectSession(
                started_manager,
                project_root=tmp_path,
                runtime_config=rc,
            )
            sess._apply_dispatch_floor(reason="unit_test")

        # Floor here is 2*(1+2)+16 = 22 — far below 1024. The override
        # must NOT be lowered.
        assert sess._config.safety_limits.max_dispatches == 1024
        # And no raise event fires when there's nothing to raise.
        events = [e for e in sess.task_log if e.get("type") == "dispatch_cap_raised"]
        assert events == []

    def test_floor_noop_when_contract_missing(self, started_manager, tmp_path):
        """No contract on disk → leave the cap untouched. Architect
        hasn't run yet; the post-phase hook will re-apply once it does.
        """
        from unittest.mock import patch as _patch

        from aise.runtime.runtime_config import RuntimeConfig

        rc = RuntimeConfig()
        original_cap = rc.safety_limits.max_dispatches

        with _patch.object(ProjectSession, "_build_pm_runtime") as mock_build:
            pm_rt = MagicMock()
            pm_rt.handle_message.return_value = "ok"
            mock_build.return_value = pm_rt
            sess = ProjectSession(
                started_manager,
                project_root=tmp_path,
                runtime_config=rc,
            )
            sess._apply_dispatch_floor(reason="unit_test")

        assert sess._config.safety_limits.max_dispatches == original_cap


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
