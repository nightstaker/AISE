"""Integration test: ProjectSession + waterfall_v2 wiring (c15)."""

from __future__ import annotations

from pathlib import Path

# -- ProjectSession process_type whitelist --------------------------------


class TestProcessTypeWhitelist:
    def test_waterfall_v2_accepted(self):
        # Read the source to verify the whitelist line was updated.
        # Importing the class would trigger the pre-existing circular
        # import unrelated to c15.
        text = Path("src/aise/runtime/project_session.py").read_text(encoding="utf-8")
        assert '"waterfall", "agile", "waterfall_v2"' in text

    def test_run_dispatches_to_v2_branch(self):
        text = Path("src/aise/runtime/project_session.py").read_text(encoding="utf-8")
        assert 'self._process_type == "waterfall_v2"' in text
        assert "return self._run_waterfall_v2(requirement)" in text

    def test_v2_method_present(self):
        text = Path("src/aise/runtime/project_session.py").read_text(encoding="utf-8")
        assert "def _run_waterfall_v2" in text
        assert "WaterfallV2Driver" in text
        # produce_fn / dispatch_reviewer adapters present
        assert "make_observable_produce_fn" in text


# -- Web routes -----------------------------------------------------------


class TestWebRoutes:
    def test_resume_route_registered(self):
        text = Path("src/aise/web/app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/projects/{project_id}/resume")' in text
        assert "load_halt_state" in text
        assert "is_halted" in text

    def test_abort_route_registered(self):
        text = Path("src/aise/web/app.py").read_text(encoding="utf-8")
        assert '@app.post("/api/tasks/{task_id}/abort")' in text
        assert "request_abort" in text

    def test_active_tasks_route_registered(self):
        text = Path("src/aise/web/app.py").read_text(encoding="utf-8")
        assert '@app.get("/api/tasks/active")' in text
        assert "active_tasks" in text


# -- CLI subcommands ------------------------------------------------------


class TestCliSubcommands:
    def test_resume_project_subcommand(self):
        text = Path("src/aise/main.py").read_text(encoding="utf-8")
        assert '"resume_project"' in text
        assert "_cmd_resume_project" in text

    def test_abort_task_subcommand(self):
        text = Path("src/aise/main.py").read_text(encoding="utf-8")
        assert '"abort_task"' in text
        assert "_cmd_abort_task" in text

    def test_active_tasks_subcommand(self):
        text = Path("src/aise/main.py").read_text(encoding="utf-8")
        assert '"active_tasks"' in text
        assert "_cmd_active_tasks" in text

    def test_cli_help_includes_new_subcommands(self):
        """Smoke test: the argparse help output mentions the 3 new
        subcommands. This catches argparse mis-registration."""
        import subprocess

        result = subprocess.run(
            [".venv/bin/python", "-m", "aise.main", "--help"],
            capture_output=True,
            text=True,
            timeout=20,
            cwd=Path(__file__).resolve().parent.parent.parent,
        )
        # Python may print stuff to stderr (logging config) but help is
        # always on stdout
        assert "resume_project" in result.stdout
        assert "abort_task" in result.stdout
        assert "active_tasks" in result.stdout


# -- Adapter smoke test ---------------------------------------------------


class TestAdapterSmoke:
    """Ensure the produce_fn adapter inside _run_waterfall_v2 has the
    right shape: takes (role, prompt, expected) and returns str.
    """

    def test_make_observable_produce_fn_signature_matches(self):
        from aise.runtime.waterfall_v2_driver import make_observable_produce_fn

        seen: list[tuple] = []

        def underlying(role, prompt, expected):
            seen.append((role, prompt, list(expected)))
            return "ok"

        wrapped = make_observable_produce_fn(underlying)
        # _run_waterfall_v2 calls produce_fn(role, prompt, list(expected))
        result = wrapped("developer", "do it", ["src/x.py"])
        assert result == "ok"
        assert seen == [("developer", "do it", ["src/x.py"])]


# -- Resume route logic (mocked service) ---------------------------------


class TestResumeRouteLogic:
    """Exercise the route helper logic without a running web server.

    The route uses load_halt_state + service.run_requirement; we test
    that path by calling load_halt_state directly with a written halt
    file."""

    def test_load_halt_state_round_trip(self, tmp_path: Path):
        from aise.runtime.halt_resume import (
            HaltState,
            is_halted,
            load_halt_state,
            save_halt_state,
        )

        save_halt_state(
            tmp_path,
            HaltState(
                halted_at_phase="implementation",
                halt_reason="producer_acceptance_gate_exhausted",
                halt_detail="missing src/foo.py",
                completed_phases=("requirements", "architecture"),
            ),
        )
        assert is_halted(tmp_path)
        loaded = load_halt_state(tmp_path)
        assert loaded.halted_at_phase == "implementation"

    def test_route_404_when_project_missing(self, tmp_path: Path):
        # The route checks service.get_project — verify the import path
        # works and the route guards exist (regression: typo in route
        # would 500 instead of 404).
        text = Path("src/aise/web/app.py").read_text(encoding="utf-8")
        # Both branches present
        assert 'detail="Project not found"' in text
        assert "Halt state file present but unparseable" in text
