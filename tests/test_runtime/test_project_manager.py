"""Tests for ``aise.runtime.project_manager`` — the web-runtime PM.

PR-a migrated the actively-used lifecycle methods from
``aise.core.project_manager`` into this new module. These tests pin both
halves of the migration:

1. The public API shape (signatures + return contracts) matches the
   caller's expectations. ``web/app.py`` is the only production caller
   and it must keep working unchanged.
2. Lifecycle behaviors that were previously covered in
   ``tests/test_core/test_project_manager.py`` still pass against the
   new module. The module-level copy is deliberate — once the legacy
   core module is removed, the core test file goes away with it and
   this file stands alone.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from aise.config import ProjectConfig
from aise.core.project import ProjectStatus
from aise.runtime.project_manager import ProjectManager


class _StubOrchestrator:
    def __init__(self) -> None:
        self.agents: dict[str, object] = {}


def _write_global_config(path: Path) -> None:
    data = {
        "project_name": "Global Template",
        "development_mode": "local",
        "default_model": {
            "provider": "anthropic",
            "model": "claude-opus-4",
            "api_key": "",
            "base_url": "",
            "temperature": 0.2,
            "max_tokens": 8192,
            "extra": {},
        },
        "workflow": {
            "max_review_iterations": 5,
            "fail_on_review_rejection": True,
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _make_manager(tmp_path: Path, monkeypatch) -> ProjectManager:
    monkeypatch.setattr("aise.main.create_team", lambda *args, **kwargs: _StubOrchestrator())
    global_config_path = tmp_path / "config/global_project_config.json"
    _write_global_config(global_config_path)
    return ProjectManager(
        projects_root=tmp_path / "projects",
        global_config_path=global_config_path,
    )


class TestPublicApiSignatures:
    """The web layer imports a handful of methods by name. If the
    signature drifts, ``WebProjectService`` would either break at
    runtime or silently behave differently. Pin it with ``inspect`` so
    the breakage shows up as a test failure instead.
    """

    REQUIRED_METHODS = (
        "__init__",
        "create_project",
        "create_default_project_config",
        "_prepare_project_root",
        "get_project",
        "list_projects",
        "delete_project",
        "pause_project",
        "resume_project",
        "complete_project",
        "get_project_info",
        "get_all_projects_info",
    )

    def test_all_required_methods_present(self) -> None:
        for name in self.REQUIRED_METHODS:
            assert hasattr(ProjectManager, name), f"ProjectManager.{name} missing after migration"
            assert callable(getattr(ProjectManager, name))

    def test_create_project_signature_accepts_name_config_agent_counts(self) -> None:
        sig = inspect.signature(ProjectManager.create_project)
        params = dict(sig.parameters)
        # ``self`` + the three public kwargs used by ``web/app.py``.
        assert set(params) == {"self", "project_name", "config", "agent_counts"}
        assert params["config"].default is None
        assert params["agent_counts"].default is None

    def test_constructor_accepts_kw_only_projects_root_and_global_config_path(self) -> None:
        sig = inspect.signature(ProjectManager.__init__)
        assert "projects_root" in sig.parameters
        assert "global_config_path" in sig.parameters
        # Both must be keyword-only to match the ``ProjectManager()``
        # call in ``WebProjectService``.
        assert sig.parameters["projects_root"].kind == inspect.Parameter.KEYWORD_ONLY
        assert sig.parameters["global_config_path"].kind == inspect.Parameter.KEYWORD_ONLY

    def test_dead_workflow_methods_are_absent(self) -> None:
        """These served the legacy ``MultiProjectSession`` path and
        were intentionally left behind. Their presence would indicate
        a regression to the pre-migration blob."""
        for name in (
            "run_project_workflow",
            "_normalize_dynamic_workflow_result",
            "_normalize_deep_workflow_result",
            "_infer_phase_from_process",
            "_split_phase_agent_key",
            "_build_phase_task_payload",
            "_get_planner_llm_client",
        ):
            assert not hasattr(ProjectManager, name), (
                f"ProjectManager.{name} should NOT be on the runtime PM — it belongs to the legacy core module"
            )


class TestGlobalConfigInheritance:
    """Carried over from ``tests/test_core/test_project_manager.py`` —
    ``WebProjectService.create_project`` depends on the config snapshot
    landing at ``<project_root>/project_config.json`` and on the
    returned config inheriting global defaults.
    """

    def test_create_project_inherits_global_config_and_persists_snapshot(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        project_id = manager.create_project("RD-Portal")
        project = manager.get_project(project_id)

        assert project is not None
        assert project.config.default_model.provider == "anthropic"
        assert project.config.workflow.max_review_iterations == 5
        assert project.project_root is not None

        config_file = Path(project.project_root) / "project_config.json"
        assert config_file.exists()
        persisted = ProjectConfig.from_json_file(config_file)
        assert persisted.project_name == "RD-Portal"
        assert persisted.default_model.model == "claude-opus-4"
        assert persisted.workflow.fail_on_review_rejection is True

        for subdir in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace"):
            assert (Path(project.project_root) / subdir).exists(), f"scaffold missing {subdir}/"

    def test_create_default_project_config_returns_global_template_copy(self, tmp_path):
        global_config_path = tmp_path / "config/global_project_config.json"
        _write_global_config(global_config_path)

        manager = ProjectManager(
            projects_root=tmp_path / "projects",
            global_config_path=global_config_path,
        )
        config = manager.create_default_project_config("MyProject")

        assert config.project_name == "MyProject"
        assert config.default_model.provider == "anthropic"
        assert config.workflow.max_review_iterations == 5

    def test_create_project_without_global_config_file_uses_builtin_defaults(self, tmp_path, monkeypatch):
        """If ``config/global_project_config.json`` is missing, the
        manager falls back to ``ProjectConfig()`` defaults — never
        raises."""
        monkeypatch.setattr("aise.main.create_team", lambda *args, **kwargs: _StubOrchestrator())
        manager = ProjectManager(
            projects_root=tmp_path / "projects",
            global_config_path=tmp_path / "does/not/exist.json",
        )
        project_id = manager.create_project("NoGlobalConfigProject")
        assert manager.get_project(project_id) is not None


class TestProjectLifecycle:
    """Lifecycle transitions the web layer invokes on user actions
    (pause / resume / complete / delete). Covered here for the first
    time — previously no lifecycle tests existed in the core file."""

    def test_pause_and_resume_round_trip(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        project_id = manager.create_project("LifecycleProject")

        assert manager.pause_project(project_id) is True
        project = manager.get_project(project_id)
        assert project is not None and project.status == ProjectStatus.PAUSED

        assert manager.resume_project(project_id) is True
        project = manager.get_project(project_id)
        assert project is not None and project.status == ProjectStatus.ACTIVE

    def test_resume_on_non_paused_project_returns_false(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        project_id = manager.create_project("ActiveProject")
        # Project is ACTIVE, not PAUSED → resume must return False.
        assert manager.resume_project(project_id) is False

    def test_complete_flips_status(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        project_id = manager.create_project("CompletionProject")

        assert manager.complete_project(project_id) is True
        project = manager.get_project(project_id)
        assert project is not None and project.status == ProjectStatus.COMPLETED

    def test_delete_removes_project_from_registry(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        project_id = manager.create_project("Doomed")

        assert manager.delete_project(project_id) is True
        assert manager.get_project(project_id) is None
        assert manager.delete_project(project_id) is False  # second delete → no-op

    def test_list_projects_filters_by_status(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        active_id = manager.create_project("Active")
        paused_id = manager.create_project("Paused")
        manager.pause_project(paused_id)

        active_list = manager.list_projects(status_filter=ProjectStatus.ACTIVE)
        assert [p.project_id for p in active_list] == [active_id]

        paused_list = manager.list_projects(status_filter=ProjectStatus.PAUSED)
        assert [p.project_id for p in paused_list] == [paused_id]

        all_list = manager.list_projects()
        assert {p.project_id for p in all_list} == {active_id, paused_id}

    def test_get_project_info_returns_dict_for_existing_and_none_for_missing(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        project_id = manager.create_project("InfoProject")
        info = manager.get_project_info(project_id)
        assert isinstance(info, dict)
        assert info["project_id"] == project_id
        assert manager.get_project_info("does-not-exist") is None

    def test_get_all_projects_info_matches_project_count(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        manager.create_project("A")
        manager.create_project("B")
        manager.create_project("C")
        infos = manager.get_all_projects_info()
        assert len(infos) == manager.project_count == 3
        assert all(isinstance(i, dict) for i in infos)

    def test_project_id_sequence_is_monotonic(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        ids = [manager.create_project(f"Seq{i}") for i in range(3)]
        assert ids == ["project_0", "project_1", "project_2"]


class TestProjectRootLayout:
    """``_prepare_project_root`` is the only scaffolding step this PR
    touches (just a mkdir; AI-First git init is a follow-up PR). Pin
    the subdirs and sanitized-name logic so PR-b knows exactly what
    it is replacing.
    """

    def test_subdirs_created(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        project_id = manager.create_project("Any")
        root = Path(manager.get_project(project_id).project_root)
        for subdir in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace"):
            assert (root / subdir).is_dir()

    def test_project_name_sanitized_into_directory_slug(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        project_id = manager.create_project("My Weird / Project Name!")
        root = Path(manager.get_project(project_id).project_root)
        # Non-alnum → dashes, collapsed, lowercased.
        assert root.name.endswith("-my-weird-project-name")

    def test_empty_project_name_falls_back_to_project_slug(self, tmp_path, monkeypatch):
        manager = _make_manager(tmp_path, monkeypatch)
        project_id = manager.create_project("???")
        root = Path(manager.get_project(project_id).project_root)
        assert root.name.endswith("-project")
