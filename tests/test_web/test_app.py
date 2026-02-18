"""Tests for AISE web application and persistence."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

from aise.web.app import WebProjectService, create_app


def _mock_workflow_result(*args, **kwargs):
    return [
        {
            "phase": "requirements",
            "status": "completed",
            "tasks": {
                "product_manager.requirement_analysis": {
                    "status": "success",
                    "artifact_id": "artifact-1",
                }
            },
        }
    ]


def _login_dev(client: TestClient) -> None:
    resp = client.get("/auth/dev-login", follow_redirects=False)
    assert resp.status_code == 303


class TestWebApi:
    def test_api_requires_auth(self, monkeypatch):
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        app = create_app()
        client = TestClient(app)

        resp = client.get("/api/projects")
        assert resp.status_code == 401

    def test_project_and_requirement_api(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)

        app = create_app()
        service = app.state.web_service
        monkeypatch.setattr(service.project_manager, "run_project_workflow", _mock_workflow_result)

        client = TestClient(app)
        _login_dev(client)

        create_resp = client.post(
            "/api/projects",
            json={"project_name": "Portal", "development_mode": "local"},
        )
        assert create_resp.status_code == 200
        project_id = create_resp.json()["project_id"]

        list_resp = client.get("/api/projects")
        assert list_resp.status_code == 200
        assert len(list_resp.json()["projects"]) == 1

        req_resp = client.post(
            f"/api/projects/{project_id}/requirements",
            json={"requirement_text": "Build dashboard"},
        )
        assert req_resp.status_code == 200
        run_id = req_resp.json()["run_id"]

        runs_resp = client.get(f"/api/projects/{project_id}/runs")
        assert runs_resp.status_code == 200
        runs = runs_resp.json()["runs"]
        assert len(runs) == 1
        assert runs[0]["run_id"] == run_id

        cfg_resp = client.get("/api/config/global/data")
        assert cfg_resp.status_code == 200
        assert "model_catalog" in cfg_resp.json()

        update_cfg = client.post(
            "/api/config/global/data",
            json={
                "development_mode": "local",
                "model_catalog": [
                    {"id": "openai:gpt-4o", "default": True},
                    {"id": "anthropic:claude-sonnet-4-20250514", "default": False},
                ],
                "agent_model_selection": {"architect": "anthropic:claude-sonnet-4-20250514"},
            },
        )
        assert update_cfg.status_code == 200

    def test_requirement_submission_is_async_and_status_pollable(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)

        app = create_app()
        service = app.state.web_service

        def _slow_workflow(*args, **kwargs):
            time.sleep(0.3)
            return _mock_workflow_result(*args, **kwargs)

        monkeypatch.setattr(service.project_manager, "run_project_workflow", _slow_workflow)

        client = TestClient(app)
        _login_dev(client)

        create_resp = client.post(
            "/api/projects",
            json={"project_name": "AsyncProject", "development_mode": "local"},
        )
        assert create_resp.status_code == 200
        project_id = create_resp.json()["project_id"]

        req_resp = client.post(
            f"/api/projects/{project_id}/requirements",
            json={"requirement_text": "Build async status"},
        )
        assert req_resp.status_code == 200
        run_id = req_resp.json()["run_id"]

        run_now = client.get(f"/api/projects/{project_id}/runs/{run_id}")
        assert run_now.status_code == 200
        assert run_now.json()["status"] in {"pending", "running"}

        time.sleep(0.45)
        run_later = client.get(f"/api/projects/{project_id}/runs/{run_id}")
        assert run_later.status_code == 200
        assert run_later.json()["status"] == "completed"
        assert len(run_later.json()["phase_results"]) == 1

    def test_local_admin_login(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        app = create_app()
        client = TestClient(app)

        bad = client.post(
            "/auth/local-login",
            data={"username": "admin", "password": "wrong"},
            follow_redirects=False,
        )
        assert bad.status_code == 303
        assert "/login" in bad.headers["location"]

        ok = client.post(
            "/auth/local-login",
            data={"username": "admin", "password": "123456"},
            follow_redirects=False,
        )
        assert ok.status_code == 303
        assert ok.headers["location"] == "/"

        resp = client.get("/api/projects")
        assert resp.status_code == 200

    def test_create_project_with_agent_model_selection(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        app = create_app()
        client = TestClient(app)
        client.post(
            "/auth/local-login",
            data={"username": "admin", "password": "123456"},
            follow_redirects=False,
        )

        create_resp = client.post(
            "/api/projects",
            json={
                "project_name": "ModelSelection",
                "development_mode": "local",
                "agent_models": {"architect": "anthropic:claude-sonnet-4-20250514"},
            },
        )
        assert create_resp.status_code == 200
        project_id = create_resp.json()["project_id"]
        detail = client.get(f"/api/projects/{project_id}")
        assert detail.status_code == 200


class TestWebPersistence:
    def test_service_persists_runs_and_requirements(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)

        service = WebProjectService()
        monkeypatch.setattr(service.project_manager, "run_project_workflow", _mock_workflow_result)

        project_id = service.create_project("Persistent", "local")
        run_id = service.run_requirement(project_id, "Need API authentication")
        assert run_id

        state_file = Path("projects/web_state.json")
        assert state_file.exists()

        service_reloaded = WebProjectService()
        project_payload = service_reloaded.get_project(project_id)
        assert project_payload is not None
        assert len(project_payload["requirements"]) == 1
        assert len(project_payload["runs"]) == 1

    def test_delete_project_removes_directory_and_state(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)

        app = create_app()
        client = TestClient(app)
        _login_dev(client)

        create_resp = client.post(
            "/api/projects",
            json={"project_name": "ToDelete", "development_mode": "local"},
        )
        assert create_resp.status_code == 200
        project_id = create_resp.json()["project_id"]

        project_dirs = list((tmp_path / "projects").glob(f"{project_id}-*"))
        assert len(project_dirs) == 1
        assert project_dirs[0].exists()

        delete_resp = client.delete(f"/api/projects/{project_id}")
        assert delete_resp.status_code == 200
        assert delete_resp.json()["deleted"] is True

        assert not project_dirs[0].exists()
        assert client.get(f"/api/projects/{project_id}").status_code == 404
        assert client.get("/api/projects").json()["projects"] == []
