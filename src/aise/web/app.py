"""FastAPI web system for project management."""

from __future__ import annotations

import json
import os
import secrets
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock, Thread
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER, HTTP_401_UNAUTHORIZED

from ..config import ProjectConfig
from ..core.project import Project, ProjectStatus
from ..core.project_manager import ProjectManager
from ..utils.logging import configure_logging, configure_module_file_logger, get_logger

try:
    from authlib.integrations.starlette_client import OAuth
except Exception:  # pragma: no cover - optional dependency
    OAuth = None

logger = get_logger(__name__)


@dataclass
class WorkflowRun:
    """Represents one workflow execution for a requirement."""

    run_id: str
    requirement_text: str
    started_at: datetime
    status: str = "pending"
    completed_at: datetime | None = None
    error: str = ""
    result: str = ""
    task_log: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RequirementEntry:
    """Represents one requirement dispatch entry."""

    requirement_id: str
    text: str
    created_at: datetime
    source: str = "web"


class WebProjectService:
    """Coordinates project operations used by the web layer.

    Uses RuntimeManager for agent lifecycle and ProjectSession for
    workflow execution. All legacy orchestrator logic has been removed.
    """

    def __init__(self) -> None:
        self.project_manager = ProjectManager()
        configure_logging(self.project_manager._global_config.logging, force=True)
        web_log_file = Path(self.project_manager._global_config.logging.log_dir) / "aise-web.log"
        configure_module_file_logger(
            "aise.web.app",
            web_log_file,
            json_format=self.project_manager._global_config.logging.json_format,
            rotate_daily=self.project_manager._global_config.logging.rotate_daily,
            propagate=False,
        )
        self._runs_by_project: dict[str, list[WorkflowRun]] = {}
        self._requirements_by_project: dict[str, list[RequirementEntry]] = {}
        self._lock = RLock()
        self._active_workflow_runs: set[tuple[str, str]] = set()
        self._state_path = self.project_manager._projects_root / "web_state.json"
        self._restore_projects_from_disk()
        self._load_state()

        from ..runtime.manager import RuntimeManager

        self._runtime_manager = RuntimeManager(config=self.project_manager._global_config)
        self._runtime_manager.start()

        logger.info("WebProjectService initialized: state_path=%s", self._state_path)

    # -- Project CRUD --------------------------------------------------------

    def list_projects(self) -> list[dict[str, Any]]:
        with self._lock:
            infos = self.project_manager.get_all_projects_info()
            # Project-lifecycle ``status`` (active/paused/completed/archived)
            # is NOT the same as "a workflow is currently running". Expose an
            # explicit ``has_active_run`` flag so the dashboard can render an
            # honest badge instead of painting every non-archived project as
            # "running".
            active_project_ids = {pid for (pid, _run_id) in self._active_workflow_runs}
            for info in infos:
                pid = info.get("project_id")
                runs = self._runs_by_project.get(pid, [])
                info["has_active_run"] = pid in active_project_ids
                info["latest_run_status"] = runs[-1].status if runs else None
            infos.sort(key=lambda item: item["updated_at"], reverse=True)
            return infos

    def create_project(
        self,
        project_name: str,
        development_mode: str,
        agent_models: dict[str, str] | None = None,
        initial_requirement: str = "",
    ) -> str:
        project_id, _ = self.create_project_with_initial_run(
            project_name=project_name,
            development_mode=development_mode,
            agent_models=agent_models,
            initial_requirement=initial_requirement,
        )
        return project_id

    def create_project_with_initial_run(
        self,
        *,
        project_name: str,
        development_mode: str,
        agent_models: dict[str, str] | None = None,
        initial_requirement: str = "",
    ) -> tuple[str, str | None]:
        if not project_name.strip():
            raise ValueError("Project name cannot be empty")
        mode = "github" if development_mode == "github" else "local"
        config = self.project_manager.create_default_project_config(project_name)
        config.development_mode = mode
        if agent_models:
            for agent_name, model_id in agent_models.items():
                normalized = str(model_id).strip()
                if normalized:
                    config.agent_model_selection[agent_name] = normalized
        with self._lock:
            project_id = self.project_manager.create_project(project_name, config)
            self._runs_by_project.setdefault(project_id, [])
            self._requirements_by_project.setdefault(project_id, [])
            self._save_state()
            run_id: str | None = None
            initial_text = initial_requirement.strip()
            if initial_text:
                run_id = self.run_requirement(project_id, initial_text)
            logger.info("Web create_project completed: project_id=%s", project_id)
            return project_id, run_id

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            project = self.project_manager.get_project(project_id)
            if project is None:
                return None
            history = self._runs_by_project.get(project_id, [])
            return {
                "info": project.get_info(),
                "workflow_nodes": [],
                "runs": [self._serialize_run(run) for run in history],
                "requirements": [
                    self._serialize_requirement(item) for item in self._list_requirement_history(project_id)
                ],
            }

    def get_run(self, project_id: str, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            run = self._find_run(project_id, run_id)
            if run is None:
                return None
            return self._serialize_run(run)

    def delete_project(self, project_id: str) -> None:
        with self._lock:
            project = self.project_manager.get_project(project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found")
            project_root = Path(project.project_root).resolve() if project.project_root else None
            projects_root = self.project_manager._projects_root.resolve()
            if project_root is not None and project_root.exists():
                if not project_root.is_relative_to(projects_root):
                    raise ValueError("Refuse to delete project directory outside projects root")
                shutil.rmtree(project_root)
            deleted = self.project_manager.delete_project(project_id)
            if not deleted:
                raise ValueError(f"Project {project_id} not found")
            self._runs_by_project.pop(project_id, None)
            self._requirements_by_project.pop(project_id, None)
            self._active_workflow_runs = {(pid, rid) for pid, rid in self._active_workflow_runs if pid != project_id}
            self._save_state()
            logger.info("Web project deleted: project_id=%s", project_id)

    def restart_project(self, project_id: str) -> str | None:
        """Clear all runs/requirements and re-execute the first requirement."""
        with self._lock:
            project = self.project_manager.get_project(project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found")

            # Find the original requirement
            reqs = self._requirements_by_project.get(project_id, [])
            original_text = ""
            if reqs:
                earliest = min(reqs, key=lambda r: r.created_at)
                original_text = earliest.text

            if not original_text:
                runs = self._runs_by_project.get(project_id, [])
                if runs:
                    original_text = runs[0].requirement_text

            if not original_text:
                raise ValueError("No original requirement found to restart")

            # Clear in-memory state
            self._runs_by_project[project_id] = []
            self._requirements_by_project[project_id] = []
            self._active_workflow_runs = {(pid, rid) for pid, rid in self._active_workflow_runs if pid != project_id}

            # Clear project output directories on disk
            project_root = Path(project.project_root) if project.project_root else None
            if project_root and project_root.is_dir():
                for subdir in ("docs", "src", "tests", "runs"):
                    target = project_root / subdir
                    if target.is_dir():
                        shutil.rmtree(target)
                    target.mkdir(parents=True, exist_ok=True)
                # Also clean stale dirs from old layout
                for stale in ("trace", "home"):
                    target = project_root / stale
                    if target.is_dir():
                        shutil.rmtree(target)

            self._save_state()
            logger.info("Project restarted: project_id=%s (disk cleaned)", project_id)

        # Re-submit the original requirement
        return self.run_requirement(project_id, original_text)

    # -- Requirement execution via ProjectSession ----------------------------

    def run_requirement(self, project_id: str, requirement_text: str) -> str:
        """Submit requirement and execute workflow via ProjectSession."""
        with self._lock:
            project = self.project_manager.get_project(project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found")
            run_id = f"run_{uuid.uuid4().hex[:10]}"
            run = WorkflowRun(
                run_id=run_id,
                requirement_text=requirement_text,
                started_at=datetime.now(timezone.utc),
                status="running",
            )
            self._runs_by_project.setdefault(project_id, []).append(run)
            self._requirements_by_project.setdefault(project_id, []).append(
                RequirementEntry(
                    requirement_id=uuid.uuid4().hex[:10],
                    text=requirement_text,
                    created_at=datetime.now(timezone.utc),
                    source="web",
                )
            )
            self._active_workflow_runs.add((project_id, run_id))
            self._save_state()

        Thread(
            target=self._execute_run,
            args=(project_id, run_id, requirement_text),
            daemon=True,
        ).start()
        return run_id

    def _execute_run(self, project_id: str, run_id: str, requirement: str) -> None:
        """Background thread: run requirement via ProjectSession."""
        from ..runtime.project_session import ProjectSession

        def on_event(event: dict[str, Any]) -> None:
            """Sync each A2A event to the WorkflowRun in real-time."""
            with self._lock:
                run = self._find_run(project_id, run_id)
                if run is not None:
                    run.task_log.append(event)

        # Resolve project root for file output
        project_root = None
        with self._lock:
            project = self.project_manager.get_project(project_id)
            if project is not None:
                project_root = project.project_root

        try:
            session = ProjectSession(
                self._runtime_manager,
                project_root=project_root,
                on_event=on_event,
            )
            result = session.run(requirement)

            with self._lock:
                run = self._find_run(project_id, run_id)
                if run is not None:
                    run.status = "completed"
                    run.completed_at = datetime.now(timezone.utc)
                    run.result = result
                self._active_workflow_runs.discard((project_id, run_id))
                self._save_state()

            logger.info("Run completed: project=%s run=%s", project_id, run_id)

        except Exception as exc:
            with self._lock:
                run = self._find_run(project_id, run_id)
                if run is not None:
                    run.status = "failed"
                    run.completed_at = datetime.now(timezone.utc)
                    run.error = str(exc)
                self._active_workflow_runs.discard((project_id, run_id))
                self._save_state()
            logger.error("Run failed: project=%s run=%s error=%s", project_id, run_id, exc)

    # -- Monitor -------------------------------------------------------------

    def get_monitor_data(self) -> dict[str, Any]:
        """Return real-time status of agents managed by RuntimeManager."""
        return {
            "agents": self._runtime_manager.get_agents_status(),
            "active_runs": len(self._active_workflow_runs),
        }

    # -- Config management ---------------------------------------------------

    def load_global_config_json(self) -> str:
        with self._lock:
            if self.project_manager._global_config_path.exists():
                payload = self.project_manager._global_config.to_dict()
            else:
                payload = self.project_manager.create_default_project_config("Template").to_dict()
            return json.dumps(payload, indent=2, ensure_ascii=False)

    def get_global_config_data(self) -> dict[str, Any]:
        with self._lock:
            cfg = self.project_manager._global_config
            cfg.ensure_model_catalog_defaults()
            model_options = [{"id": m.id, "default": m.is_default} for m in cfg.models]
            return {
                "development_mode": cfg.development_mode,
                "model_providers": [
                    {"provider": p.provider, "api_key": p.api_key, "base_url": p.base_url, "enabled": p.enabled}
                    for p in cfg.model_providers
                ],
                "models": [
                    {
                        "id": m.id,
                        "name": m.name,
                        "api_model": m.api_model,
                        "default": m.is_default,
                        "default_provider": m.default_provider,
                        "is_local": m.is_local,
                        "providers": list(m.providers),
                        "extra": dict(m.extra),
                    }
                    for m in cfg.models
                ],
                "model_options": model_options,
                "model_catalog": model_options,
                "agent_model_selection": dict(cfg.agent_model_selection),
                "agents": [
                    {
                        "key": name,
                        "name": agent_cfg.name,
                        "enabled": agent_cfg.enabled,
                        "selected_model": cfg.agent_model_selection.get(name, cfg.get_default_model_id()),
                    }
                    for name, agent_cfg in cfg.agents.items()
                ],
                "available_agents": list(cfg.agents.keys()),
                "workspace": {
                    "projects_root": cfg.workspace.projects_root,
                    "artifacts_root": cfg.workspace.artifacts_root,
                    "auto_create_dirs": cfg.workspace.auto_create_dirs,
                },
                "workflow": {
                    "max_review_iterations": cfg.workflow.max_review_iterations,
                    "review_min_rounds": cfg.workflow.review_min_rounds,
                    "review_max_rounds": cfg.workflow.review_max_rounds,
                    "developer_sr_task_retry_attempts": cfg.workflow.developer_sr_task_retry_attempts,
                    "fail_on_review_rejection": cfg.workflow.fail_on_review_rejection,
                },
                "logging": {
                    "level": cfg.logging.level,
                    "log_dir": cfg.logging.log_dir,
                    "json_format": cfg.logging.json_format,
                    "rotate_daily": cfg.logging.rotate_daily,
                },
            }

    def save_global_config_data(
        self,
        *,
        development_mode: str,
        model_catalog: list[dict[str, Any]],
        agent_model_selection: dict[str, str],
    ) -> None:
        with self._lock:
            current = self.project_manager._global_config
            payload = current.to_dict()
            normalized_catalog: list[dict[str, Any]] = []
            default_seen = False
            seen_ids: set[str] = set()
            for item in model_catalog:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id", "")).strip()
                if not model_id or model_id in seen_ids:
                    continue
                seen_ids.add(model_id)
                is_default = bool(item.get("default", False))
                if is_default and not default_seen:
                    default_seen = True
                else:
                    is_default = False
                normalized_catalog.append({"id": model_id, "default": is_default})
            if not normalized_catalog:
                raise ValueError("模型列表不能为空")
            if not default_seen:
                normalized_catalog[0]["default"] = True
            payload["development_mode"] = "github" if development_mode == "github" else "local"
            payload["model_catalog"] = normalized_catalog
            payload["agent_model_selection"] = {
                str(k): str(v).strip() for k, v in agent_model_selection.items() if str(v).strip()
            }
            updated = ProjectConfig.from_dict(payload)
            updated.to_json_file(self.project_manager._global_config_path)
            self.project_manager._global_config = updated

    def save_global_models_data(
        self,
        *,
        model_providers: list[dict[str, Any]] | None = None,
        models: list[dict[str, Any]],
        development_mode: str | None = None,
    ) -> None:
        with self._lock:
            normalized: list[dict[str, Any]] = []
            for item in models:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id", "")).strip()
                if not model_id:
                    continue
                is_local = bool(item.get("is_local", False))
                providers_raw = item.get("providers", [])
                refs = [str(r).strip() for r in providers_raw] if isinstance(providers_raw, list) else []
                refs = [r for r in refs if r]
                if is_local:
                    refs = []
                    default_provider = "local"
                else:
                    if not refs:
                        raise ValueError(f"模型 {model_id} 至少要绑定一个 provider，或标记为本地���型")
                    default_provider = str(item.get("default_provider", refs[0])).strip()
                    if default_provider not in refs:
                        default_provider = refs[0]
                normalized.append(
                    {
                        "id": model_id,
                        "name": str(item.get("name", model_id)).strip() or model_id,
                        "api_model": str(item.get("api_model", model_id)).strip() or model_id,
                        "default": bool(item.get("default", False)),
                        "default_provider": default_provider,
                        "is_local": is_local,
                        "providers": refs,
                        "extra": dict(item.get("extra", {})) if isinstance(item.get("extra"), dict) else {},
                    }
                )
            if normalized and not any(m["default"] for m in normalized):
                normalized[0]["default"] = True
            current = self.project_manager._global_config
            payload = current.to_dict()
            if model_providers is not None:
                payload["model_providers"] = model_providers
            payload["models"] = normalized
            if development_mode is not None:
                payload["development_mode"] = "github" if development_mode == "github" else "local"
            updated = ProjectConfig.from_dict(payload)
            updated.to_json_file(self.project_manager._global_config_path)
            self.project_manager._global_config = updated

    def save_global_agents_data(self, *, agents: list[dict[str, Any]], agent_model_selection: dict[str, str]) -> None:
        with self._lock:
            current = self.project_manager._global_config
            payload = current.to_dict()
            agents_payload = payload.get("agents", {})
            if not isinstance(agents_payload, dict):
                agents_payload = {}
            for item in agents:
                if not isinstance(item, dict):
                    continue
                key = str(item.get("key", "")).strip()
                if not key or key not in agents_payload:
                    continue
                agent_data = agents_payload[key]
                if isinstance(agent_data, dict):
                    agent_data["name"] = str(item.get("name", key))
                    agent_data["enabled"] = bool(item.get("enabled", True))
            payload["agents"] = agents_payload
            payload["agent_model_selection"] = {
                str(k): str(v).strip() for k, v in agent_model_selection.items() if str(v).strip()
            }
            updated = ProjectConfig.from_dict(payload)
            updated.to_json_file(self.project_manager._global_config_path)
            self.project_manager._global_config = updated

    def save_global_workspace_data(self, workspace: dict[str, Any]) -> None:
        with self._lock:
            payload = self.project_manager._global_config.to_dict()
            payload["workspace"] = workspace
            updated = ProjectConfig.from_dict(payload)
            updated.to_json_file(self.project_manager._global_config_path)
            self.project_manager._global_config = updated

    def save_global_logging_data(self, logging_cfg: dict[str, Any]) -> None:
        with self._lock:
            payload = self.project_manager._global_config.to_dict()
            payload["logging"] = logging_cfg
            updated = ProjectConfig.from_dict(payload)
            updated.to_json_file(self.project_manager._global_config_path)
            self.project_manager._global_config = updated

    def save_global_workflow_data(self, workflow_cfg: dict[str, Any]) -> None:
        with self._lock:
            payload = self.project_manager._global_config.to_dict()
            payload["workflow"] = workflow_cfg
            updated = ProjectConfig.from_dict(payload)
            updated.to_json_file(self.project_manager._global_config_path)
            self.project_manager._global_config = updated

    def save_global_config_json(self, text: str) -> None:
        with self._lock:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("Global config JSON must be an object")
            config = ProjectConfig.from_dict(parsed)
            config.to_json_file(self.project_manager._global_config_path)
            self.project_manager._global_config = config

    # -- Internal helpers ----------------------------------------------------

    def _find_run(self, project_id: str, run_id: str) -> WorkflowRun | None:
        for run in self._runs_by_project.get(project_id, []):
            if run.run_id == run_id:
                return run
        return None

    def _list_requirement_history(self, project_id: str) -> list[RequirementEntry]:
        items = self._requirements_by_project.get(project_id, [])
        return sorted(items, key=lambda item: item.created_at, reverse=True)

    def _restore_projects_from_disk(self) -> None:
        root = self.project_manager._projects_root
        root.mkdir(parents=True, exist_ok=True)
        max_counter = -1
        for project_dir in root.iterdir():
            if not project_dir.is_dir():
                continue
            config_path = project_dir / "project_config.json"
            if not config_path.exists():
                continue
            project_id = project_dir.name.split("-", 1)[0]
            if not project_id.startswith("project_"):
                continue
            try:
                config = ProjectConfig.from_json_file(config_path)
                project = Project(
                    project_id=project_id,
                    config=config,
                    project_root=str(project_dir),
                )
                self.project_manager._projects[project_id] = project
                counter = int(project_id.split("_", 1)[1])
                max_counter = max(max_counter, counter)
            except Exception:
                continue
        self.project_manager._project_counter = max_counter + 1 if max_counter >= 0 else 0

    def _load_state(self) -> None:
        if not self._state_path.exists():
            return
        try:
            data = json.loads(self._state_path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to load web state: %s", exc)
            return
        if not isinstance(data, dict):
            return

        reaped_any = False
        runs_data = data.get("runs_by_project", {})
        if isinstance(runs_data, dict):
            for project_id, runs in runs_data.items():
                if not isinstance(runs, list):
                    continue
                self._runs_by_project[project_id] = []
                for item in runs:
                    if not isinstance(item, dict):
                        continue
                    try:
                        started = datetime.fromisoformat(str(item.get("started_at", "")))
                    except Exception:
                        started = datetime.now(timezone.utc)
                    completed: datetime | None = None
                    completed_at = item.get("completed_at")
                    if isinstance(completed_at, str) and completed_at:
                        try:
                            completed = datetime.fromisoformat(completed_at)
                        except Exception:
                            pass
                    raw_status = str(item.get("status", "completed"))
                    raw_error = str(item.get("error", ""))
                    # Reap zombie runs: any run stored as pending/running when
                    # this process starts has no live worker thread (we never
                    # persist _active_workflow_runs). Without this, the
                    # run-detail UI polls forever and the dashboard keeps the
                    # project in a misleading in-progress state. Mark them as
                    # ``failed`` with a clear "interrupted" message so the UI
                    # reaches a terminal state and the user can decide whether
                    # to re-run.
                    if raw_status in ("pending", "running"):
                        logger.warning(
                            "Reaping zombie run: project=%s run=%s prior_status=%s",
                            project_id,
                            str(item.get("run_id", "")),
                            raw_status,
                        )
                        raw_status = "failed"
                        raw_error = raw_error or (
                            "interrupted: web server restarted while this run "
                            "was in progress; no worker thread remained to "
                            "advance it. Re-run to retry."
                        )
                        if completed is None:
                            completed = datetime.now(timezone.utc)
                        reaped_any = True
                    self._runs_by_project[project_id].append(
                        WorkflowRun(
                            run_id=str(item.get("run_id", "")),
                            requirement_text=str(item.get("requirement_text", "")),
                            started_at=started,
                            status=raw_status,
                            completed_at=completed,
                            error=raw_error,
                            result=str(item.get("result", "")),
                            task_log=list(item.get("task_log", [])),
                        )
                    )

        req_data = data.get("requirements_by_project", {})
        if isinstance(req_data, dict):
            for project_id, reqs in req_data.items():
                if not isinstance(reqs, list):
                    continue
                self._requirements_by_project[project_id] = []
                for item in reqs:
                    if not isinstance(item, dict):
                        continue
                    try:
                        created = datetime.fromisoformat(str(item.get("created_at", "")))
                    except Exception:
                        created = datetime.now(timezone.utc)
                    self._requirements_by_project[project_id].append(
                        RequirementEntry(
                            requirement_id=str(item.get("requirement_id", "")),
                            text=str(item.get("text", "")),
                            created_at=created,
                            source=str(item.get("source", "web")),
                        )
                    )

        project_statuses = data.get("project_statuses", {})
        if isinstance(project_statuses, dict):
            for project_id, info in project_statuses.items():
                project = self.project_manager.get_project(project_id)
                if project is None or not isinstance(info, dict):
                    continue
                try:
                    project.status = ProjectStatus(str(info.get("status", "active")))
                except Exception:
                    pass
                try:
                    if isinstance(info.get("created_at"), str):
                        project.created_at = datetime.fromisoformat(info["created_at"])
                    if isinstance(info.get("updated_at"), str):
                        project.updated_at = datetime.fromisoformat(info["updated_at"])
                except Exception:
                    pass

        # Persist the reaped statuses so the next restart sees clean state
        # instead of re-reaping the same runs.
        if reaped_any:
            try:
                self._save_state()
            except Exception as exc:
                logger.debug("Failed to persist reaped state: %s", exc)

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "runs_by_project": {
                pid: [self._serialize_run(r) for r in runs] for pid, runs in self._runs_by_project.items()
            },
            "requirements_by_project": {
                pid: [self._serialize_requirement(r) for r in reqs]
                for pid, reqs in self._requirements_by_project.items()
            },
            "project_statuses": {
                p.project_id: {
                    "status": p.status.value,
                    "created_at": p.created_at.isoformat(),
                    "updated_at": p.updated_at.isoformat(),
                }
                for p in self.project_manager.list_projects()
            },
        }
        tmp_path = self._state_path.with_suffix(f"{self._state_path.suffix}.{uuid.uuid4().hex}.tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self._state_path)

    @staticmethod
    def _serialize_run(run: WorkflowRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "requirement_text": run.requirement_text,
            "started_at": run.started_at.isoformat(),
            "status": run.status,
            "completed_at": run.completed_at.isoformat() if run.completed_at else None,
            "error": run.error,
            "result": run.result,
            "task_log": run.task_log,
        }

    @staticmethod
    def _serialize_requirement(item: RequirementEntry) -> dict[str, Any]:
        return {
            "requirement_id": item.requirement_id,
            "text": item.text,
            "created_at": item.created_at.isoformat(),
            "source": item.source,
        }


# -- OAuth helper ------------------------------------------------------------


def _build_oauth() -> Any | None:
    if OAuth is None:
        return None
    oauth = OAuth()
    if os.environ.get("GOOGLE_CLIENT_ID"):
        oauth.register(
            name="google",
            client_id=os.environ.get("GOOGLE_CLIENT_ID"),
            client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            client_kwargs={"scope": "openid email profile"},
        )
    if os.environ.get("MICROSOFT_CLIENT_ID"):
        oauth.register(
            name="microsoft",
            client_id=os.environ.get("MICROSOFT_CLIENT_ID"),
            client_secret=os.environ.get("MICROSOFT_CLIENT_SECRET"),
            server_metadata_url="https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration",
            client_kwargs={"scope": "openid profile email User.Read"},
        )
    return oauth


def _template_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    """Create the AISE web app."""
    _LOCALHOST_AUTO_USER: dict[str, Any] = {
        "id": "local-auto",
        "name": "Local User",
        "email": "local@aise.local",
        "provider": "local",
        "role": "super_admin",
        "permissions": ["super_admin", "rd_director"],
    }
    _AUTH_PUBLIC_PATHS = {"/login", "/auth/local-login", "/auth/dev-login", "/api/health"}

    class _LocalhostAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if not path.startswith("/static"):
                host = (request.headers.get("host") or "").split(":")[0].strip().lower()
                is_local = host in {"127.0.0.1", "localhost", "::1"}
                if is_local and not request.session.get("user"):
                    request.session["user"] = _LOCALHOST_AUTO_USER
                elif (
                    not is_local
                    and not request.session.get("user")
                    and not path.startswith("/auth/")
                    and path not in _AUTH_PUBLIC_PATHS
                    and not path.startswith("/api/")
                ):
                    return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
            return await call_next(request)

    app = FastAPI(title="AISE Web Console")
    app.add_middleware(_LocalhostAuthMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(32))
    app.mount("/static", StaticFiles(directory=_static_dir()), name="static")
    templates = Jinja2Templates(directory=str(_template_dir()))
    service = WebProjectService()
    app.state.web_service = service
    oauth = _build_oauth()
    dev_login_enabled = os.environ.get("AISE_WEB_ENABLE_DEV_LOGIN", "").lower() in {"1", "true", "yes"}
    local_admin_username = os.environ.get("AISE_ADMIN_USERNAME", "admin")
    local_admin_password = os.environ.get("AISE_ADMIN_PASSWORD", "123456")

    def require_login(request: Request) -> dict[str, Any]:
        user = request.session.get("user")
        if not user:
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Login required")
        return user

    # -- Page routes ---------------------------------------------------------

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        user = request.session.get("user")
        if not user:
            return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"projects": service.list_projects(), "global_config_data": service.get_global_config_data(), "user": user},
        )

    @app.get("/monitor", response_class=HTMLResponse)
    async def monitor_page(request: Request) -> HTMLResponse:
        user = request.session.get("user")
        if not user:
            return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
        return templates.TemplateResponse(
            request,
            "monitor.html",
            {"monitor_data": service.get_monitor_data(), "user": user},
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, error: str | None = None) -> HTMLResponse:
        user = request.session.get("user")
        configured = {
            "google": bool(os.environ.get("GOOGLE_CLIENT_ID")),
            "microsoft": bool(os.environ.get("MICROSOFT_CLIENT_ID")),
            "oauth_enabled": oauth is not None,
            "dev_login_enabled": dev_login_enabled,
        }
        return templates.TemplateResponse(
            request,
            "login.html",
            {"user": user, "configured": configured, "error": error, "local_admin_username": local_admin_username},
        )

    # -- Auth routes ---------------------------------------------------------

    @app.post("/auth/local-login")
    async def local_login(request: Request, username: str = Form(...), password: str = Form(...)):
        if username.strip() != local_admin_username or password != local_admin_password:
            return RedirectResponse(url="/login?error=用户名或���码错误", status_code=HTTP_303_SEE_OTHER)
        request.session["user"] = {
            "id": "local-admin",
            "name": "System Admin",
            "email": "admin@aise.local",
            "provider": "local",
            "role": "super_admin",
            "permissions": ["super_admin", "rd_director"],
        }
        return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)

    @app.get("/auth/dev-login")
    async def dev_login(request: Request, name: str = "Dev User", email: str = "dev@aise.local"):
        if not dev_login_enabled:
            raise HTTPException(status_code=404, detail="Not found")
        request.session["user"] = {
            "id": "dev-user",
            "name": name,
            "email": email,
            "provider": "dev",
            "role": "super_admin",
            "permissions": ["super_admin", "rd_director"],
        }
        return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)

    @app.get("/auth/{provider}")
    async def auth_login(request: Request, provider: str):
        if oauth is None:
            raise HTTPException(status_code=500, detail="OAuth dependency not installed")
        if provider not in {"google", "microsoft"}:
            raise HTTPException(status_code=404, detail="Provider not supported")
        client = oauth.create_client(provider)
        if client is None:
            raise HTTPException(status_code=500, detail="OAuth client not configured")
        redirect_uri = request.url_for("auth_callback", provider=provider)
        return await client.authorize_redirect(request, redirect_uri)

    @app.get("/auth/{provider}/callback")
    async def auth_callback(request: Request, provider: str):
        if oauth is None:
            raise HTTPException(status_code=500, detail="OAuth dependency not installed")
        client = oauth.create_client(provider)
        if client is None:
            raise HTTPException(status_code=500, detail="OAuth client not configured")
        token = await client.authorize_access_token(request)
        userinfo = token.get("userinfo")
        if not userinfo:
            userinfo = {}
            if provider == "microsoft":
                resp = await client.get("https://graph.microsoft.com/v1.0/me", token=token)
                if resp.is_success:
                    g = resp.json()
                    userinfo = {
                        "sub": g.get("id", ""),
                        "name": g.get("displayName", ""),
                        "email": g.get("mail") or g.get("userPrincipalName", ""),
                    }
        request.session["user"] = {
            "id": userinfo.get("sub", ""),
            "name": userinfo.get("name", "User"),
            "email": userinfo.get("email", ""),
            "provider": provider,
            "role": "user",
            "permissions": [],
        }
        return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)

    @app.get("/logout")
    async def logout(request: Request):
        request.session.clear()
        return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)

    # -- Project page routes -------------------------------------------------

    @app.post("/projects")
    async def create_project(request: Request, project_name: str = Form(...), development_mode: str = Form("local")):
        require_login(request)
        form_data = await request.form()
        initial_requirement = str(form_data.get("initial_requirement", ""))
        agent_models: dict[str, str] = {}
        for key, value in form_data.multi_items():
            if key.startswith("agent_model_"):
                agent_models[key.replace("agent_model_", "", 1)] = str(value)
        try:
            project_id, run_id = service.create_project_with_initial_run(
                project_name=project_name.strip(),
                development_mode=development_mode,
                agent_models=agent_models,
                initial_requirement=initial_requirement,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if run_id:
            return RedirectResponse(url=f"/projects/{project_id}/runs/{run_id}", status_code=HTTP_303_SEE_OTHER)
        return RedirectResponse(url=f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    async def project_detail(request: Request, project_id: str) -> HTMLResponse:
        user = require_login(request)
        payload = service.get_project(project_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return templates.TemplateResponse(request, "project_detail.html", {"project": payload, "user": user})

    @app.post("/projects/{project_id}/requirements")
    async def add_requirement(request: Request, project_id: str, requirement_text: str = Form(...)):
        require_login(request)
        try:
            run_id = service.run_requirement(project_id, requirement_text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url=f"/projects/{project_id}/runs/{run_id}", status_code=HTTP_303_SEE_OTHER)

    @app.get("/projects/{project_id}/runs/{run_id}", response_class=HTMLResponse)
    async def workflow_run_detail(request: Request, project_id: str, run_id: str):
        user = require_login(request)
        project = service.get_project(project_id)
        run = service.get_run(project_id, run_id)
        if project is None or run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return templates.TemplateResponse(request, "run_detail.html", {"project": project, "run": run, "user": user})

    # -- Config page routes --------------------------------------------------

    @app.get("/config/global")
    async def global_config_index() -> RedirectResponse:
        return RedirectResponse(url="/config/global/models", status_code=HTTP_303_SEE_OTHER)

    @app.get("/config/global/{section}", response_class=HTMLResponse)
    async def global_config_page(request: Request, section: str) -> HTMLResponse:
        user = require_login(request)
        section = section.lower()
        if section not in {"models", "agents", "workspace", "workflow", "logging", "json"}:
            raise HTTPException(status_code=404, detail="Config section not found")
        return templates.TemplateResponse(
            request,
            "global_config.html",
            {
                "config_json": service.load_global_config_json(),
                "config_data": service.get_global_config_data(),
                "user": user,
                "error": None,
                "section": section,
            },
        )

    @app.post("/config/global/{section}", response_class=HTMLResponse)
    async def update_global_config_section(request: Request, section: str) -> HTMLResponse:
        user = require_login(request)
        error = None
        section = section.lower()
        form = await request.form()
        try:
            if section == "json":
                service.save_global_config_json(str(form.get("config_json", "")))
            elif section == "models":
                providers = json.loads(str(form.get("providers_json", "[]")))
                models = json.loads(str(form.get("models_json", "[]")))
                service.save_global_models_data(
                    model_providers=providers,
                    models=models,
                    development_mode=str(form.get("development_mode", "local")),
                )
            elif section == "agents":
                config_data = service.get_global_config_data()
                agent_items: list[dict[str, Any]] = []
                selections: dict[str, str] = {}
                for item in config_data["agents"]:
                    key = str(item["key"])
                    agent_items.append(
                        {
                            "key": key,
                            "name": str(form.get(f"agent_name_{key}", key)),
                            "enabled": str(form.get(f"agent_enabled_{key}", "")) == "on",
                        }
                    )
                    selections[key] = str(form.get(f"agent_model_{key}", "")).strip()
                service.save_global_agents_data(
                    agents=agent_items,
                    agent_model_selection=selections,
                )
            elif section == "workspace":
                service.save_global_workspace_data(
                    {
                        "projects_root": str(form.get("projects_root", "projects")),
                        "artifacts_root": str(form.get("artifacts_root", "artifacts")),
                        "auto_create_dirs": str(form.get("auto_create_dirs", "")) == "on",
                    }
                )
            elif section == "workflow":
                service.save_global_workflow_data(
                    {
                        "max_review_iterations": int(str(form.get("max_review_iterations", "3")) or 3),
                        "review_min_rounds": int(str(form.get("review_min_rounds", "2")) or 2),
                        "review_max_rounds": int(str(form.get("review_max_rounds", "3")) or 3),
                        "developer_sr_task_retry_attempts": int(
                            str(form.get("developer_sr_task_retry_attempts", "2")) or 2
                        ),
                        "fail_on_review_rejection": str(form.get("fail_on_review_rejection", "")) == "on",
                    }
                )
            elif section == "logging":
                service.save_global_logging_data(
                    {
                        "level": str(form.get("level", "INFO")),
                        "log_dir": str(form.get("log_dir", "logs")),
                        "json_format": str(form.get("json_format", "")) == "on",
                        "rotate_daily": str(form.get("rotate_daily", "")) == "on",
                    }
                )
        except Exception as exc:
            error = str(exc)
        return templates.TemplateResponse(
            request,
            "global_config.html",
            {
                "config_json": service.load_global_config_json(),
                "config_data": service.get_global_config_data(),
                "user": user,
                "error": error,
                "section": section,
            },
        )

    # -- API routes ----------------------------------------------------------

    @app.get("/api/health")
    async def api_health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/monitor")
    async def api_monitor(request: Request) -> dict[str, Any]:
        require_login(request)
        return service.get_monitor_data()

    @app.get("/api/projects")
    async def api_list_projects(request: Request) -> dict[str, Any]:
        require_login(request)
        return {"projects": service.list_projects()}

    @app.post("/api/projects")
    async def api_create_project(request: Request) -> dict[str, Any]:
        require_login(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        try:
            project_id, run_id = service.create_project_with_initial_run(
                project_name=str(payload.get("project_name", "")).strip(),
                development_mode=str(payload.get("development_mode", "local")),
                agent_models={str(k): str(v) for k, v in (payload.get("agent_models") or {}).items()},
                initial_requirement=str(payload.get("initial_requirement", "")),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"project_id": project_id, "run_id": run_id}

    @app.get("/api/projects/{project_id}")
    async def api_get_project(request: Request, project_id: str) -> dict[str, Any]:
        require_login(request)
        project = service.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

    @app.delete("/api/projects/{project_id}")
    async def api_delete_project(request: Request, project_id: str) -> dict[str, Any]:
        require_login(request)
        try:
            service.delete_project(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True, "project_id": project_id}

    @app.post("/api/projects/{project_id}/restart")
    async def api_restart_project(request: Request, project_id: str) -> dict[str, Any]:
        require_login(request)
        try:
            run_id = service.restart_project(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"restarted": True, "project_id": project_id, "run_id": run_id}

    @app.get("/api/projects/{project_id}/requirements")
    async def api_get_requirements(request: Request, project_id: str) -> dict[str, Any]:
        require_login(request)
        project = service.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"requirements": project["requirements"]}

    @app.post("/api/projects/{project_id}/requirements")
    async def api_add_requirement(request: Request, project_id: str) -> dict[str, Any]:
        require_login(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        try:
            run_id = service.run_requirement(project_id, str(payload.get("requirement_text", "")))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"run_id": run_id}

    @app.get("/api/projects/{project_id}/runs")
    async def api_get_runs(request: Request, project_id: str) -> dict[str, Any]:
        require_login(request)
        project = service.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"runs": project["runs"]}

    @app.get("/api/projects/{project_id}/runs/{run_id}")
    async def api_get_run(request: Request, project_id: str, run_id: str) -> dict[str, Any]:
        require_login(request)
        run = service.get_run(project_id, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return run

    @app.get("/api/config/global")
    async def api_get_global_config(request: Request) -> dict[str, Any]:
        require_login(request)
        return {"config_json": service.load_global_config_json()}

    @app.post("/api/config/global")
    async def api_set_global_config(request: Request) -> dict[str, Any]:
        require_login(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        try:
            service.save_global_config_json(str(payload.get("config_json", "")))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"saved": True}

    @app.get("/api/config/global/data")
    async def api_get_global_config_data(request: Request) -> dict[str, Any]:
        require_login(request)
        return service.get_global_config_data()

    @app.post("/api/config/global/data")
    async def api_set_global_config_data(request: Request) -> dict[str, Any]:
        require_login(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        try:
            if "models" in payload:
                service.save_global_models_data(
                    model_providers=payload.get("model_providers"),
                    models=payload.get("models", []),
                    development_mode=str(payload.get("development_mode", "local")),
                )
            if "agents" in payload or "agent_model_selection" in payload:
                service.save_global_agents_data(
                    agents=payload.get("agents", []),
                    agent_model_selection={str(k): str(v) for k, v in payload.get("agent_model_selection", {}).items()},
                )
            if "workspace" in payload:
                service.save_global_workspace_data(payload["workspace"])
            if "logging" in payload:
                service.save_global_logging_data(payload["logging"])
            if "workflow" in payload:
                service.save_global_workflow_data(payload["workflow"])
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"saved": True}

    return app
