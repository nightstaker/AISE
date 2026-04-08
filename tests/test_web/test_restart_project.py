"""Tests for project restart — ensures disk cleanup and state reset."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aise.web.app import RequirementEntry, WebProjectService, WorkflowRun


@pytest.fixture
def service(tmp_path: Path):
    """Create a WebProjectService with mocked internals."""
    with patch.object(WebProjectService, "__init__", lambda self: None):
        svc = WebProjectService.__new__(WebProjectService)

    # Minimal init
    from threading import RLock

    svc._lock = RLock()
    svc._runs_by_project = {}
    svc._requirements_by_project = {}
    svc._active_workflow_runs = set()
    svc._state_path = tmp_path / "web_state.json"

    # Mock project_manager
    svc.project_manager = MagicMock()

    # Mock runtime_manager
    svc._runtime_manager = MagicMock()

    # Create a fake project with a real tmp directory as project_root
    project_root = tmp_path / "project_0-test"
    project_root.mkdir()
    for subdir in ("docs", "src", "tests", "runs/trace", "runs/docs", "runs/plans"):
        (project_root / subdir).mkdir(parents=True)

    mock_project = MagicMock()
    mock_project.project_root = str(project_root)
    mock_project.project_id = "project_0"
    svc.project_manager.get_project.return_value = mock_project

    return svc, project_root


class TestRestartProjectDiskCleanup:
    """Verify restart_project clears docs/, src/, tests/, trace/ on disk."""

    def test_clears_docs_directory(self, service):
        svc, root = service
        # Create some files in docs/
        (root / "docs" / "requirements.md").write_text("old requirements")
        (root / "docs" / "design.md").write_text("old design")
        assert len(list((root / "docs").iterdir())) == 2

        # Add a requirement so restart can find it
        svc._requirements_by_project["project_0"] = [
            RequirementEntry(requirement_id="r1", text="build something", created_at=datetime.now(timezone.utc)),
        ]
        # Mock run_requirement to avoid actual execution
        svc.run_requirement = MagicMock(return_value="run_123")

        svc.restart_project("project_0")

        # docs/ should be empty
        assert (root / "docs").is_dir()
        assert len(list((root / "docs").iterdir())) == 0

    def test_clears_src_directory(self, service):
        svc, root = service
        (root / "src" / "main.py").write_text("print('hello')")
        (root / "src" / "utils.py").write_text("def foo(): pass")

        svc._requirements_by_project["project_0"] = [
            RequirementEntry(requirement_id="r1", text="build it", created_at=datetime.now(timezone.utc)),
        ]
        svc.run_requirement = MagicMock(return_value="run_123")

        svc.restart_project("project_0")

        assert (root / "src").is_dir()
        assert len(list((root / "src").iterdir())) == 0

    def test_clears_tests_directory(self, service):
        svc, root = service
        (root / "tests" / "test_main.py").write_text("def test_pass(): pass")

        svc._requirements_by_project["project_0"] = [
            RequirementEntry(requirement_id="r1", text="test it", created_at=datetime.now(timezone.utc)),
        ]
        svc.run_requirement = MagicMock(return_value="run_123")

        svc.restart_project("project_0")

        assert (root / "tests").is_dir()
        assert len(list((root / "tests").iterdir())) == 0

    def test_clears_runs_directory(self, service):
        svc, root = service
        (root / "runs" / "trace" / "call_001.json").write_text("{}")
        (root / "runs" / "docs" / "temp.md").write_text("temp")
        (root / "runs" / "plans" / "plan.md").write_text("plan")

        svc._requirements_by_project["project_0"] = [
            RequirementEntry(requirement_id="r1", text="trace it", created_at=datetime.now(timezone.utc)),
        ]
        svc.run_requirement = MagicMock(return_value="run_123")

        svc.restart_project("project_0")

        assert (root / "runs").is_dir()
        assert len(list((root / "runs").iterdir())) == 0

    def test_clears_nested_files(self, service):
        """Ensure subdirectories within docs/src are also removed."""
        svc, root = service
        nested = root / "src" / "game" / "core"
        nested.mkdir(parents=True)
        (nested / "engine.py").write_text("class Engine: pass")
        (root / "docs" / "sub" / "detail.md").parent.mkdir(parents=True, exist_ok=True)
        (root / "docs" / "sub" / "detail.md").write_text("detail")

        svc._requirements_by_project["project_0"] = [
            RequirementEntry(requirement_id="r1", text="nested test", created_at=datetime.now(timezone.utc)),
        ]
        svc.run_requirement = MagicMock(return_value="run_123")

        svc.restart_project("project_0")

        assert len(list((root / "src").iterdir())) == 0
        assert len(list((root / "docs").iterdir())) == 0

    def test_clears_in_memory_state(self, service):
        svc, root = service
        svc._runs_by_project["project_0"] = [
            WorkflowRun(
                run_id="old_run", requirement_text="old", started_at=datetime.now(timezone.utc), status="completed"
            ),
        ]
        svc._requirements_by_project["project_0"] = [
            RequirementEntry(requirement_id="r1", text="old req", created_at=datetime.now(timezone.utc)),
        ]
        svc._active_workflow_runs = {("project_0", "old_run"), ("other", "other_run")}

        svc.run_requirement = MagicMock(return_value="run_new")

        svc.restart_project("project_0")

        assert svc._runs_by_project["project_0"] == []
        assert svc._requirements_by_project["project_0"] == []
        assert ("project_0", "old_run") not in svc._active_workflow_runs
        assert ("other", "other_run") in svc._active_workflow_runs

    def test_clears_stale_home_directory(self, service):
        """home/ dir created by absolute path leakage should be cleaned."""
        svc, root = service
        stale_home = root / "home" / "user" / "project"
        stale_home.mkdir(parents=True)
        (stale_home / "leaked.py").write_text("leaked")

        svc._requirements_by_project["project_0"] = [
            RequirementEntry(requirement_id="r1", text="clean it", created_at=datetime.now(timezone.utc)),
        ]
        svc.run_requirement = MagicMock(return_value="run_123")

        svc.restart_project("project_0")

        assert not (root / "home").exists()

    def test_preserves_project_config(self, service):
        """project_config.json should NOT be deleted."""
        svc, root = service
        config_file = root / "project_config.json"
        config_file.write_text('{"name": "test"}')

        svc._requirements_by_project["project_0"] = [
            RequirementEntry(requirement_id="r1", text="keep config", created_at=datetime.now(timezone.utc)),
        ]
        svc.run_requirement = MagicMock(return_value="run_123")

        svc.restart_project("project_0")

        assert config_file.exists()
        assert config_file.read_text() == '{"name": "test"}'

    def test_resubmits_original_requirement(self, service):
        svc, root = service
        svc._requirements_by_project["project_0"] = [
            RequirementEntry(requirement_id="r1", text="build a snake game", created_at=datetime.now(timezone.utc)),
        ]
        svc.run_requirement = MagicMock(return_value="run_new")

        result = svc.restart_project("project_0")

        svc.run_requirement.assert_called_once_with("project_0", "build a snake game")
        assert result == "run_new"

    def test_no_requirement_raises(self, service):
        svc, root = service
        svc._runs_by_project["project_0"] = []
        svc._requirements_by_project["project_0"] = []

        with pytest.raises(ValueError, match="No original requirement"):
            svc.restart_project("project_0")

    def test_project_not_found_raises(self, service):
        svc, root = service
        svc.project_manager.get_project.return_value = None

        with pytest.raises(ValueError, match="not found"):
            svc.restart_project("project_0")
