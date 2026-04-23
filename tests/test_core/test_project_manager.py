"""Tests for project manager global config inheritance and persistence."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from aise.config import ProjectConfig
from aise.core.project import Project
from aise.core.project_manager import ProjectManager


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


class TestProjectManagerGlobalConfig:
    def test_create_project_inherits_global_config_and_persists_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.setattr("aise.main.create_team", lambda *args, **kwargs: _StubOrchestrator())

        global_config_path = tmp_path / "config/global_project_config.json"
        _write_global_config(global_config_path)

        manager = ProjectManager(
            projects_root=tmp_path / "projects",
            global_config_path=global_config_path,
        )
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

        assert (Path(project.project_root) / "docs").exists()
        assert (Path(project.project_root) / "src").exists()
        assert (Path(project.project_root) / "tests").exists()
        assert (Path(project.project_root) / "trace").exists()

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

    @pytest.mark.slow
    def test_run_project_workflow_supports_deep_orchestrator_result(self, tmp_path):
        manager = ProjectManager(
            projects_root=tmp_path / "projects",
            global_config_path=tmp_path / "config/global_project_config.json",
        )

        class _DeepStub:
            agents: dict[str, object] = {}

            def run_workflow(self, requirements, project_name):
                assert requirements == {"raw_requirements": "Build API"}
                assert project_name == "DeepWebProject"
                return {
                    "status": "completed",
                    "phase_results": {
                        "requirements_product_manager": "completed",
                        "design_architect": "completed",
                        "implementation_developer": "completed",
                    },
                    "artifact_ids": ["artifact-xyz"],
                    "messages": [],
                }

        project = Project(
            project_id="project_0",
            config=ProjectConfig(project_name="DeepWebProject"),
            orchestrator=_DeepStub(),  # type: ignore[arg-type]
            project_root=str(tmp_path / "projects/project_0"),
        )
        manager._projects[project.project_id] = project

        rows = manager.run_project_workflow("project_0", {"raw_requirements": "Build API"})
        assert len(rows) == 3
        assert rows[0]["phase"] == "requirements"
        assert rows[0]["status"] == "completed"
        task_payload = rows[0]["tasks"]["product_manager.requirements"]
        assert task_payload["status"] == "success"
        assert task_payload["artifact_id"] == "artifact-xyz"
        deep_payload = rows[0]["tasks"]["product_manager.deep_product_workflow"]
        assert deep_payload["status"] == "success"
        assert deep_payload["artifact_id"] == "artifact-xyz"
        assert rows[1]["tasks"]["architect.deep_architecture_workflow"]["status"] == "success"
        assert rows[2]["tasks"]["developer.deep_developer_workflow"]["status"] == "success"

    @pytest.mark.slow
    def test_run_project_workflow_deep_error_maps_to_failed_row(self, tmp_path):
        manager = ProjectManager(
            projects_root=tmp_path / "projects",
            global_config_path=tmp_path / "config/global_project_config.json",
        )

        class _DeepFailingStub:
            agents: dict[str, object] = {}

            def run_workflow(self, requirements, project_name):
                return {
                    "status": "error",
                    "error": "deep runtime crashed",
                    "phase_results": {},
                    "artifact_ids": [],
                }

        project = Project(
            project_id="project_1",
            config=ProjectConfig(project_name="DeepErrorProject"),
            orchestrator=_DeepFailingStub(),  # type: ignore[arg-type]
            project_root=str(tmp_path / "projects/project_1"),
        )
        manager._projects[project.project_id] = project

        rows = manager.run_project_workflow("project_1", {"raw_requirements": "X"})
        assert len(rows) == 1
        assert rows[0]["phase"] == "workflow"
        assert rows[0]["status"] == "failed"
        assert rows[0]["tasks"]["deep_orchestrator.run_workflow"]["status"] == "error"

    @pytest.mark.slow
    def test_run_project_workflow_falls_back_when_deep_returns_empty(self, tmp_path):
        manager = ProjectManager(
            projects_root=tmp_path / "projects",
            global_config_path=tmp_path / "config/global_project_config.json",
        )

        class _BaseStub:
            agents: dict[str, object] = {}

            def run_default_workflow(self, requirements, project_name):
                assert requirements == {"raw_requirements": "Build API"}
                assert project_name == "FallbackProject"
                return [
                    {
                        "phase": "requirements",
                        "status": "completed",
                        "tasks": {"product_manager.deep_product_workflow": {"status": "success"}},
                    }
                ]

        class _DeepEmptyStub:
            agents: dict[str, object] = {}
            orchestrator = _BaseStub()

            def run_workflow(self, requirements, project_name):
                return {
                    "status": "completed",
                    "phase_results": {},
                    "artifact_ids": [],
                    "messages": [],
                }

        project = Project(
            project_id="project_2",
            config=ProjectConfig(project_name="FallbackProject"),
            orchestrator=_DeepEmptyStub(),  # type: ignore[arg-type]
            project_root=str(tmp_path / "projects/project_2"),
        )
        manager._projects[project.project_id] = project

        rows = manager.run_project_workflow("project_2", {"raw_requirements": "Build API"})
        assert len(rows) == 1
        assert rows[0]["phase"] == "requirements"
        assert rows[0]["status"] == "completed"


class TestProjectGetInfoScaffoldingError:
    def test_get_info_includes_scaffolding_error_key_when_unset(self):
        project = Project(
            project_id="p_info_0",
            config=ProjectConfig(project_name="InfoScaffoldOK"),
            orchestrator=_StubOrchestrator(),  # type: ignore[arg-type]
        )
        info = project.get_info()
        assert "scaffolding_error" in info
        assert info["scaffolding_error"] is None
        assert info["status"] == "scaffolding"

    def test_get_info_exposes_scaffolding_error_after_failure(self):
        project = Project(
            project_id="p_info_1",
            config=ProjectConfig(project_name="InfoScaffoldFail"),
            orchestrator=_StubOrchestrator(),  # type: ignore[arg-type]
        )
        project.fail_scaffolding("mkdir refused: permission denied on /opt/ai")
        info = project.get_info()
        assert info["status"] == "scaffolding_failed"
        assert info["scaffolding_error"] == "mkdir refused: permission denied on /opt/ai"
