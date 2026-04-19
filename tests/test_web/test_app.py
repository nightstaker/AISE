"""Tests for AISE web application and persistence."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi.testclient import TestClient

import aise.web.app as web_app_module
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
    def test_api_requires_auth(self, monkeypatch, tmp_path):
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)
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

    def test_layout_injects_ui_language(self, monkeypatch, tmp_path):
        """Every page extends ``layout.html`` which must emit
        ``window.__AISE_LANG`` so the React frontend's ``t()`` helper
        knows which language table to use. Pinned here because a
        missing injection is invisible until a user hits a page in a
        different locale and sees mixed Chinese/English."""
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)
        app = create_app()
        client = TestClient(app)
        _login_dev(client)

        resp = client.get("/")
        assert resp.status_code == 200
        assert "window.__AISE_LANG" in resp.text
        # Default language is ``zh`` — the original UI locale.
        assert '"zh"' in resp.text

    def test_settings_language_roundtrip(self, monkeypatch, tmp_path):
        """Posting the workspace settings form with a language switch
        must persist the new ``ui_language`` to the global config and
        surface it on the next page render via the layout injection."""
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)
        app = create_app()
        client = TestClient(app)
        _login_dev(client)

        resp = client.post(
            "/config/global/workspace",
            data={
                "ui_language": "en",
                "projects_root": "projects",
                "artifacts_root": "artifacts",
                "auto_create_dirs": "on",
            },
            follow_redirects=False,
        )
        # The handler redirects back to the settings page on success.
        assert resp.status_code in (200, 302, 303)

        # Verify the choice persisted + is served to subsequent pages.
        svc = app.state.web_service
        assert svc.get_ui_language() == "en"

        page = client.get("/")
        assert '"en"' in page.text

    def test_settings_language_bogus_value_is_ignored(self, monkeypatch, tmp_path):
        """An unknown locale code must not corrupt the config. The
        backend clamps unknown values; the existing language is
        preserved."""
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)
        app = create_app()
        client = TestClient(app)
        _login_dev(client)

        svc = app.state.web_service
        assert svc.get_ui_language() == "zh"  # default

        resp = client.post(
            "/config/global/workspace",
            data={
                "ui_language": "not-a-real-locale",
                "projects_root": "projects",
                "artifacts_root": "artifacts",
            },
            follow_redirects=False,
        )
        assert resp.status_code in (200, 302, 303)
        # Still the default — the bogus value was rejected.
        assert svc.get_ui_language() == "zh"

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

    def test_project_workflow_nodes_use_langchain_phases(self, monkeypatch, tmp_path):
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
            json={"project_name": "LangchainWeb", "development_mode": "local"},
        )
        assert create_resp.status_code == 200
        project_id = create_resp.json()["project_id"]

        detail = client.get(f"/api/projects/{project_id}")
        assert detail.status_code == 200
        workflow_nodes = detail.json().get("workflow_nodes", [])
        assert [node.get("name") for node in workflow_nodes] == [
            "requirements",
            "design",
            "implementation",
            "testing",
        ]
        assert all("agent_tasks" in node for node in workflow_nodes)
        assert isinstance(workflow_nodes[0].get("agent_tasks"), list)
        requirements_agents = [item.get("agent") for item in workflow_nodes[0].get("agent_tasks", [])]
        assert "product_designer" in requirements_agents
        assert "product_reviewer" in requirements_agents
        design_agents = [item.get("agent") for item in workflow_nodes[1].get("agent_tasks", [])]
        assert "architecture_designer" in design_agents
        assert "architecture_reviewer[*]" in design_agents
        assert "subsystem_architect[*]" in design_agents
        implementation_agents = [item.get("agent") for item in workflow_nodes[2].get("agent_tasks", [])]
        assert "programmer[*]" in implementation_agents
        assert "code_reviewer[*]" in implementation_agents


class TestWebPersistence:
    def test_web_logger_has_dedicated_file(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)

        service = WebProjectService()
        assert service is not None
        assert Path("logs/aise-web.log").exists()
        assert logging.getLogger("aise.web.app").propagate is False

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

    def test_get_project_returns_runs_in_insertion_order(self, monkeypatch, tmp_path):
        """Regression guard: the frontend's "jump to latest run" logic
        depends on understanding the order ``get_project`` returns runs
        in. Backend returns them in insertion (chronological) order, so
        ``runs[0]`` is the oldest. The frontend therefore must sort by
        ``started_at`` before picking a target; previously it used
        ``runs[0]`` and redirected users to a days-old failed run when
        they clicked the project card.
        """
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        monkeypatch.setattr(service.project_manager, "run_project_workflow", _mock_workflow_result)
        project_id = service.create_project("OrderCheck", "local")
        service.run_requirement(project_id, "first")
        service.run_requirement(project_id, "second")
        service.run_requirement(project_id, "third")
        payload = service.get_project(project_id)
        assert payload is not None
        runs = payload["runs"]
        assert len(runs) == 3
        # Insertion order: earliest first. The sort stability matters
        # because the frontend sort in ``pickLatestRun`` flips this.
        times = [r["started_at"] for r in runs]
        assert times == sorted(times), "Expected insertion (chronological) order; frontend depends on this contract."

    def test_zombie_running_run_is_reaped_on_startup(self, monkeypatch, tmp_path):
        """Runs stored as running/pending when the server starts have no live
        worker thread (``_active_workflow_runs`` is not persisted). Without
        reaping, the dashboard and run-detail UI poll forever. Regression
        guard for zombie runs left over from server crash/restart."""
        import json

        monkeypatch.chdir(tmp_path)

        # Seed a service with one legitimate completed run
        service = WebProjectService()
        monkeypatch.setattr(service.project_manager, "run_project_workflow", _mock_workflow_result)
        project_id = service.create_project("ZombieHost", "local")
        service.run_requirement(project_id, "req")

        # Manually corrupt the persisted state to simulate a crash while
        # running: flip the run status to "running" and clear completed_at.
        state_path = Path("projects/web_state.json")
        data = json.loads(state_path.read_text())
        run = data["runs_by_project"][project_id][0]
        run["status"] = "running"
        run["completed_at"] = None
        run["error"] = ""
        state_path.write_text(json.dumps(data))

        # Reload — reaper should fire
        reloaded = WebProjectService()
        payload = reloaded.get_project(project_id)
        assert payload is not None
        r = payload["runs"][0]
        assert r["status"] == "failed"
        assert "interrupted" in (r.get("error") or "").lower()
        assert r.get("completed_at"), "reaped run should have a completed_at"

        # Persisted state should reflect the reap so the next restart doesn't
        # have to redo the work.
        data2 = json.loads(state_path.read_text())
        assert data2["runs_by_project"][project_id][0]["status"] == "failed"


class TestWebTaskStatusInference:
    def test_runtime_running_status_is_not_downgraded_to_pending(self):
        status = WebProjectService._infer_live_task_status(
            phase_status="running",
            runtime_status="running",
            has_trace_events=False,
        )
        assert status == "running"

    def test_runtime_in_progress_status_is_not_downgraded_to_pending(self):
        status = WebProjectService._infer_live_task_status(
            phase_status="running",
            runtime_status="in_progress",
            has_trace_events=False,
        )
        assert status == "running"

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


class TestTaskRetryRecovery:
    def test_retry_recovers_stale_running_operation(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        project_id = service.create_project("RetryRecovery", "local")

        run_id = "run_stale_001"
        with service._lock:
            service._runs_by_project.setdefault(project_id, []).append(
                web_app_module.WorkflowRun(
                    run_id=run_id,
                    requirement_text="Recover stale retry",
                    started_at=datetime.now(timezone.utc),
                    status="running",
                )
            )
            service._save_state()

        store = service._run_task_state_store(project_id, run_id)
        store.save(
            {
                "active_operation": {
                    "op_id": "retry_stale_dead",
                    "type": "task_retry",
                    "status": "running",
                    "phase_key": "requirements",
                    "task_key": "product_manager.deep_product_workflow.step1",
                    "mode": "current",
                    "started_at": datetime.now(timezone.utc).isoformat(),
                },
                "tasks": {
                    "requirements::product_manager.deep_product_workflow.step1": {
                        "phase_key": "requirements",
                        "task_key": "product_manager.deep_product_workflow.step1",
                        "display_name": "step1",
                        "latest_status": "running",
                        "latest_attempt_no": 1,
                        "attempts": [
                            {
                                "attempt_no": 1,
                                "kind": "retry",
                                "mode": "current",
                                "status": "running",
                                "started_at": datetime.now(timezone.utc).isoformat(),
                                "completed_at": None,
                                "error": "",
                                "executor": {},
                                "context": {},
                                "outputs": {},
                            }
                        ],
                    }
                },
            }
        )

        monkeypatch.setattr(
            service,
            "_build_task_execution_plan",
            lambda *args, **kwargs: [
                web_app_module.TaskExecUnit(
                    phase_key="requirements",
                    task_key="product_manager.deep_product_workflow.step1",
                    agent_name="product_manager",
                    skill_name="deep_product_workflow",
                    execution_scope="step1",
                    display_name="step1",
                )
            ],
        )

        class _FakeThread:
            def __init__(self, *args, **kwargs):
                self.args = args
                self.kwargs = kwargs

            def start(self):
                return None

        monkeypatch.setattr(web_app_module, "Thread", _FakeThread)

        result = service.retry_task(
            project_id,
            run_id,
            phase_key="requirements",
            task_key="product_manager.deep_product_workflow.step1",
            mode="current",
        )

        assert result["accepted"] is True
        task_state = store.get_task("requirements", "product_manager.deep_product_workflow.step1")
        assert task_state is not None
        assert task_state["latest_status"] == "failed"
        assert task_state["attempts"][0]["status"] == "failed"


class TestWebRunTaskSummary:
    def test_get_run_exposes_developer_step1_workflow_summary_subsystems(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        project_id = service.create_project("RunTaskSummary", "local")
        run_id = "run_step1_summary_001"

        with service._lock:
            service._runs_by_project.setdefault(project_id, []).append(
                web_app_module.WorkflowRun(
                    run_id=run_id,
                    requirement_text="Build subsystem cards",
                    started_at=datetime.now(timezone.utc),
                    status="running",
                )
            )
            service._save_state()

        store = service._run_task_state_store(project_id, run_id)
        store.save(
            {
                "tasks": {
                    "implementation::developer.deep_developer_workflow.step1": {
                        "phase_key": "implementation",
                        "task_key": "developer.deep_developer_workflow.step1",
                        "display_name": "step1",
                        "latest_status": "completed",
                        "latest_attempt_no": 1,
                        "attempts": [
                            {
                                "attempt_no": 1,
                                "kind": "initial",
                                "mode": "current",
                                "status": "completed",
                                "started_at": datetime.now(timezone.utc).isoformat(),
                                "completed_at": datetime.now(timezone.utc).isoformat(),
                                "error": "",
                                "executor": {},
                                "context": {},
                                "outputs": {
                                    "workflow_summary": {
                                        "workflow": "deep_developer_workflow",
                                        "subsystems": [
                                            {
                                                "subsystem_id": "SUB-001",
                                                "subsystem_name": "User Service",
                                                "subsystem_slug": "user_service",
                                                "assigned_sr_ids": ["SR-001"],
                                            }
                                        ],
                                        "rounds": {"step2": 3},
                                    }
                                },
                            }
                        ],
                    }
                }
            }
        )

        payload = service.get_run(project_id, run_id)
        assert payload is not None
        summary = payload.get("task_state_summary", {})
        assert isinstance(summary, dict)
        key = "implementation::developer.deep_developer_workflow.step1"
        assert key in summary
        latest_outputs = summary[key].get("latest_outputs", {})
        workflow_summary = latest_outputs.get("workflow_summary", {})
        assert workflow_summary.get("workflow") == "deep_developer_workflow"
        subsystems = workflow_summary.get("subsystems", [])
        assert isinstance(subsystems, list)
        assert len(subsystems) == 1
        assert subsystems[0]["subsystem_id"] == "SUB-001"
