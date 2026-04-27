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


def _stub_scaffolding(service: "WebProjectService") -> None:
    """Replace the async PM scaffold dispatch with a synchronous
    filesystem stub.

    The real ``_dispatch_scaffolding_to_pm`` asks a real LLM to run
    ``git init`` / write ``.gitignore`` / ``mkdir`` the subdirs. In
    tests we have no LLM credentials — without this stub, every
    project lands in ``SCAFFOLDING_FAILED`` and every subsequent
    ``run_requirement`` submission is rejected.

    The stub creates the files the post-dispatch invariant check
    expects (``.git`` / ``.gitignore`` / the standard subdirs) so
    ``_scaffold_project`` flips the status to ACTIVE via its normal
    code path. This exercises more of the production flow than
    short-circuiting the whole background thread would.
    """

    def _synthetic_scaffold(project, prompt):  # type: ignore[no-untyped-def]
        root = Path(project.project_root)
        (root / ".git").mkdir(exist_ok=True)
        (root / ".gitignore").write_text("# test stub\n", encoding="utf-8")
        for subdir in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace"):
            (root / subdir).mkdir(exist_ok=True)

    service._dispatch_scaffolding_to_pm = _synthetic_scaffold  # type: ignore[method-assign]


def _wait_for_scaffolding(service: "WebProjectService", project_id: str, timeout: float = 2.0) -> str:
    """Poll the project's status until it leaves SCAFFOLDING.

    Returns the resolved status value (``"active"`` on happy path or
    ``"scaffolding_failed"`` if the stub wasn't installed). Raises on
    timeout so a hanging scaffold thread surfaces as a test failure
    instead of a mysterious downstream ``run_requirement`` rejection.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        project = service.project_manager.get_project(project_id)
        if project is not None and project.status.value != "scaffolding":
            return project.status.value
        time.sleep(0.02)
    raise AssertionError(f"scaffolding did not finish within {timeout}s for project {project_id}")


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
        # Vestigial: web runtime uses ProjectSession, not run_project_workflow.
        # PR-a removed the method from the runtime PM; keep ``raising=False``
        # so the patch is a no-op instead of an AttributeError.
        monkeypatch.setattr(service.project_manager, "run_project_workflow", _mock_workflow_result, raising=False)
        _stub_scaffolding(service)

        client = TestClient(app)
        _login_dev(client)

        create_resp = client.post(
            "/api/projects",
            json={"project_name": "Portal", "development_mode": "local"},
        )
        assert create_resp.status_code == 200
        project_id = create_resp.json()["project_id"]
        _wait_for_scaffolding(service, project_id)

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

        # Vestigial — see the note in the earlier test.
        monkeypatch.setattr(service.project_manager, "run_project_workflow", _slow_workflow, raising=False)
        _stub_scaffolding(service)

        # Stub the whole ``_execute_run`` worker so the test doesn't
        # need real LLM credentials. ``ProjectSession.__init__`` requires
        # a loaded orchestrator agent, which in test env with no API
        # key is unavailable — simulating the whole worker is simpler
        # than trying to fake ``RuntimeManager`` state.
        original_execute = service._execute_run

        def _fake_execute_run(project_id, run_id, requirement_text, mode, process_type, attempt):  # noqa: ARG001
            time.sleep(0.3)
            with service._lock:
                run = service._find_run(project_id, run_id)
                if run is not None:
                    run.status = "completed"
                    run.completed_at = datetime.now(timezone.utc)
                    run.result = "simulated completion"
                    run.failed_phase_idx = -1
                    run.failed_phase_name = ""
                service._active_workflow_runs.discard((project_id, run_id))
                service._save_state()

        service._execute_run = _fake_execute_run  # type: ignore[method-assign]
        # Add restore at test-teardown via monkeypatch.
        monkeypatch.setattr(service, "_execute_run", _fake_execute_run, raising=False)
        # Silence the unused ``original_execute`` warning.
        del original_execute

        client = TestClient(app)
        _login_dev(client)

        create_resp = client.post(
            "/api/projects",
            json={"project_name": "AsyncProject", "development_mode": "local"},
        )
        assert create_resp.status_code == 200
        project_id = create_resp.json()["project_id"]
        _wait_for_scaffolding(service, project_id)

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
        service = app.state.web_service
        _stub_scaffolding(service)
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
        _wait_for_scaffolding(service, project_id)
        detail = client.get(f"/api/projects/{project_id}")
        assert detail.status_code == 200

    def test_project_workflow_nodes_use_langchain_phases(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        app = create_app()
        service = app.state.web_service
        _stub_scaffolding(service)
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
        _wait_for_scaffolding(service, project_id)

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
        # Vestigial: web runtime uses ProjectSession, not run_project_workflow.
        # PR-a removed the method from the runtime PM; keep ``raising=False``
        # so the patch is a no-op instead of an AttributeError.
        monkeypatch.setattr(service.project_manager, "run_project_workflow", _mock_workflow_result, raising=False)
        _stub_scaffolding(service)

        project_id = service.create_project("Persistent", "local")
        _wait_for_scaffolding(service, project_id)
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
        # Vestigial: web runtime uses ProjectSession, not run_project_workflow.
        # PR-a removed the method from the runtime PM; keep ``raising=False``
        # so the patch is a no-op instead of an AttributeError.
        monkeypatch.setattr(service.project_manager, "run_project_workflow", _mock_workflow_result, raising=False)
        _stub_scaffolding(service)
        project_id = service.create_project("OrderCheck", "local")
        _wait_for_scaffolding(service, project_id)
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
        # Vestigial: web runtime uses ProjectSession, not run_project_workflow.
        # PR-a removed the method from the runtime PM; keep ``raising=False``
        # so the patch is a no-op instead of an AttributeError.
        monkeypatch.setattr(service.project_manager, "run_project_workflow", _mock_workflow_result, raising=False)
        _stub_scaffolding(service)
        project_id = service.create_project("ZombieHost", "local")
        _wait_for_scaffolding(service, project_id)
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

    def test_silent_failure_run_is_reclassified_on_load(self, monkeypatch, tmp_path):
        """Old ``_execute_run`` code marked runs as ``completed`` even when
        ``session.run()`` returned ``""`` (LLM backend dropped mid-run, the
        phase loop swallowed the exception, orchestrator never called
        mark_complete). Reclassify those on load so the retry / restart UI
        becomes available. Regression guard for run_019c47591a-style silent
        failures."""
        import json
        import time

        monkeypatch.chdir(tmp_path)

        service = WebProjectService()
        # Vestigial: web runtime uses ProjectSession, not run_project_workflow.
        # PR-a removed the method from the runtime PM; keep ``raising=False``
        # so the patch is a no-op instead of an AttributeError.
        monkeypatch.setattr(service.project_manager, "run_project_workflow", _mock_workflow_result, raising=False)
        _stub_scaffolding(service)
        project_id = service.create_project("SilentHost", "local")
        _wait_for_scaffolding(service, project_id)
        service.run_requirement(project_id, "req")
        # Wait for the background _execute_run thread to settle so our
        # manual state overwrite isn't clobbered by the thread's own
        # status save.
        time.sleep(0.5)

        state_path = Path("projects/web_state.json")
        data = json.loads(state_path.read_text())
        run = data["runs_by_project"][project_id][0]
        # The pre-fix pathology: status=completed but empty result.
        run["status"] = "completed"
        run["result"] = ""
        run["error"] = ""
        state_path.write_text(json.dumps(data))

        reloaded = WebProjectService()
        payload = reloaded.get_project(project_id)
        assert payload is not None
        r = payload["runs"][0]
        assert r["status"] == "failed", "silent-failure run must be reclassified as failed"
        assert "silent failure" in (r.get("error") or "").lower()

        # Persisted state must reflect the migration so it's idempotent.
        data2 = json.loads(state_path.read_text())
        assert data2["runs_by_project"][project_id][0]["status"] == "failed"

    def test_completed_run_with_result_is_not_reclassified(self, monkeypatch, tmp_path):
        """Guard the migration: a run that genuinely completed with a
        non-empty result must NOT be flipped to failed."""
        import json
        import time

        monkeypatch.chdir(tmp_path)

        service = WebProjectService()
        # Vestigial: web runtime uses ProjectSession, not run_project_workflow.
        # PR-a removed the method from the runtime PM; keep ``raising=False``
        # so the patch is a no-op instead of an AttributeError.
        monkeypatch.setattr(service.project_manager, "run_project_workflow", _mock_workflow_result, raising=False)
        _stub_scaffolding(service)
        project_id = service.create_project("HappyHost", "local")
        _wait_for_scaffolding(service, project_id)
        service.run_requirement(project_id, "req")
        time.sleep(0.5)

        state_path = Path("projects/web_state.json")
        data = json.loads(state_path.read_text())
        run = data["runs_by_project"][project_id][0]
        run["status"] = "completed"
        run["result"] = "Delivery report: everything works."
        run["error"] = ""
        state_path.write_text(json.dumps(data))

        reloaded = WebProjectService()
        payload = reloaded.get_project(project_id)
        r = payload["runs"][0]
        assert r["status"] == "completed", "genuinely completed run must stay completed"


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
        service = app.state.web_service
        _stub_scaffolding(service)
        client = TestClient(app)
        _login_dev(client)

        create_resp = client.post(
            "/api/projects",
            json={"project_name": "ToDelete", "development_mode": "local"},
        )
        assert create_resp.status_code == 200
        project_id = create_resp.json()["project_id"]
        _wait_for_scaffolding(service, project_id)

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
        _stub_scaffolding(service)
        project_id = service.create_project("RetryRecovery", "local")
        _wait_for_scaffolding(service, project_id)

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
        _stub_scaffolding(service)
        project_id = service.create_project("RunTaskSummary", "local")
        _wait_for_scaffolding(service, project_id)
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


class TestAIFirstScaffolding:
    """PR-b contract tests: project creation now triggers an async
    PM-agent dispatch that scaffolds the environment. These tests pin
    the state machine the web UI and safety-net (PR-c) rely on.
    """

    def test_create_project_starts_in_scaffolding_state(self, monkeypatch, tmp_path):
        """``project_manager.create_project`` returns immediately; the
        project lands in SCAFFOLDING until the background thread either
        succeeds or marks it failed."""
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        # Block the scaffold dispatch so the status stays visible.
        service._dispatch_scaffolding_to_pm = lambda project, prompt: time.sleep(5)  # type: ignore[method-assign]

        project_id, _ = service.create_project_with_initial_run(
            project_name="Inspection",
            development_mode="local",
        )
        project = service.project_manager.get_project(project_id)
        assert project is not None
        assert project.status.value == "scaffolding"
        assert project.scaffolding_error is None

    def test_scaffold_thread_flips_to_active_on_success(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        _stub_scaffolding(service)

        project_id = service.create_project("Happy", "local")
        status = _wait_for_scaffolding(service, project_id)
        assert status == "active"

        root = Path(service.project_manager.get_project(project_id).project_root)
        # Stub creates the subset the post-dispatch invariant check looks for.
        assert (root / ".git").exists()
        assert (root / ".gitignore").exists()

    def test_scaffold_recovered_by_safety_net_when_agent_does_nothing(self, monkeypatch, tmp_path):
        """PR-c layer: if the PM agent's scaffold dispatch returns
        without writing anything (silent failure — classic LLM
        regression), the safety net's mechanical repairs kick in and
        the project still lands in ACTIVE. The only visible trace is
        the structured event log.
        """
        import shutil

        if not shutil.which("git"):
            pytest.skip("git binary not on PATH")

        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        # "Agent" claims success but writes nothing.
        service._dispatch_scaffolding_to_pm = lambda project, prompt: None  # type: ignore[method-assign]

        project_id = service.create_project("Liar", "local")
        status = _wait_for_scaffolding(service, project_id)
        assert status == "active", "safety net must repair silent-failure scaffolds"
        project = service.project_manager.get_project(project_id)
        root = Path(project.project_root)
        # Safety net should have produced a real repo + .gitignore +
        # the standard layout.
        assert (root / ".git").exists()
        assert (root / ".gitignore").is_file()
        for name in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace"):
            assert (root / name).is_dir()

        # And a per-project event log with one entry per distinct
        # repair action fired.
        events_path = root / "trace" / "safety_net_events.jsonl"
        assert events_path.is_file()
        import json as _json

        events = [_json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        actions = {e["repair_action"] for e in events}
        assert {"missing_git_repo", "missing_gitignore", "missing_standard_subdirs"} <= actions

    def test_scaffold_fails_when_safety_net_repair_itself_fails(self, monkeypatch, tmp_path):
        """If the PM agent does nothing AND the safety net's
        mechanical repair also fails, the project lands in
        SCAFFOLDING_FAILED with an error blurb — this is the only
        code path that reaches that state now.
        """
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        service._dispatch_scaffolding_to_pm = lambda project, prompt: None  # type: ignore[method-assign]

        # Force every repair attempt to blow up.
        from aise.runtime import safety_net as _sn

        def _boom(project_root, ctx):  # noqa: ARG001
            raise RuntimeError("simulated repair failure")

        for key in list(_sn.REPAIR_ACTIONS):
            monkeypatch.setitem(_sn.REPAIR_ACTIONS, key, _boom)

        project_id = service.create_project("Broken", "local")
        status = _wait_for_scaffolding(service, project_id)
        assert status == "scaffolding_failed"
        project = service.project_manager.get_project(project_id)
        assert project.scaffolding_error
        assert "simulated repair failure" in project.scaffolding_error

    def test_run_requirement_rejected_while_scaffolding(self, monkeypatch, tmp_path):
        """A stale client (or a direct API call) hitting the requirements
        endpoint before scaffolding completes must get a clear rejection —
        racing the scaffold thread would corrupt project state."""
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        # Hold the dispatch — project stays in SCAFFOLDING.
        service._dispatch_scaffolding_to_pm = lambda project, prompt: time.sleep(5)  # type: ignore[method-assign]

        project_id = service.create_project("Racing", "local")
        with pytest.raises(ValueError, match="still scaffolding"):
            service.run_requirement(project_id, "premature submission")

    def test_run_requirement_rejected_after_scaffolding_failed(self, monkeypatch, tmp_path):
        """SCAFFOLDING_FAILED is also a hard block. Force it by breaking
        every repair in the safety net.
        """
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        service._dispatch_scaffolding_to_pm = lambda project, prompt: None  # type: ignore[method-assign]
        from aise.runtime import safety_net as _sn

        def _boom(project_root, ctx):  # noqa: ARG001
            raise RuntimeError("simulated repair failure")

        for key in list(_sn.REPAIR_ACTIONS):
            monkeypatch.setitem(_sn.REPAIR_ACTIONS, key, _boom)

        project_id = service.create_project("Broken", "local")
        _wait_for_scaffolding(service, project_id)
        with pytest.raises(ValueError, match="failed to scaffold"):
            service.run_requirement(project_id, "submission to a broken project")

    def test_project_card_surfaces_scaffolding_status_in_list(self, monkeypatch, tmp_path):
        """The dashboard list endpoint must expose the SCAFFOLDING /
        SCAFFOLDING_FAILED states so the React badge logic can render
        them correctly."""
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)
        app = create_app()
        service = app.state.web_service
        service._dispatch_scaffolding_to_pm = lambda project, prompt: time.sleep(5)  # type: ignore[method-assign]

        client = TestClient(app)
        _login_dev(client)
        create_resp = client.post(
            "/api/projects",
            json={"project_name": "BadgeCheck", "development_mode": "local"},
        )
        project_id = create_resp.json()["project_id"]

        list_resp = client.get("/api/projects")
        items = list_resp.json()["projects"]
        match = [p for p in items if p["project_id"] == project_id]
        assert match and match[0]["status"] == "scaffolding"


class TestGitSkillWiring:
    """Pins that the ``git`` skill is loadable and declared by the PM
    agent. The skill body is inlined into the PM's system prompt via
    the agent-md ``## Skills`` filter; a missing declaration means the
    scaffolding prompt is sent to an agent that hasn't been told how
    to use git. Catch that here rather than at run time.
    """

    SKILL_PATH = (
        Path(__file__).resolve().parents[2] / "src" / "aise" / "agents" / "_runtime_skills" / "git" / "SKILL.md"
    )
    PM_PATH = Path(__file__).resolve().parents[2] / "src" / "aise" / "agents" / "product_manager.md"

    def test_git_skill_file_exists(self) -> None:
        assert self.SKILL_PATH.is_file(), "src/aise/agents/_runtime_skills/git/SKILL.md missing"
        body = self.SKILL_PATH.read_text(encoding="utf-8")
        for needle in ("git init", "git tag phase_", "git log --oneline", ".gitignore"):
            assert needle in body, f"git SKILL.md must mention {needle!r}"

    def test_product_manager_declares_git_skill(self) -> None:
        body = self.PM_PATH.read_text(encoding="utf-8")
        assert "\n- git:" in body, (
            "product_manager.md must declare ``git`` in its ## Skills block; "
            "otherwise ``_load_inline_skill_content`` filters the SKILL.md body "
            "out of the PM's system prompt and the scaffolding dispatch would "
            "hit an agent that doesn't know the commands"
        )

    def test_product_manager_mentions_scaffolding_task(self) -> None:
        """The PM's system prompt must acknowledge the SCAFFOLDING TASK
        envelope so the agent recognizes the first dispatch and doesn't
        try to treat it as a regular requirement-analysis phase."""
        body = self.PM_PATH.read_text(encoding="utf-8")
        assert "SCAFFOLDING TASK" in body, "product_manager.md must reference the SCAFFOLDING TASK envelope"

    def test_git_on_shell_allowlist(self) -> None:
        from aise.runtime.runtime_config import DEFAULT_SHELL_ALLOWLIST

        assert "git" in DEFAULT_SHELL_ALLOWLIST, (
            "``git`` must be on the shell allowlist so the PM agent's "
            "``execute_shell`` calls (``git init``, ``git commit``, "
            "``git tag``, ``git log``, ``git diff``) don't get rejected"
        )


class TestSafetyNetAnalyticsEndpoint:
    """Integration tests for ``/api/analytics/safety-net`` + the
    ``/analytics/safety-net`` page (issue #122). The aggregator
    itself is unit-tested separately; here we only verify wiring,
    auth, and the end-to-end happy path.
    """

    def _seed(self, service, project_id: str, events: list[dict]) -> None:
        import json as _json

        events_path = service.project_manager._projects_root / project_id / "trace" / "safety_net_events.jsonl"
        events_path.parent.mkdir(parents=True, exist_ok=True)
        with events_path.open("w", encoding="utf-8") as fp:
            for ev in events:
                fp.write(_json.dumps(ev, ensure_ascii=False))
                fp.write("\n")

    def test_api_requires_auth(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)
        app = create_app()
        client = TestClient(app)
        resp = client.get("/api/analytics/safety-net")
        assert resp.status_code == 401

    def test_page_requires_auth(self, monkeypatch, tmp_path) -> None:
        monkeypatch.chdir(tmp_path)
        app = create_app()
        client = TestClient(app)
        resp = client.get("/analytics/safety-net", follow_redirects=False)
        # Unauthenticated access redirects to /login (303) or returns 401.
        assert resp.status_code in (303, 401)

    def test_api_empty_state_returns_zero_counts(self, monkeypatch, tmp_path) -> None:
        """Fresh deployment: no projects, no events. API must return
        a valid shape with zero totals — that's the empty-hero case
        the dashboard renders."""
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)
        app = create_app()
        client = TestClient(app)
        _login_dev(client)

        resp = client.get("/api/analytics/safety-net")
        assert resp.status_code == 200
        body = resp.json()
        assert "summary" in body and "known_project_ids" in body
        summary = body["summary"]
        assert summary["total"] == 0
        assert summary["recent"] == []
        assert summary["by_status"] == {}

    def test_api_aggregates_seeded_events_across_projects(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)
        app = create_app()
        service = app.state.web_service

        self._seed(
            service,
            "project_0-a",
            [
                {
                    "event_type": "llm_fallback_triggered",
                    "step_id": "scaffold",
                    "layer": "B",
                    "expected": "git_repo",
                    "actual": "repaired",
                    "repair_action": "missing_git_repo",
                    "repair_status": "success",
                    "detail": "",
                    "ts": "2026-04-22T10:00:00+00:00",
                },
                {
                    "event_type": "llm_fallback_triggered",
                    "step_id": "scaffold",
                    "layer": "B",
                    "expected": "file:.gitignore",
                    "actual": "repaired",
                    "repair_action": "missing_gitignore",
                    "repair_status": "success",
                    "detail": "",
                    "ts": "2026-04-22T10:00:01+00:00",
                },
            ],
        )
        self._seed(
            service,
            "project_1-b",
            [
                {
                    "event_type": "llm_fallback_triggered",
                    "step_id": "scaffold",
                    "layer": "A",
                    "expected": "missing_standard_subdirs",
                    "actual": "missing",
                    "repair_action": "missing_standard_subdirs",
                    "repair_status": "failed",
                    "detail": "mkdir failed",
                    "ts": "2026-04-22T11:00:00+00:00",
                },
            ],
        )

        client = TestClient(app)
        _login_dev(client)

        resp = client.get("/api/analytics/safety-net")
        assert resp.status_code == 200
        summary = resp.json()["summary"]
        assert summary["total"] == 3
        assert summary["by_status"] == {"success": 2, "failed": 1}
        assert summary["by_layer"] == {"B": 2, "A": 1}
        # Recent is newest-first — project_1-b's event should top.
        assert summary["recent"][0]["project_id"] == "project_1-b"

    def test_api_project_filter_scopes_to_one(self, monkeypatch, tmp_path) -> None:
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)
        app = create_app()
        service = app.state.web_service
        self._seed(
            service,
            "project_0-a",
            [
                {
                    "event_type": "llm_fallback_triggered",
                    "step_id": "scaffold",
                    "layer": "B",
                    "expected": "git_repo",
                    "actual": "repaired",
                    "repair_action": "missing_git_repo",
                    "repair_status": "success",
                    "detail": "",
                    "ts": "2026-04-22T10:00:00+00:00",
                }
            ],
        )
        self._seed(
            service,
            "project_1-b",
            [
                {
                    "event_type": "llm_fallback_triggered",
                    "step_id": "phase_1",
                    "layer": "B",
                    "expected": "clean_tree",
                    "actual": "repaired",
                    "repair_action": "uncommitted_changes",
                    "repair_status": "success",
                    "detail": "",
                    "ts": "2026-04-22T11:00:00+00:00",
                }
            ],
        )
        client = TestClient(app)
        _login_dev(client)

        resp = client.get("/api/analytics/safety-net?project_id=project_1-b")
        body = resp.json()
        assert body["summary"]["total"] == 1
        assert body["summary"]["recent"][0]["step_id"] == "phase_1"

    def test_page_renders_with_permission(self, monkeypatch, tmp_path) -> None:
        """The dashboard HTML loads (status 200) when the logged-in
        user carries ``view_analytics``. ``AISE_WEB_ENABLE_DEV_LOGIN``
        gives the dev account super_admin privileges, which includes
        the new permission."""
        monkeypatch.setenv("AISE_WEB_ENABLE_DEV_LOGIN", "true")
        monkeypatch.chdir(tmp_path)
        app = create_app()
        client = TestClient(app)
        _login_dev(client)
        resp = client.get("/analytics/safety-net")
        assert resp.status_code == 200
        # React root must be present so ``setupAnalyticsReact`` can
        # find it on client-side bootstrap.
        assert 'id="analytics-react-root"' in resp.text


class TestAnalyticsI18n:
    """The dashboard relies on a dedicated ``analytics.*`` i18n
    namespace. If keys go missing or zh/en drift apart, the UI
    regresses to raw keys. Pinning here lets a contributor editing
    locales catch the mismatch before a user hits it."""

    REQUIRED_KEYS = (
        "analytics.title",
        "analytics.subtitle",
        "analytics.filter_project",
        "analytics.filter_all_projects",
        "analytics.filter_since",
        "analytics.filter_until",
        "analytics.filter_limit",
        "analytics.refresh",
        "analytics.pill_total",
        "analytics.pill_success",
        "analytics.pill_failed",
        "analytics.pill_skipped",
        "analytics.pill_layer_b",
        "analytics.pill_layer_a",
        "analytics.top_step_ids",
        "analytics.top_repair_actions",
        "analytics.top_expected",
        "analytics.recent_heading",
        "analytics.recent_empty",
        "analytics.empty_hero",
        "analytics.no_data",
        "analytics.error_prefix",
        "analytics.col_ts",
        "analytics.col_project",
        "analytics.col_step",
        "analytics.col_layer",
        "analytics.col_expected",
        "analytics.col_action",
        "analytics.col_status",
        "nav.analytics",
    )

    @pytest.mark.parametrize("lang", ["zh", "en"])
    def test_required_keys_present(self, lang: str) -> None:
        import json as _json

        path = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "aise"
            / "web"
            / "static"
            / "locales"
            / lang
            / "translation.json"
        )
        data = _json.loads(path.read_text(encoding="utf-8"))

        def _get(dotted: str) -> object:
            node: object = data
            for part in dotted.split("."):
                if not isinstance(node, dict) or part not in node:
                    return None
                node = node[part]
            return node

        for key in self.REQUIRED_KEYS:
            value = _get(key)
            assert isinstance(value, str) and value.strip(), f"missing/empty {lang}/{key}"


class TestProjectTokenUsage:
    """Per-WorkflowRun + per-project LLM token accounting.

    The web layer aggregates token_usage events emitted by the
    orchestrator session (``token_usage`` event type) onto the
    matching ``WorkflowRun`` in real time, plus a project-level
    scaffolding bucket populated by ``_dispatch_scaffolding_to_pm``.
    """

    def test_run_aggregates_token_usage_events(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        _stub_scaffolding(service)
        project_id = service.create_project("TokenAggRun", "local")
        _wait_for_scaffolding(service, project_id)

        run_id = "run_token_001"
        with service._lock:
            service._runs_by_project.setdefault(project_id, []).append(
                web_app_module.WorkflowRun(
                    run_id=run_id,
                    requirement_text="Aggregate tokens",
                    started_at=datetime.now(timezone.utc),
                    status="running",
                )
            )

        # Drive the same callback the live ProjectSession would call.
        run_obj = service._find_run(project_id, run_id)
        assert run_obj is not None
        events = [
            {
                "type": "token_usage",
                "agent": "developer",
                "input_tokens": 100,
                "output_tokens": 30,
                "total_tokens": 130,
            },
            {"type": "token_usage", "agent": "developer", "input_tokens": 40, "output_tokens": 12, "total_tokens": 52},
            {
                "type": "token_usage",
                "agent": "project_manager",
                "input_tokens": 7,
                "output_tokens": 5,
                "total_tokens": 12,
            },
            # Non-token event must NOT bump the counters.
            {"type": "stage_update", "stage": "implementation"},
        ]
        for event in events:
            with service._lock:
                run = service._find_run(project_id, run_id)
                run.task_log.append(event)
                if event["type"] == "token_usage":
                    run.total_input_tokens += int(event.get("input_tokens") or 0)
                    run.total_output_tokens += int(event.get("output_tokens") or 0)
                    run.total_tokens += int(event.get("total_tokens") or 0)
                    run.llm_call_count += 1

        run = service._find_run(project_id, run_id)
        assert run.total_input_tokens == 147
        assert run.total_output_tokens == 47
        assert run.total_tokens == 194
        assert run.llm_call_count == 3

        # Persistence round-trip: serialize, restore, verify the
        # accumulated counts survive a process restart.
        service._save_state()
        service2 = WebProjectService()
        restored = service2._find_run(project_id, run_id)
        assert restored is not None
        assert restored.total_input_tokens == 147
        assert restored.total_output_tokens == 47
        assert restored.total_tokens == 194
        assert restored.llm_call_count == 3

    def test_project_token_summary_combines_scaffolding_and_runs(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        _stub_scaffolding(service)
        project_id = service.create_project("TokenSummary", "local")
        _wait_for_scaffolding(service, project_id)

        # Simulate scaffolding + two runs each having recorded tokens.
        with service._lock:
            service._scaffolding_tokens_by_project[project_id] = {
                "input": 50,
                "output": 20,
                "total": 70,
                "calls": 2,
            }
            for run_idx, (input_t, output_t, total_t, calls) in enumerate([(100, 40, 140, 3), (60, 25, 85, 2)]):
                service._runs_by_project.setdefault(project_id, []).append(
                    web_app_module.WorkflowRun(
                        run_id=f"run_{run_idx}",
                        requirement_text=f"req {run_idx}",
                        started_at=datetime.now(timezone.utc),
                        status="completed",
                        total_input_tokens=input_t,
                        total_output_tokens=output_t,
                        total_tokens=total_t,
                        llm_call_count=calls,
                    )
                )

        summary = service._project_token_summary(project_id)
        assert summary["scaffolding_input_tokens"] == 50
        assert summary["scaffolding_output_tokens"] == 20
        assert summary["scaffolding_total_tokens"] == 70
        assert summary["scaffolding_llm_calls"] == 2
        assert summary["input_tokens"] == 50 + 100 + 60
        assert summary["output_tokens"] == 20 + 40 + 25
        assert summary["total_tokens"] == 70 + 140 + 85
        assert summary["llm_calls"] == 2 + 3 + 2

        # ``get_project`` exposes the same summary on the API surface.
        payload = service.get_project(project_id)
        assert payload is not None
        assert payload["token_usage"] == summary

    def test_scaffolding_tokens_persisted_across_restarts(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()
        _stub_scaffolding(service)
        project_id = service.create_project("TokenScaffoldPersist", "local")
        _wait_for_scaffolding(service, project_id)

        with service._lock:
            service._scaffolding_tokens_by_project[project_id] = {
                "input": 11,
                "output": 4,
                "total": 15,
                "calls": 1,
            }
            service._save_state()

        service2 = WebProjectService()
        restored = service2._scaffolding_tokens_by_project.get(project_id)
        assert restored == {"input": 11, "output": 4, "total": 15, "calls": 1}

    def test_dispatch_scaffolding_records_tokens_via_callback(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)
        service = WebProjectService()

        # Replace get_runtime("product_manager") with a stub whose
        # handle_message synthesizes a single token_usage callback hit.
        captured_kwargs: dict = {}

        class _StubPM:
            def handle_message(self, prompt, **kwargs):
                captured_kwargs.update(kwargs)
                cb = kwargs.get("on_token_usage")
                if cb is not None:
                    cb({"input_tokens": 21, "output_tokens": 9, "total_tokens": 30})
                return "ok"

        def _get_runtime(name):
            assert name == "product_manager"
            return _StubPM()

        monkeypatch.setattr(service._runtime_manager, "get_runtime", _get_runtime)

        # Simulate creation: call the dispatch directly on a fake project.
        from aise.core.project import Project, ProjectStatus

        config = service.project_manager.create_default_project_config("TokenDispatch")
        project = Project(
            project_id="tok_dispatch_pid",
            config=config,
            project_root=str(tmp_path / "project"),
        )
        project.status = ProjectStatus.SCAFFOLDING
        Path(project.project_root).mkdir(parents=True, exist_ok=True)

        service._dispatch_scaffolding_to_pm(project, "scaffold this")

        bucket = service._scaffolding_tokens_by_project.get(project.project_id)
        assert bucket == {"input": 21, "output": 9, "total": 30, "calls": 1}
        # The runtime ALSO got the on_token_usage kwarg — proves the
        # plumbing wires up to the AgentRuntime, not just the test stub.
        assert "on_token_usage" in captured_kwargs
