"""FastAPI web system for project management."""

from __future__ import annotations

import json
import os
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER, HTTP_401_UNAUTHORIZED

from ..config import ProjectConfig
from ..core.artifact import Artifact, ArtifactType
from ..core.project import Project, ProjectStatus
from ..core.project_manager import ProjectManager
from ..core.workflow import WorkflowEngine
from ..main import create_team
from ..utils.logging import configure_logging, get_logger

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
    phase_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RequirementEntry:
    """Represents one requirement dispatch entry."""

    requirement_id: str
    text: str
    created_at: datetime
    source: str = "web"


class WebProjectService:
    """Coordinates project operations used by the web layer."""

    def __init__(self) -> None:
        self.project_manager = ProjectManager()
        configure_logging(self.project_manager._global_config.logging, force=True)
        self._runs_by_project: dict[str, list[WorkflowRun]] = {}
        self._requirements_by_project: dict[str, list[RequirementEntry]] = {}
        self._lock = RLock()
        self._state_path = self.project_manager._projects_root / "web_state.json"
        self._restore_projects_from_disk()
        self._load_state()
        logger.info("WebProjectService initialized: state_path=%s", self._state_path)

    def list_projects(self) -> list[dict[str, Any]]:
        with self._lock:
            infos = self.project_manager.get_all_projects_info()
            infos.sort(key=lambda item: item["updated_at"], reverse=True)
            logger.debug("Web list_projects: count=%d", len(infos))
            return infos

    def create_project(
        self,
        project_name: str,
        development_mode: str,
        agent_models: dict[str, str] | None = None,
        initial_requirement: str = "",
    ) -> str:
        if not project_name.strip():
            raise ValueError("Project name cannot be empty")
        logger.info("Web create_project requested: name=%s mode=%s", project_name, development_mode)
        mode = "github" if development_mode == "github" else "local"
        config = self.project_manager.create_default_project_config(project_name)
        config.development_mode = mode
        if agent_models:
            for agent_name, model_id in agent_models.items():
                normalized = str(model_id).strip()
                if normalized:
                    config.agent_model_selection[agent_name] = normalized
                    if agent_name in config.agents:
                        config.agents[agent_name].model = config.resolve_model_id(normalized)
        with self._lock:
            project_id = self.project_manager.create_project(project_name, config)
            self._runs_by_project.setdefault(project_id, [])
            self._requirements_by_project.setdefault(project_id, [])
            self._save_state()
            initial_text = initial_requirement.strip()
            if initial_text:
                self.run_requirement(project_id, initial_text)
            logger.info("Web create_project completed: project_id=%s", project_id)
            return project_id

    def get_project(self, project_id: str) -> dict[str, Any] | None:
        with self._lock:
            project = self.project_manager.get_project(project_id)
            if project is None:
                return None

            default_workflow = WorkflowEngine.create_default_workflow()
            workflow_nodes = [
                {
                    "name": phase.name,
                    "tasks": [f"{task.agent}.{task.skill}" for task in phase.tasks],
                    "review_gate": (
                        f"{phase.review_gate.reviewer_agent}.{phase.review_gate.review_skill}"
                        if phase.review_gate
                        else None
                    ),
                }
                for phase in default_workflow.phases
            ]
            history = self._runs_by_project.get(project_id, [])
            return {
                "info": project.get_info(),
                "workflow_nodes": workflow_nodes,
                "runs": [self._serialize_run(run) for run in history],
                "requirements": [
                    self._serialize_requirement(item) for item in self._list_requirement_history(project_id)
                ],
            }

    def get_run(self, project_id: str, run_id: str) -> dict[str, Any] | None:
        with self._lock:
            for run in self._runs_by_project.get(project_id, []):
                if run.run_id == run_id:
                    return self._serialize_run(run)
        return None

    def run_requirement(self, project_id: str, requirement_text: str) -> str:
        with self._lock:
            project = self.project_manager.get_project(project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found")

            requirement = requirement_text.strip()
            if not requirement:
                raise ValueError("Requirement text cannot be empty")
            logger.info(
                "Web requirement dispatch: project_id=%s text_len=%d",
                project_id,
                len(requirement),
            )

            requirement_entry = RequirementEntry(
                requirement_id=uuid.uuid4().hex[:10],
                text=requirement,
                created_at=datetime.now(timezone.utc),
            )
            self._requirements_by_project.setdefault(project_id, []).append(requirement_entry)

            requirement_artifact = Artifact(
                artifact_type=ArtifactType.REQUIREMENTS,
                content={"raw_requirements": requirement},
                producer="web_user",
                metadata={"source": "web", "project_id": project_id},
            )
            project.orchestrator.artifact_store.store(requirement_artifact)

            run_id = uuid.uuid4().hex[:10]
            results = self.project_manager.run_project_workflow(
                project_id,
                {"raw_requirements": requirement},
            )
            run = WorkflowRun(
                run_id=run_id,
                requirement_text=requirement,
                started_at=datetime.now(timezone.utc),
                phase_results=results,
            )
            self._runs_by_project.setdefault(project_id, []).append(run)
            if project.project_root:
                runs_dir = Path(project.project_root) / "runs"
                runs_dir.mkdir(parents=True, exist_ok=True)
                run_path = runs_dir / f"{run_id}.json"
                run_path.write_text(
                    json.dumps(self._serialize_run(run), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            self._save_state()
            logger.info("Web requirement completed: project_id=%s run_id=%s", project_id, run_id)
            return run_id

    def load_global_config_json(self) -> str:
        with self._lock:
            if self.project_manager._global_config_path.exists():
                payload = self.project_manager._global_config.to_dict()
            else:
                payload = self.project_manager.create_default_project_config("Template").to_dict()
            return json.dumps(payload, indent=2, ensure_ascii=False)

    def get_global_config_data(self) -> dict[str, Any]:
        """Return structured global config data for friendly UI."""
        with self._lock:
            cfg = self.project_manager._global_config
            cfg.ensure_model_catalog_defaults()
            model_options = [{"id": m.id, "default": m.is_default} for m in cfg.models]
            return {
                "development_mode": cfg.development_mode,
                "model_providers": [
                    {
                        "provider": p.provider,
                        "api_key": p.api_key,
                        "base_url": p.base_url,
                        "enabled": p.enabled,
                    }
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
        """Save global config from friendly UI payload."""
        with self._lock:
            current = self.project_manager._global_config
            payload = current.to_dict()

            normalized_mode = "github" if development_mode == "github" else "local"
            normalized_catalog: list[dict[str, Any]] = []
            default_seen = False
            seen_ids: set[str] = set()
            for item in model_catalog:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id", "")).strip()
                if not model_id:
                    continue
                if model_id in seen_ids:
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

            normalized_selection = {
                str(agent): str(model_id).strip()
                for agent, model_id in agent_model_selection.items()
                if str(model_id).strip()
            }

            payload["development_mode"] = normalized_mode
            payload["model_catalog"] = normalized_catalog
            payload["agent_model_selection"] = normalized_selection

            updated = ProjectConfig.from_dict(payload)
            for agent_name, model_id in normalized_selection.items():
                if agent_name in updated.agents:
                    updated.agents[agent_name].model = updated.resolve_model_id(model_id)

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
            normalized_models: list[dict[str, Any]] = []
            for item in models:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id", "")).strip()
                if not model_id:
                    continue
                is_local = bool(item.get("is_local", False))
                model_name = str(item.get("name", model_id)).strip() or model_id
                api_model = str(item.get("api_model", model_id)).strip() or model_id
                refs_raw = item.get("providers", [])
                refs = [str(ref).strip() for ref in refs_raw] if isinstance(refs_raw, list) else []
                refs = [ref for ref in refs if ref]
                if is_local:
                    refs = []
                    default_provider = "local"
                else:
                    if not refs:
                        raise ValueError(f"模型 {model_id} 至少要绑定一个 provider，或标记为本地模型")
                    default_provider = str(item.get("default_provider", refs[0] if refs else "")).strip()
                    if default_provider not in refs:
                        default_provider = refs[0]
                normalized_models.append(
                    {
                        "id": model_id,
                        "name": model_name,
                        "api_model": api_model,
                        "default": bool(item.get("default", False)),
                        "default_provider": default_provider,
                        "is_local": is_local,
                        "providers": refs,
                        "extra": dict(item.get("extra", {})) if isinstance(item.get("extra", {}), dict) else {},
                    }
                )
            if normalized_models and not any(item["default"] for item in normalized_models):
                normalized_models[0]["default"] = True

            current = self.project_manager._global_config
            payload = current.to_dict()
            if model_providers is not None:
                payload["model_providers"] = model_providers
            payload["models"] = normalized_models
            if development_mode is not None:
                payload["development_mode"] = "github" if development_mode == "github" else "local"
            updated = ProjectConfig.from_dict(payload)
            updated.to_json_file(self.project_manager._global_config_path)
            self.project_manager._global_config = updated

    def save_global_agents_data(
        self,
        *,
        agents: list[dict[str, Any]],
        agent_model_selection: dict[str, str],
    ) -> None:
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
                if not isinstance(agent_data, dict):
                    continue
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

    def save_global_config_json(self, text: str) -> None:
        with self._lock:
            parsed = json.loads(text)
            if not isinstance(parsed, dict):
                raise ValueError("Global config JSON must be an object")
            config = ProjectConfig.from_dict(parsed)
            config.to_json_file(self.project_manager._global_config_path)
            self.project_manager._global_config = config

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
                orchestrator = create_team(config)
                project = Project(
                    project_id=project_id,
                    config=config,
                    orchestrator=orchestrator,
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
        except Exception:
            return
        if not isinstance(data, dict):
            return

        runs_data = data.get("runs_by_project", {})
        if isinstance(runs_data, dict):
            for project_id, runs in runs_data.items():
                if not isinstance(runs, list):
                    continue
                self._runs_by_project[project_id] = []
                for item in runs:
                    if not isinstance(item, dict):
                        continue
                    started_at = item.get("started_at")
                    try:
                        started = datetime.fromisoformat(str(started_at))
                    except Exception:
                        started = datetime.now(timezone.utc)
                    self._runs_by_project[project_id].append(
                        WorkflowRun(
                            run_id=str(item.get("run_id", "")),
                            requirement_text=str(item.get("requirement_text", "")),
                            started_at=started,
                            phase_results=list(item.get("phase_results", [])),
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
                    created_at = item.get("created_at")
                    try:
                        created = datetime.fromisoformat(str(created_at))
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
                status = str(info.get("status", "active"))
                try:
                    project.status = ProjectStatus(status)
                except Exception:
                    pass
                created_at = info.get("created_at")
                updated_at = info.get("updated_at")
                try:
                    if isinstance(created_at, str):
                        project.created_at = datetime.fromisoformat(created_at)
                    if isinstance(updated_at, str):
                        project.updated_at = datetime.fromisoformat(updated_at)
                except Exception:
                    pass

    def _save_state(self) -> None:
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "runs_by_project": {
                project_id: [self._serialize_run(run) for run in runs]
                for project_id, runs in self._runs_by_project.items()
            },
            "requirements_by_project": {
                project_id: [self._serialize_requirement(req) for req in reqs]
                for project_id, reqs in self._requirements_by_project.items()
            },
            "project_statuses": {
                project.project_id: {
                    "status": project.status.value,
                    "created_at": project.created_at.isoformat(),
                    "updated_at": project.updated_at.isoformat(),
                }
                for project in self.project_manager.list_projects()
            },
        }
        self._state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def _serialize_run(run: WorkflowRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "requirement_text": run.requirement_text,
            "started_at": run.started_at.isoformat(),
            "phase_results": run.phase_results,
        }

    @staticmethod
    def _serialize_requirement(item: RequirementEntry) -> dict[str, Any]:
        return {
            "requirement_id": item.requirement_id,
            "text": item.text,
            "created_at": item.created_at.isoformat(),
            "source": item.source,
        }


def _build_oauth() -> OAuth | None:
    if OAuth is None:
        return None

    oauth = OAuth()
    oauth.register(
        name="google",
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_id=os.environ.get("GOOGLE_CLIENT_ID", ""),
        client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", ""),
        client_kwargs={"scope": "openid email profile"},
    )
    oauth.register(
        name="microsoft",
        server_metadata_url=("https://login.microsoftonline.com/common/v2.0/.well-known/openid-configuration"),
        client_id=os.environ.get("MICROSOFT_CLIENT_ID", ""),
        client_secret=os.environ.get("MICROSOFT_CLIENT_SECRET", ""),
        client_kwargs={"scope": "openid profile email User.Read"},
    )
    return oauth


def _template_dir() -> Path:
    return Path(__file__).resolve().parent / "templates"


def _static_dir() -> Path:
    return Path(__file__).resolve().parent / "static"


def create_app() -> FastAPI:
    """Create the AISE web app."""
    app = FastAPI(title="AISE Web Console")
    app.add_middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(32))
    app.mount("/static", StaticFiles(directory=_static_dir()), name="static")
    templates = Jinja2Templates(directory=str(_template_dir()))
    service = WebProjectService()
    app.state.web_service = service
    oauth = _build_oauth()
    dev_login_enabled = os.environ.get("AISE_WEB_ENABLE_DEV_LOGIN", "").lower() in {"1", "true", "yes"}
    local_admin_username = os.environ.get("AISE_ADMIN_USERNAME", "admin")
    local_admin_password = os.environ.get("AISE_ADMIN_PASSWORD", "123456")

    @app.middleware("http")
    async def log_request_response(request: Request, call_next):
        request_id = uuid.uuid4().hex[:10]
        logger.info(
            "HTTP request: request_id=%s method=%s path=%s",
            request_id,
            request.method,
            request.url.path,
        )
        try:
            response = await call_next(request)
        except Exception:
            logger.exception("HTTP request failed: request_id=%s path=%s", request_id, request.url.path)
            raise
        logger.info(
            "HTTP response: request_id=%s status=%s path=%s",
            request_id,
            response.status_code,
            request.url.path,
        )
        return response

    def require_login(request: Request) -> dict[str, Any]:
        user = request.session.get("user")
        if not user:
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Login required")
        return user

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        user = request.session.get("user")
        if not user:
            return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": request,
                "projects": service.list_projects(),
                "global_config_data": service.get_global_config_data(),
                "user": user,
            },
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
            "login.html",
            {
                "request": request,
                "user": user,
                "configured": configured,
                "error": error,
                "local_admin_username": local_admin_username,
            },
        )

    @app.post("/auth/local-login")
    async def local_login(
        request: Request,
        username: str = Form(...),
        password: str = Form(...),
    ):
        if username.strip() != local_admin_username or password != local_admin_password:
            return RedirectResponse(url="/login?error=用户名或密码错误", status_code=HTTP_303_SEE_OTHER)
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
        if provider == "google" and not os.environ.get("GOOGLE_CLIENT_ID"):
            raise HTTPException(status_code=500, detail="GOOGLE_CLIENT_ID is not configured")
        if provider == "microsoft" and not os.environ.get("MICROSOFT_CLIENT_ID"):
            raise HTTPException(status_code=500, detail="MICROSOFT_CLIENT_ID is not configured")
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
                    graph_data = resp.json()
                    userinfo = {
                        "sub": graph_data.get("id", ""),
                        "name": graph_data.get("displayName", ""),
                        "email": graph_data.get("mail") or graph_data.get("userPrincipalName", ""),
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

    @app.post("/projects")
    async def create_project(
        request: Request,
        project_name: str = Form(...),
        development_mode: str = Form("local"),
    ):
        require_login(request)
        form_data = await request.form()
        initial_requirement = str(form_data.get("initial_requirement", ""))
        agent_models: dict[str, str] = {}
        for key, value in form_data.multi_items():
            if key.startswith("agent_model_"):
                agent_name = key.replace("agent_model_", "", 1)
                agent_models[agent_name] = str(value)
        try:
            project_id = service.create_project(
                project_name.strip(),
                development_mode,
                agent_models,
                initial_requirement=initial_requirement,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(url=f"/projects/{project_id}", status_code=HTTP_303_SEE_OTHER)

    @app.get("/projects/{project_id}", response_class=HTMLResponse)
    async def project_detail(request: Request, project_id: str) -> HTMLResponse:
        user = require_login(request)
        payload = service.get_project(project_id)
        if payload is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return templates.TemplateResponse(
            "project_detail.html",
            {"request": request, "project": payload, "user": user},
        )

    @app.post("/projects/{project_id}/requirements")
    async def add_requirement(
        request: Request,
        project_id: str,
        requirement_text: str = Form(...),
    ):
        require_login(request)
        try:
            run_id = service.run_requirement(project_id, requirement_text)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return RedirectResponse(
            url=f"/projects/{project_id}/runs/{run_id}",
            status_code=HTTP_303_SEE_OTHER,
        )

    @app.get("/projects/{project_id}/runs/{run_id}", response_class=HTMLResponse)
    async def workflow_run_detail(request: Request, project_id: str, run_id: str):
        user = require_login(request)
        project = service.get_project(project_id)
        run = service.get_run(project_id, run_id)
        if project is None or run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return templates.TemplateResponse(
            "run_detail.html",
            {"request": request, "project": project, "run": run, "user": user},
        )

    @app.get(
        "/projects/{project_id}/runs/{run_id}/phases/{phase_idx}/tasks/{task_key}",
        response_class=HTMLResponse,
    )
    async def task_detail(
        request: Request,
        project_id: str,
        run_id: str,
        phase_idx: int,
        task_key: str,
    ):
        user = require_login(request)
        run = service.get_run(project_id, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        phases = run.get("phase_results", [])
        if phase_idx < 0 or phase_idx >= len(phases):
            raise HTTPException(status_code=404, detail="Phase not found")
        phase = phases[phase_idx]
        task = phase.get("tasks", {}).get(task_key)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return templates.TemplateResponse(
            "task_detail.html",
            {
                "request": request,
                "project_id": project_id,
                "run_id": run_id,
                "phase_idx": phase_idx,
                "phase_name": phase.get("phase", ""),
                "task_key": task_key,
                "task": task,
                "user": user,
            },
        )

    @app.get("/config/global")
    async def global_config_index() -> RedirectResponse:
        return RedirectResponse(url="/config/global/models", status_code=HTTP_303_SEE_OTHER)

    @app.get("/config/global/{section}", response_class=HTMLResponse)
    async def global_config_page(request: Request, section: str) -> HTMLResponse:
        user = require_login(request)
        section = section.lower()
        if section not in {"models", "agents", "workspace", "logging", "json"}:
            raise HTTPException(status_code=404, detail="Config section not found")
        return templates.TemplateResponse(
            "global_config.html",
            {
                "request": request,
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
                development_mode = str(form.get("development_mode", "local"))
                providers_json = str(form.get("providers_json", "[]"))
                models_json = str(form.get("models_json", "[]"))
                provider_items = json.loads(providers_json)
                models = json.loads(models_json)
                if not isinstance(provider_items, list):
                    raise ValueError("providers_json must be a list")
                if not isinstance(models, list):
                    raise ValueError("models_json must be a list")
                service.save_global_models_data(
                    model_providers=provider_items,
                    models=models,
                    development_mode=development_mode,
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
                service.save_global_agents_data(agents=agent_items, agent_model_selection=selections)
            elif section == "workspace":
                service.save_global_workspace_data(
                    {
                        "projects_root": str(form.get("projects_root", "projects")),
                        "artifacts_root": str(form.get("artifacts_root", "artifacts")),
                        "auto_create_dirs": str(form.get("auto_create_dirs", "")) == "on",
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
            else:
                raise ValueError("Unsupported section")
        except Exception as exc:
            error = str(exc)

        return templates.TemplateResponse(
            "global_config.html",
            {
                "request": request,
                "config_json": service.load_global_config_json(),
                "config_data": service.get_global_config_data(),
                "user": user,
                "error": error,
                "section": section,
            },
        )

    @app.get("/api/health")
    async def api_health() -> dict[str, str]:
        return {"status": "ok"}

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
        project_name = str(payload.get("project_name", "")).strip()
        development_mode = str(payload.get("development_mode", "local"))
        initial_requirement = str(payload.get("initial_requirement", ""))
        agent_models = payload.get("agent_models", {})
        if not isinstance(agent_models, dict):
            agent_models = {}
        try:
            project_id = service.create_project(
                project_name,
                development_mode,
                {str(k): str(v) for k, v in agent_models.items()},
                initial_requirement=initial_requirement,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"project_id": project_id}

    @app.get("/api/projects/{project_id}")
    async def api_get_project(request: Request, project_id: str) -> dict[str, Any]:
        require_login(request)
        project = service.get_project(project_id)
        if project is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return project

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
        requirement_text = str(payload.get("requirement_text", ""))
        try:
            run_id = service.run_requirement(project_id, requirement_text)
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

    @app.get("/api/projects/{project_id}/runs/{run_id}/phases/{phase_idx}/tasks/{task_key}")
    async def api_get_task(
        request: Request,
        project_id: str,
        run_id: str,
        phase_idx: int,
        task_key: str,
    ) -> dict[str, Any]:
        require_login(request)
        run = service.get_run(project_id, run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="Run not found")
        phases = run.get("phase_results", [])
        if phase_idx < 0 or phase_idx >= len(phases):
            raise HTTPException(status_code=404, detail="Phase not found")
        task = phases[phase_idx].get("tasks", {}).get(task_key)
        if task is None:
            raise HTTPException(status_code=404, detail="Task not found")
        return task

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
        config_json = str(payload.get("config_json", ""))
        try:
            service.save_global_config_json(config_json)
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
                models = payload.get("models", [])
                model_providers = payload.get("model_providers", None)
                if not isinstance(models, list):
                    raise HTTPException(status_code=400, detail="models must be a list")
                if model_providers is not None and not isinstance(model_providers, list):
                    raise HTTPException(status_code=400, detail="model_providers must be a list")
                service.save_global_models_data(
                    model_providers=model_providers,
                    models=models,
                    development_mode=str(payload.get("development_mode", "local")),
                )
            if "agents" in payload or "agent_model_selection" in payload:
                agents = payload.get("agents", [])
                selection = payload.get("agent_model_selection", {})
                if not isinstance(agents, list):
                    raise HTTPException(status_code=400, detail="agents must be a list")
                if not isinstance(selection, dict):
                    raise HTTPException(status_code=400, detail="agent_model_selection must be an object")
                service.save_global_agents_data(
                    agents=agents,
                    agent_model_selection={str(k): str(v) for k, v in selection.items()},
                )
            if "workspace" in payload:
                workspace = payload.get("workspace", {})
                if not isinstance(workspace, dict):
                    raise HTTPException(status_code=400, detail="workspace must be an object")
                service.save_global_workspace_data(workspace)
            if "logging" in payload:
                logging_cfg = payload.get("logging", {})
                if not isinstance(logging_cfg, dict):
                    raise HTTPException(status_code=400, detail="logging must be an object")
                service.save_global_logging_data(logging_cfg)
            if not {"models", "agents", "agent_model_selection", "workspace", "logging"} & set(payload.keys()):
                # backward compatibility
                development_mode = str(payload.get("development_mode", "local"))
                model_catalog = payload.get("model_catalog", [])
                selection = payload.get("agent_model_selection", {})
                if not isinstance(model_catalog, list):
                    raise HTTPException(status_code=400, detail="model_catalog must be a list")
                if not isinstance(selection, dict):
                    raise HTTPException(status_code=400, detail="agent_model_selection must be an object")
                service.save_global_config_data(
                    development_mode=development_mode,
                    model_catalog=model_catalog,
                    agent_model_selection={str(k): str(v) for k, v in selection.items()},
                )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"saved": True}

    return app
