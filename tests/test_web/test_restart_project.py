"""Tests for project restart — full-root wipe semantics.

The semantics changed from "wipe a hard-coded subset of dirs" to
"wipe everything except ``WebProjectService._RESTART_PRESERVE``"
(see project_0-tower analysis). The new contract is idempotent under
language switches: a Python -> Dart restart no longer leaves
``pyproject.toml``, ``node_modules/``, etc. lying around to corrupt
the next stack_contract.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from unittest.mock import MagicMock, patch

import pytest

from aise.web.app import RequirementEntry, WebProjectService, WorkflowRun


@pytest.fixture
def service(tmp_path: Path):
    """Create a WebProjectService with a real on-disk project root.

    ``tmp_path`` is the projects-root, ``tmp_path/project_0-test``
    is the project root. The safety guard in ``restart_project``
    checks that the project root resolves underneath the projects
    root before wiping, so the mock ``project_manager`` must
    advertise the same.
    """
    with patch.object(WebProjectService, "__init__", lambda self: None):
        svc = WebProjectService.__new__(WebProjectService)

    svc._lock = RLock()
    svc._runs_by_project = {}
    svc._requirements_by_project = {}
    svc._active_workflow_runs = set()
    svc._state_path = tmp_path / "web_state.json"
    svc._save_state = MagicMock()

    svc.project_manager = MagicMock()
    svc.project_manager._projects_root = tmp_path
    svc._runtime_manager = MagicMock()

    project_root = tmp_path / "project_0-test"
    project_root.mkdir()

    mock_project = MagicMock()
    mock_project.project_root = str(project_root)
    mock_project.project_id = "project_0"
    svc.project_manager.get_project.return_value = mock_project

    return svc, project_root


def _seed_requirement(svc: WebProjectService) -> None:
    svc._requirements_by_project["project_0"] = [
        RequirementEntry(
            requirement_id="r1",
            text="build it",
            created_at=datetime.now(timezone.utc),
        ),
    ]
    svc.run_requirement = MagicMock(return_value="run_123")


class TestRestartProjectFullWipe:
    """Everything except ``_RESTART_PRESERVE`` is removed on restart."""

    def test_clears_legacy_python_layout(self, service):
        svc, root = service
        # Files from a previous Python run.
        (root / "src").mkdir()
        (root / "tests").mkdir()
        (root / "docs").mkdir()
        (root / "src" / "main.py").write_text("print('hi')")
        (root / "tests" / "test_main.py").write_text("def test_x(): pass")
        (root / "docs" / "design.md").write_text("design")
        (root / "pyproject.toml").write_text("[project]\nname = 'x'\n")

        _seed_requirement(svc)
        svc.restart_project("project_0")

        for name in ("src", "tests", "docs", "pyproject.toml"):
            assert not (root / name).exists(), f"{name} should have been removed"

    def test_clears_dart_layout(self, service):
        svc, root = service
        (root / "lib").mkdir()
        (root / "lib" / "main.dart").write_text("void main() {}")
        (root / "test").mkdir()
        (root / "test" / "main_test.dart").write_text("// test")
        (root / "pubspec.yaml").write_text("name: snake")
        (root / "pubspec.lock").write_text("# lock")

        _seed_requirement(svc)
        svc.restart_project("project_0")

        for name in ("lib", "test", "pubspec.yaml", "pubspec.lock"):
            assert not (root / name).exists(), f"{name} should have been removed"

    def test_clears_node_modules_and_lockfiles(self, service):
        """The exact cross-language leftover that motivated this change.

        After a previous Phaser/Node run, ``node_modules/`` (~80 MB)
        and ``package*.json`` survive into the next restart even
        though they're on the safety-net ``must_not_exist`` list.
        Full-root wipe makes this unreachable.
        """
        svc, root = service
        (root / "node_modules").mkdir()
        (root / "node_modules" / "lodash").mkdir()
        (root / "node_modules" / "lodash" / "index.js").write_text("module.exports = {}")
        (root / "package.json").write_text('{"name":"x"}')
        (root / "package-lock.json").write_text("{}")

        _seed_requirement(svc)
        svc.restart_project("project_0")

        for name in ("node_modules", "package.json", "package-lock.json"):
            assert not (root / name).exists(), f"{name} should have been removed"

    def test_clears_unknown_topdir(self, service):
        """Arbitrary top-level dirs from organic agent writes are wiped."""
        svc, root = service
        for name in ("assets", "saves", "server", "data", "test_pkg", "dart-sdk"):
            (root / name).mkdir()
            (root / name / "x.txt").write_text("x")

        _seed_requirement(svc)
        svc.restart_project("project_0")

        for name in ("assets", "saves", "server", "data", "test_pkg", "dart-sdk"):
            assert not (root / name).exists(), f"{name} should have been removed"

    def test_clears_nested_files(self, service):
        svc, root = service
        nested = root / "src" / "game" / "core"
        nested.mkdir(parents=True)
        (nested / "engine.py").write_text("class Engine: pass")
        (root / "lib" / "ui").mkdir(parents=True)
        (root / "lib" / "ui" / "widget.dart").write_text("// widget")

        _seed_requirement(svc)
        svc.restart_project("project_0")

        assert not (root / "src").exists()
        assert not (root / "lib").exists()


class TestRestartProjectPreserve:
    """Only the small ``_RESTART_PRESERVE`` set survives."""

    def test_preserves_project_config(self, service):
        svc, root = service
        cfg = root / "project_config.json"
        cfg.write_text('{"name": "test"}')

        _seed_requirement(svc)
        svc.restart_project("project_0")

        assert cfg.exists()
        assert cfg.read_text() == '{"name": "test"}'

    def test_preserves_dot_git(self, service):
        svc, root = service
        git_dir = root / ".git"
        git_dir.mkdir()
        (git_dir / "HEAD").write_text("ref: refs/heads/main\n")
        (git_dir / "config").write_text("[core]\n")

        # Add other content that should be wiped.
        (root / "src").mkdir()
        (root / "src" / "main.py").write_text("x")

        _seed_requirement(svc)
        svc.restart_project("project_0")

        assert git_dir.is_dir()
        assert (git_dir / "HEAD").read_text() == "ref: refs/heads/main\n"
        assert not (root / "src").exists()

    def test_preserve_set_is_minimal(self):
        """Guard against silently expanding the carve-out list."""
        assert WebProjectService._RESTART_PRESERVE == frozenset({".git", "project_config.json"})


class TestRestartProjectStateAndSafety:
    """In-memory bookkeeping + safety guards."""

    def test_clears_in_memory_state(self, service):
        svc, root = service
        svc._runs_by_project["project_0"] = [
            WorkflowRun(
                run_id="old_run",
                requirement_text="old",
                started_at=datetime.now(timezone.utc),
                status="completed",
            ),
        ]
        svc._requirements_by_project["project_0"] = [
            RequirementEntry(
                requirement_id="r1",
                text="old req",
                created_at=datetime.now(timezone.utc),
            ),
        ]
        svc._active_workflow_runs = {("project_0", "old_run"), ("other", "other_run")}

        svc.run_requirement = MagicMock(return_value="run_new")
        svc.restart_project("project_0")

        assert svc._runs_by_project["project_0"] == []
        assert svc._requirements_by_project["project_0"] == []
        assert ("project_0", "old_run") not in svc._active_workflow_runs
        assert ("other", "other_run") in svc._active_workflow_runs

    def test_resubmits_original_requirement(self, service):
        svc, root = service
        svc._requirements_by_project["project_0"] = [
            RequirementEntry(
                requirement_id="r1",
                text="build a snake game",
                created_at=datetime.now(timezone.utc),
            ),
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

    def test_refuses_to_wipe_outside_projects_root(self, tmp_path: Path):
        """A misconfigured project_root that resolves outside the
        projects root must NOT be wiped — defense against symlink
        leak that would otherwise let restart turn into rm -rf /."""
        with patch.object(WebProjectService, "__init__", lambda self: None):
            svc = WebProjectService.__new__(WebProjectService)
        svc._lock = RLock()
        svc._runs_by_project = {}
        svc._requirements_by_project = {}
        svc._active_workflow_runs = set()
        svc._state_path = tmp_path / "web_state.json"
        svc._save_state = MagicMock()

        svc.project_manager = MagicMock()
        # Projects root is one place, project_root somewhere else.
        projects_root = tmp_path / "projects"
        projects_root.mkdir()
        outsider = tmp_path / "elsewhere"
        outsider.mkdir()
        (outsider / "important.txt").write_text("DO NOT DELETE")

        svc.project_manager._projects_root = projects_root
        mock_project = MagicMock()
        mock_project.project_root = str(outsider)
        mock_project.project_id = "project_0"
        svc.project_manager.get_project.return_value = mock_project

        svc._requirements_by_project["project_0"] = [
            RequirementEntry(
                requirement_id="r1",
                text="x",
                created_at=datetime.now(timezone.utc),
            ),
        ]
        svc.run_requirement = MagicMock(return_value="run_x")

        with pytest.raises(ValueError, match="outside projects directory"):
            svc.restart_project("project_0")

        # File outside the projects root MUST still exist.
        assert (outsider / "important.txt").exists()
