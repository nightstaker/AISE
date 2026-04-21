"""Regression guards for the incremental-requirement mode (Task 2).

Covers three layers:

1. **Mode detection** — ``WebProjectService.run_requirement`` picks
   ``initial`` vs ``incremental`` based on prior-run state.
2. **Session wiring** — ``ProjectSession(mode=...)`` is honored and
   branches ``_build_phase_prompts`` to the incremental variant.
3. **Prompt contract** — the incremental phase prompts carry the
   "read existing first, append / edit in place" instructions for
   every phase, and the QA phase still runs the FULL test suite.
4. **UI surface** — ``app.js`` renders an ``Incremental`` badge when
   ``run.mode === "incremental"``, with the required i18n keys
   present in both zh and en translation tables.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import aise
from aise.runtime.project_session import ProjectSession
from aise.web.app import WorkflowRun

STATIC_DIR = Path(aise.__file__).resolve().parent / "web" / "static"
APP_JS = STATIC_DIR / "app.js"
MAIN_CSS = STATIC_DIR / "main.css"


# ---------------------------------------------------------------------------
# Mode detection
# ---------------------------------------------------------------------------


class _FakeProject:
    def __init__(self, project_id: str, project_root: Path) -> None:
        self.project_id = project_id
        self.project_name = "test"
        self.project_root = project_root
        self.status = type("S", (), {"value": "active"})()
        self.created_at = None
        self.updated_at = None

    def get_info(self) -> dict:  # pragma: no cover — not exercised
        return {}


@pytest.fixture
def web_service(tmp_path):
    """Build a ``WebProjectService`` with all IO + runtime stubbed out."""
    from aise.web.app import WebProjectService

    with (
        patch("aise.web.app.configure_logging"),
        patch("aise.web.app.configure_module_file_logger"),
        patch("aise.web.app.ProjectManager") as PM,
        patch("aise.runtime.manager.RuntimeManager") as RM,
    ):
        pm_instance = MagicMock()
        pm_instance._global_config.logging.log_dir = str(tmp_path / "logs")
        pm_instance._global_config.logging.json_format = False
        pm_instance._global_config.logging.rotate_daily = True
        pm_instance._projects_root = tmp_path / "projects"
        pm_instance._projects_root.mkdir(parents=True, exist_ok=True)
        pm_instance.get_project.return_value = _FakeProject("proj-1", tmp_path / "projects" / "proj-1")
        pm_instance.list_projects.return_value = []
        pm_instance.get_all_projects_info.return_value = []
        PM.return_value = pm_instance
        rm_instance = MagicMock()
        RM.return_value = rm_instance
        service = WebProjectService()
        # Don't spawn background threads during tests.
        service._execute_run = MagicMock()  # type: ignore[assignment]
        yield service


class TestIncrementalDetection:
    def test_first_run_is_initial(self, web_service) -> None:
        run_id = web_service.run_requirement("proj-1", "build a snake game")
        runs = web_service._runs_by_project["proj-1"]
        assert len(runs) == 1
        assert runs[0].run_id == run_id
        assert runs[0].mode == "initial"

    def test_second_run_after_completed_is_incremental(self, web_service) -> None:
        web_service.run_requirement("proj-1", "build a snake game")
        runs = web_service._runs_by_project["proj-1"]
        # Simulate the first run completing with a real result.
        runs[0].status = "completed"
        runs[0].result = "delivered: snake game v1"

        web_service.run_requirement("proj-1", "add multiplayer mode")
        runs = web_service._runs_by_project["proj-1"]
        assert len(runs) == 2
        assert runs[1].mode == "incremental"

    def test_second_run_after_failed_stays_initial(self, web_service) -> None:
        """A project whose first attempt failed has no baseline to
        build on. The next submission must re-run the full waterfall
        cleanly — NOT switch to incremental mode."""
        web_service.run_requirement("proj-1", "build a snake game")
        runs = web_service._runs_by_project["proj-1"]
        runs[0].status = "failed"
        runs[0].error = "recursion limit"

        web_service.run_requirement("proj-1", "retry")
        runs = web_service._runs_by_project["proj-1"]
        assert runs[1].mode == "initial"

    def test_second_run_after_completed_empty_result_stays_initial(self, web_service) -> None:
        """A completed run with an empty final report is not a real
        baseline either — mark_complete wasn't actually invoked with
        useful content."""
        web_service.run_requirement("proj-1", "build a snake game")
        runs = web_service._runs_by_project["proj-1"]
        runs[0].status = "completed"
        runs[0].result = "   "

        web_service.run_requirement("proj-1", "add feature")
        runs = web_service._runs_by_project["proj-1"]
        assert runs[1].mode == "initial"


# ---------------------------------------------------------------------------
# Serialization round-trip
# ---------------------------------------------------------------------------


class TestWorkflowRunModeSerialization:
    def test_default_mode_is_initial(self) -> None:
        run = WorkflowRun(
            run_id="r1",
            requirement_text="x",
            started_at=MagicMock(isoformat=lambda: "2026-04-19T00:00:00+00:00"),
        )
        assert run.mode == "initial"

    def test_serialize_includes_mode(self) -> None:
        import datetime as _dt

        from aise.web.app import WebProjectService

        run = WorkflowRun(
            run_id="r1",
            requirement_text="x",
            started_at=_dt.datetime(2026, 4, 19, tzinfo=_dt.timezone.utc),
            mode="incremental",
        )
        payload = WebProjectService._serialize_run(run)
        assert payload["mode"] == "incremental"

    def test_load_state_clamps_unknown_mode(self, web_service, tmp_path) -> None:
        """An on-disk run record with an unknown mode falls back to
        ``initial`` rather than propagating a value the UI can't
        render."""
        import json

        state = {
            "runs_by_project": {
                "proj-1": [
                    {
                        "run_id": "r1",
                        "requirement_text": "x",
                        "started_at": "2026-04-19T00:00:00+00:00",
                        "status": "completed",
                        "completed_at": "2026-04-19T00:05:00+00:00",
                        "error": "",
                        "result": "done",
                        "task_log": [],
                        "mode": "weird-new-mode",
                    }
                ]
            }
        }
        web_service._state_path.write_text(json.dumps(state), encoding="utf-8")
        web_service._runs_by_project.clear()
        web_service._load_state()
        runs = web_service._runs_by_project["proj-1"]
        assert runs[0].mode == "initial"


# ---------------------------------------------------------------------------
# ProjectSession mode propagation + phase-prompt content
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_session(tmp_path):
    """Build a ``ProjectSession`` with all heavy deps mocked."""
    from aise.runtime.project_session import ProjectSession

    with (
        patch.object(ProjectSession, "_build_pm_runtime", return_value=MagicMock()),
        patch.object(ProjectSession, "_select_orchestrator_name", return_value="project_manager"),
    ):
        manager = MagicMock()
        manager.runtimes = {"project_manager": MagicMock()}

        def _make(mode: str) -> ProjectSession:
            return ProjectSession(
                manager,
                project_root=tmp_path,
                mode=mode,
            )

        yield _make


class TestProjectSessionMode:
    def test_default_mode_is_initial(self, fake_session) -> None:
        session = fake_session("initial")
        assert session._mode == "initial"

    def test_unknown_mode_clamps_to_initial(self, fake_session) -> None:
        session = fake_session("bogus")
        assert session._mode == "initial"

    def test_incremental_mode_routes_to_incremental_builder(self, fake_session) -> None:
        session = fake_session("incremental")
        phases = session._build_phase_prompts("add feature X")
        # All six phases should be present.
        names = [name for name, _ in phases]
        assert names == ["requirements", "architecture", "implementation", "main_entry", "qa_testing", "delivery"]

    def test_initial_and_incremental_prompts_differ(self, fake_session) -> None:
        initial = fake_session("initial")._build_phase_prompts("feature X")
        incremental = fake_session("incremental")._build_phase_prompts("feature X")
        for (name_a, prompt_a), (name_b, prompt_b) in zip(initial, incremental):
            assert name_a == name_b
            assert prompt_a != prompt_b, (
                f"incremental prompt for phase '{name_a}' is identical to the "
                "initial prompt — incremental mode must materially differ"
            )


class TestIncrementalPromptContract:
    """Each phase's incremental prompt must carry the contract the
    runtime and the docs advertise: read existing artifacts first,
    append / edit in place rather than rewriting, and keep the full
    test suite on the QA phase."""

    @pytest.fixture
    def prompts(self, fake_session) -> dict[str, str]:
        phases = fake_session("incremental")._build_phase_prompts("add multiplayer")
        return dict(phases)

    def test_requirements_phase_appends(self, prompts) -> None:
        p = prompts["requirements"]
        assert "incremental" in p.lower()
        assert "docs/requirement.md" in p
        assert "APPEND" in p or "Append" in p or "append" in p
        assert "do not rewrite" in p.lower() or "do not reorder" in p.lower() or "do not renumber" in p.lower()
        # Per-requirement Mermaid use case diagrams still required.
        assert "mermaid" in p.lower() or "Mermaid" in p

    def test_architecture_phase_adds_only(self, prompts) -> None:
        p = prompts["architecture"]
        assert "docs/architecture.md" in p
        # "read existing first"
        assert "existing" in p.lower()
        # "preserve existing" / "grow, not shrink"
        assert "preserve" in p.lower() or "grow" in p.lower()
        # C4 requirement still in force
        for c4_type in ("C4Context", "C4Container", "C4Component"):
            assert c4_type in p

    def test_implementation_phase_edits_in_place(self, prompts) -> None:
        p = prompts["implementation"]
        assert "edit_file" in p, "incremental dev must use edit_file for CHANGED modules"
        assert "untouched" in p.lower() or "unrelated" in p.lower()
        # TDD is still the order of the day
        assert "tdd" in p.lower() or "TDD" in p

    def test_main_entry_phase_prefers_skip(self, prompts) -> None:
        p = prompts["main_entry"]
        assert "skip" in p.lower() or "SKIP" in p

    def test_qa_testing_phase_is_full_suite(self, prompts) -> None:
        """The hardest invariant of incremental mode — QA MUST still
        run the full pytest suite. Incremental changes can silently
        break existing flows and only the full run catches it."""
        p = prompts["qa_testing"]
        assert "FULL" in p
        # The concrete pytest command targets the whole tests/ tree.
        assert "pytest tests/" in p

    def test_delivery_phase_reports_delta(self, prompts) -> None:
        p = prompts["delivery"]
        # "Incremental Delta" section in the report.
        assert "Incremental Delta" in p or "incremental delta" in p.lower()
        # Must cite pass rate.
        assert "pass rate" in p.lower() or "percentage" in p.lower()
        # git-based delta detection attempt.
        assert "git" in p.lower()


# ---------------------------------------------------------------------------
# UI surface
# ---------------------------------------------------------------------------


class TestUIBadge:
    def test_mode_i18n_keys_in_both_languages(self) -> None:
        body = APP_JS.read_text(encoding="utf-8")
        for key in ("run.mode.initial", "run.mode.incremental", "run.mode.incremental_hint"):
            assert f'"{key}"' in body, f"missing i18n key {key}"
        # Both zh and en blocks should carry the keys — roughly: key
        # must appear twice in the file body.
        for key in ("run.mode.initial", "run.mode.incremental"):
            assert body.count(f'"{key}"') >= 2, f"{key} not in both zh and en"

    def test_badge_rendered_when_mode_is_incremental(self) -> None:
        body = APP_JS.read_text(encoding="utf-8")
        assert 'run.mode === "incremental"' in body
        assert "run-mode-badge" in body

    def test_css_class_defined(self) -> None:
        css = MAIN_CSS.read_text(encoding="utf-8")
        assert ".run-mode-badge" in css
        assert ".run-mode-badge-incremental" in css
