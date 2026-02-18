"""Tests for project manager global config inheritance and persistence."""

from __future__ import annotations

import json
from pathlib import Path

from aise.config import ProjectConfig
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
