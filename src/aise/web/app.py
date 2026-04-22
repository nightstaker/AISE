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
from ..runtime.project_manager import ProjectManager
from ..utils.logging import configure_logging, configure_module_file_logger, get_logger
from .i18n import make_translator
from .log_service import LogService
from .user_store import (
    PERM_ANALYZE_LOGS,
    PERM_MANAGE_PROJECTS,
    PERM_MANAGE_SYSTEM,
    PERM_MANAGE_USERS,
    PERM_RUN_PROJECTS,
    PERM_VIEW_LOGS,
    UserStore,
    has_permission,
    session_payload,
)

try:
    from authlib.integrations.starlette_client import OAuth
except Exception:  # pragma: no cover - optional dependency
    OAuth = None

logger = get_logger(__name__)


@dataclass
class WorkflowRun:
    """Represents one workflow execution for a requirement.

    ``mode`` distinguishes the kind of run:
    - ``"initial"`` — first requirement against a fresh project; the
      orchestrator runs the full waterfall from a clean slate.
    - ``"incremental"`` — a subsequent requirement against a project
      that already has prior completed runs. The orchestrator reads
      existing artifacts first and only adds / updates what the new
      requirement demands, while still running the full test suite.
    """

    run_id: str
    requirement_text: str
    started_at: datetime
    status: str = "pending"
    completed_at: datetime | None = None
    error: str = ""
    result: str = ""
    task_log: list[dict[str, Any]] = field(default_factory=list)
    mode: str = "initial"
    process_type: str = "waterfall"
    # Phase-level metadata populated by the session's phase_start /
    # phase_complete events and surfaced to the UI so a failed run
    # can be retried from the phase that broke. ``failed_phase_idx``
    # is -1 when the run never reached a phase (e.g. crashed during
    # session setup) or completed cleanly.
    failed_phase_idx: int = -1
    failed_phase_name: str = ""
    phase_total: int = 0
    # Link to the run this one was retried / restarted from. ``""`` for
    # original submissions. Lets the UI show a "retry of run_xxx" hint
    # and lets the user walk the retry chain backwards.
    resumed_from_run_id: str = ""
    start_phase_idx: int = 0


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
        self._users_path = self.project_manager._projects_root / "users.json"
        self._user_store = UserStore(self._users_path)
        self._log_service = LogService(self.project_manager._global_config.logging.log_dir)
        self._restore_projects_from_disk()
        self._load_state()

        from ..runtime.manager import RuntimeManager

        self._runtime_manager = RuntimeManager(config=self.project_manager._global_config)
        self._runtime_manager.start()
        self._log_service.set_runtime_manager(self._runtime_manager)

        logger.info("WebProjectService initialized: state_path=%s", self._state_path)

    @property
    def user_store(self) -> UserStore:
        return self._user_store

    @property
    def log_service(self) -> LogService:
        return self._log_service

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
        process_type: str = "waterfall",
    ) -> str:
        project_id, _ = self.create_project_with_initial_run(
            project_name=project_name,
            development_mode=development_mode,
            agent_models=agent_models,
            initial_requirement=initial_requirement,
            process_type=process_type,
        )
        return project_id

    def create_project_with_initial_run(
        self,
        *,
        project_name: str,
        development_mode: str,
        agent_models: dict[str, str] | None = None,
        initial_requirement: str = "",
        process_type: str = "waterfall",
    ) -> tuple[str, str | None]:
        """Create a project and (optionally) its first workflow run.

        AI-First scaffolding flow: the call returns immediately with a
        project_id. Directory layout + ``git init`` + ``.gitignore``
        happen asynchronously, driven by the product-manager agent.
        The project sits in :pyattr:`ProjectStatus.SCAFFOLDING` until
        the background thread flips it to ``ACTIVE`` (success) or
        ``SCAFFOLDING_FAILED`` (reported by the agent).

        If ``initial_requirement`` is provided, it is stashed and
        dispatched once scaffolding completes — the client still sees
        a single create-and-run call; the asynchrony is hidden behind
        the run's ``pending`` status.
        """
        if not project_name.strip():
            raise ValueError("Project name cannot be empty")
        mode = "github" if development_mode == "github" else "local"
        raw_process = str(process_type or "waterfall").strip().lower()
        process = raw_process if raw_process in ("waterfall", "agile") else "waterfall"
        config = self.project_manager.create_default_project_config(project_name)
        config.development_mode = mode
        config.process_type = process
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
            logger.info(
                "Web create_project scheduled scaffolding: project_id=%s initial_req=%s",
                project_id,
                bool(initial_requirement.strip()),
            )

        # Background scaffolding — outside the lock so polling requests
        # (``list_projects``, ``get_project``) can see SCAFFOLDING while
        # the agent works.
        Thread(
            target=self._scaffold_project,
            args=(project_id, initial_requirement.strip()),
            daemon=True,
            name=f"scaffold-{project_id}",
        ).start()

        return project_id, None

    # -- Async scaffolding ---------------------------------------------------

    def _scaffold_project(self, project_id: str, initial_requirement: str) -> None:
        """Dispatch the product-manager agent to scaffold the project.

        Runs in a background thread. The prompt asks the agent to
        create the standard subdirs, initialize git (with a seeded
        ``.gitignore``), and commit the root scaffold. Success → flip
        status to ACTIVE and, if an ``initial_requirement`` was
        supplied, kick off the first workflow run. Failure → flip
        status to SCAFFOLDING_FAILED and let the safety-net module
        (PR-c) decide whether to repair or surface to the user.
        """
        with self._lock:
            project = self.project_manager.get_project(project_id)
        if project is None:
            logger.warning("Scaffold thread: project %s vanished before start", project_id)
            return

        try:
            prompt = self._build_scaffolding_prompt(project)
            self._dispatch_scaffolding_to_pm(project, prompt)
        except Exception as exc:  # pragma: no cover — defensive
            logger.exception("Scaffold thread raised: project=%s", project_id)
            with self._lock:
                project.fail_scaffolding(f"scaffolding dispatch raised: {exc}")
                self._save_state()
            return

        # Post-dispatch invariant check. The agent's happy-path answer
        # is "I did it", but the filesystem is the source of truth.
        # These checks are minimal — PR-c's safety net broadens them
        # into a plan-driven verifier.
        root = Path(project.project_root or "")
        ok = root.is_dir() and (root / ".git").exists() and (root / ".gitignore").exists()
        with self._lock:
            if ok:
                project.finish_scaffolding()
                logger.info("Scaffold completed: project_id=%s root=%s", project_id, root)
            else:
                project.fail_scaffolding("post-dispatch invariants failed: .git / .gitignore missing")
                logger.warning(
                    "Scaffold invariants failed: project_id=%s .git=%s .gitignore=%s",
                    project_id,
                    (root / ".git").exists(),
                    (root / ".gitignore").exists(),
                )
            self._save_state()

        # Fire the deferred initial run only if scaffolding landed in ACTIVE.
        if initial_requirement and project.status == ProjectStatus.ACTIVE:
            try:
                self.run_requirement(project_id, initial_requirement)
            except Exception:
                logger.exception("Deferred initial run failed: project_id=%s", project_id)

    @staticmethod
    def _build_scaffolding_prompt(project: Project) -> str:
        """Compose the one-shot scaffolding task for the PM agent.

        Kept terse: the ``git`` skill (inlined into the PM's system
        prompt via its ``## Skills`` block) carries the command
        reference. This prompt only says *what* to do and where.
        """
        root = project.project_root or ""
        return (
            f"SCAFFOLDING TASK for project ``{project.project_name}`` at ``{root}``.\n\n"
            "Prepare the project environment so subsequent phases can run:\n"
            "1. Create the standard subdirectories under the project root: "
            "``docs/``, ``src/``, ``tests/``, ``scripts/``, ``config/``, "
            "``artifacts/``, ``trace/``.\n"
            "2. Initialize the project root as a git repository "
            "(``git init``) and seed ``.gitignore`` with the baseline "
            "entries from the ``git`` skill.\n"
            "3. Stage and commit the scaffold with subject "
            "``project_manager(scaffold): initialize project layout``.\n\n"
            "Perform the filesystem / git operations directly via the tools "
            "available to you. Do NOT draft any documentation in this task — "
            "that happens in later phases. Respond with a one-line summary "
            "of what you created."
        )

    def _dispatch_scaffolding_to_pm(self, project: Project, prompt: str) -> None:
        """Resolve the PM runtime and send it the scaffolding prompt.

        Kept separate so tests can monkeypatch it with a stub without
        touching the runtime manager plumbing. The real implementation
        uses the already-started ``RuntimeManager`` to pick up the
        ``product_manager`` agent, then calls ``handle_message`` with
        a project-scoped thread id so the scaffold conversation stays
        isolated from workflow dispatches.
        """
        pm_runtime = self._runtime_manager.get_runtime("product_manager")
        if pm_runtime is None:
            raise RuntimeError("product_manager runtime not found in RuntimeManager")
        thread_id = f"scaffold-{project.project_id}"
        pm_runtime.handle_message(prompt, thread_id=thread_id)

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

    # -- Failed-run recovery -------------------------------------------------

    def retry_run(self, project_id: str, run_id: str) -> str:
        """Resume a failed run from the phase that broke.

        Creates a NEW run (with its own run_id and fresh task_log) that
        shares the project root, requirement text, mode, and
        process_type of the failed run. The new session starts at the
        failed run's ``failed_phase_idx``; earlier phases are skipped
        entirely. Artifacts written by earlier phases (docs/, src/,
        tests/) stay on disk so the resumed session can read them.
        """
        return self._spawn_derived_run(project_id, run_id, reset_to_zero=False)

    def restart_run(self, project_id: str, run_id: str) -> str:
        """Re-run the SAME requirement from phase 0.

        Unlike :meth:`restart_project` which also wipes history and
        filesystem state, this keeps all prior runs visible and only
        re-submits THIS run's requirement from the beginning. New
        agents will see the existing docs/ / src/ / tests/ from
        earlier attempts and either overwrite or extend them.
        """
        return self._spawn_derived_run(project_id, run_id, reset_to_zero=True)

    def _spawn_derived_run(self, project_id: str, run_id: str, *, reset_to_zero: bool) -> str:
        """Shared retry / restart implementation.

        ``reset_to_zero=True`` forces start_phase_idx=0 (restart);
        ``False`` uses the failed phase index so the retry picks up
        where the failure happened.
        """
        with self._lock:
            project = self.project_manager.get_project(project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found")
            source = self._find_run(project_id, run_id)
            if source is None:
                raise ValueError(f"Run {run_id} not found")
            if source.status in ("pending", "running"):
                raise ValueError(f"Run {run_id} is still {source.status}; wait for it to finish before retrying.")
            start_phase_idx = 0
            if not reset_to_zero:
                if source.failed_phase_idx >= 0:
                    start_phase_idx = int(source.failed_phase_idx)
                else:
                    # Retry requested on a run that never emitted a
                    # phase_start (pre-phase crash) — fall back to 0
                    # so the user gets a clean re-run rather than a
                    # confusing no-op.
                    start_phase_idx = 0
            new_run_id = f"run_{uuid.uuid4().hex[:10]}"
            new_run = WorkflowRun(
                run_id=new_run_id,
                requirement_text=source.requirement_text,
                started_at=datetime.now(timezone.utc),
                status="running",
                mode=source.mode,
                process_type=source.process_type,
                phase_total=source.phase_total,
                resumed_from_run_id=source.run_id,
                start_phase_idx=start_phase_idx,
            )
            self._runs_by_project.setdefault(project_id, []).append(new_run)
            self._active_workflow_runs.add((project_id, new_run_id))
            self._save_state()

        Thread(
            target=self._execute_run,
            args=(
                project_id,
                new_run_id,
                source.requirement_text,
                source.mode,
                source.process_type,
                start_phase_idx,
            ),
            daemon=True,
        ).start()
        logger.info(
            "Derived run dispatched: parent=%s new=%s start_phase_idx=%d (%s)",
            run_id,
            new_run_id,
            start_phase_idx,
            "restart" if reset_to_zero else "retry",
        )
        return new_run_id

    # -- Requirement execution via ProjectSession ----------------------------

    def run_requirement(self, project_id: str, requirement_text: str) -> str:
        """Submit requirement and execute workflow via ProjectSession.

        Run mode (``initial`` vs ``incremental``) is decided here based
        on whether the project already has at least one prior COMPLETED
        run with a non-empty result. That guarantees the incremental
        path only kicks in once there's a real baseline to build on —
        a project whose first attempt failed stays in ``initial`` mode
        so the next submission re-runs the full waterfall cleanly.
        """
        with self._lock:
            project = self.project_manager.get_project(project_id)
            if project is None:
                raise ValueError(f"Project {project_id} not found")
            # Reject submissions while the project's environment is
            # still being prepared. The UI blocks the button during
            # ``scaffolding``, but a stale tab (or a direct API call)
            # could still land here — fail loud rather than racing
            # the scaffold thread.
            if project.status == ProjectStatus.SCAFFOLDING:
                raise ValueError(f"Project {project_id} is still scaffolding — retry once the status flips to 'active'")
            if project.status == ProjectStatus.SCAFFOLDING_FAILED:
                raise ValueError(
                    f"Project {project_id} failed to scaffold: {project.scaffolding_error or 'unknown error'}"
                )
            prior_runs = self._runs_by_project.get(project_id, [])
            has_baseline = any(r.status == "completed" and (r.result or "").strip() for r in prior_runs)
            mode = "incremental" if has_baseline else "initial"
            process_type = getattr(project.config, "process_type", "waterfall") or "waterfall"
            if process_type not in ("waterfall", "agile"):
                process_type = "waterfall"
            run_id = f"run_{uuid.uuid4().hex[:10]}"
            run = WorkflowRun(
                run_id=run_id,
                requirement_text=requirement_text,
                started_at=datetime.now(timezone.utc),
                status="running",
                mode=mode,
                process_type=process_type,
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
            args=(project_id, run_id, requirement_text, mode, process_type, 0),
            daemon=True,
        ).start()
        return run_id

    def _execute_run(
        self,
        project_id: str,
        run_id: str,
        requirement: str,
        mode: str = "initial",
        process_type: str = "waterfall",
        start_phase_idx: int = 0,
    ) -> None:
        """Background thread: run requirement via ProjectSession."""
        from ..runtime.project_session import ProjectSession

        def on_event(event: dict[str, Any]) -> None:
            """Sync each A2A event to the WorkflowRun in real-time.

            The phase_plan / phase_start / phase_complete events are
            also mirrored onto run-level fields so the dashboard and
            retry API don't have to re-walk the log.
            """
            with self._lock:
                run = self._find_run(project_id, run_id)
                if run is None:
                    return
                run.task_log.append(event)
                event_type = event.get("type")
                if event_type == "phase_plan":
                    try:
                        run.phase_total = int(event.get("total") or 0)
                    except (TypeError, ValueError):
                        pass
                elif event_type == "phase_start":
                    try:
                        run.failed_phase_idx = int(event.get("phase_idx"))
                    except (TypeError, ValueError):
                        run.failed_phase_idx = -1
                    run.failed_phase_name = str(event.get("phase_name", ""))
                elif event_type == "phase_complete":
                    # Phase cleared — if the next phase_start arrives we'll
                    # overwrite these; if the session ends cleanly, the
                    # final status=completed branch resets them anyway.
                    run.failed_phase_idx = -1
                    run.failed_phase_name = ""

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
                mode=mode,
                process_type=process_type,
                start_phase_idx=start_phase_idx,
            )
            result = session.run(requirement)

            # Silent-failure guard. ``ProjectSession._invoke_pm`` swallows
            # LLM backend exceptions and returns "" so the phase loop can
            # still iterate — that makes the session resilient but also
            # lets a whole run end without producing anything when the
            # backend dies mid-flight. Treat an empty / whitespace-only
            # result as a failure instead of a "completed" run with no
            # output, so the retry / restart controls surface correctly.
            # ``workflow_state.final_report`` is the authoritative signal
            # that ``mark_complete`` was called; if it's set we trust the
            # session. Otherwise require a non-trivial result string.
            completed_ok = bool(session.workflow_state.is_complete) or bool((result or "").strip())
            if not completed_ok:
                # Surface phase context so the retry picks up where it died.
                with self._lock:
                    run = self._find_run(project_id, run_id)
                    if run is not None:
                        run.status = "failed"
                        run.completed_at = datetime.now(timezone.utc)
                        run.error = (
                            "Workflow ended without producing a delivery report. "
                            "The LLM backend likely dropped mid-run; check Logs for the "
                            "underlying task_response errors."
                        )
                    self._active_workflow_runs.discard((project_id, run_id))
                    self._save_state()
                logger.warning(
                    "Run marked failed (silent): project=%s run=%s (no mark_complete, empty result)",
                    project_id,
                    run_id,
                )
                return

            with self._lock:
                run = self._find_run(project_id, run_id)
                if run is not None:
                    run.status = "completed"
                    run.completed_at = datetime.now(timezone.utc)
                    run.result = result
                    run.failed_phase_idx = -1
                    run.failed_phase_name = ""
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

    def get_ui_language(self) -> str:
        """Return the currently configured UI language (``zh`` or ``en``).

        Used by the Jinja template layer to seed ``window.__AISE_LANG``
        on every page so the frontend's ``t()`` helper can route each
        string to the right translation.
        """
        with self._lock:
            lang = (self.project_manager._global_config.ui_language or "zh").strip().lower()
            return lang if lang in ("zh", "en") else "zh"

    def get_global_config_data(self) -> dict[str, Any]:
        with self._lock:
            cfg = self.project_manager._global_config
            cfg.ensure_model_catalog_defaults()
            model_options = [{"id": m.id, "default": m.is_default} for m in cfg.models]
            return {
                "development_mode": cfg.development_mode,
                "ui_language": cfg.ui_language,
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

    def save_global_workspace_data(
        self,
        workspace: dict[str, Any],
        *,
        ui_language: str | None = None,
    ) -> None:
        with self._lock:
            payload = self.project_manager._global_config.to_dict()
            payload["workspace"] = workspace
            if ui_language is not None:
                payload["ui_language"] = ui_language
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
                    # Silent-failure migration: older runs recorded
                    # ``completed`` whenever ``session.run()`` returned
                    # without raising, even if the result was empty and
                    # the orchestrator never hit ``mark_complete``. The
                    # forward fix lives in ``_execute_run``; here we
                    # reclassify persisted records so the retry / restart
                    # UI becomes available on historical silent failures.
                    raw_result = str(item.get("result", ""))
                    if raw_status == "completed" and not raw_result.strip():
                        logger.info(
                            "Reclassifying silent-failure run as failed: project=%s run=%s (empty result)",
                            project_id,
                            str(item.get("run_id", "")),
                        )
                        raw_status = "failed"
                        raw_error = raw_error or (
                            "silent failure: the workflow ended without producing a "
                            "delivery report. Earlier code treated this as completed; "
                            "it has been reclassified so retry / restart are available."
                        )
                        reaped_any = True
                    raw_mode = str(item.get("mode", "initial")).strip().lower()
                    if raw_mode not in ("initial", "incremental"):
                        raw_mode = "initial"
                    raw_process = str(item.get("process_type", "waterfall")).strip().lower()
                    if raw_process not in ("waterfall", "agile"):
                        raw_process = "waterfall"
                    failed_idx_raw = item.get("failed_phase_idx", -1)
                    try:
                        failed_idx = int(failed_idx_raw)
                    except (TypeError, ValueError):
                        failed_idx = -1
                    total_raw = item.get("phase_total", 0)
                    try:
                        phase_total_val = int(total_raw)
                    except (TypeError, ValueError):
                        phase_total_val = 0
                    start_idx_raw = item.get("start_phase_idx", 0)
                    try:
                        start_idx_val = int(start_idx_raw)
                    except (TypeError, ValueError):
                        start_idx_val = 0
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
                            mode=raw_mode,
                            process_type=raw_process,
                            failed_phase_idx=failed_idx,
                            failed_phase_name=str(item.get("failed_phase_name", "")),
                            phase_total=phase_total_val,
                            resumed_from_run_id=str(item.get("resumed_from_run_id", "")),
                            start_phase_idx=max(0, start_idx_val),
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
            "mode": run.mode,
            "process_type": run.process_type,
            "failed_phase_idx": run.failed_phase_idx,
            "failed_phase_name": run.failed_phase_name,
            "phase_total": run.phase_total,
            "resumed_from_run_id": run.resumed_from_run_id,
            "start_phase_idx": run.start_phase_idx,
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
    # Localhost auto-login no longer injects a synthetic user. Instead it
    # signs in as the bootstrapped super_admin from the UserStore so
    # every action is attributed to a real user record.
    _AUTH_PUBLIC_PATHS = {"/login", "/auth/local-login", "/auth/dev-login", "/api/health"}

    app = FastAPI(title="AISE Web Console")

    def _refresh_session_user(request: Request, user_dict: dict[str, Any] | None) -> dict[str, Any] | None:
        """Re-hydrate the session user from the store (role may have changed).

        Keeps the session object fresh so a user whose role was changed
        by an admin picks up new permissions on their next request
        without needing a re-login.
        """
        if not user_dict:
            return None
        user_id = str(user_dict.get("id", ""))
        if not user_id:
            return user_dict
        stored = service.user_store.get_user(user_id)
        if stored is None:
            # Stored record deleted — force re-login.
            request.session.clear()
            return None
        if not stored.enabled:
            request.session.clear()
            return None
        payload = session_payload(stored)
        if payload != user_dict:
            request.session["user"] = payload
        return payload

    class _LocalhostAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            path = request.url.path
            if path.startswith("/static"):
                return await call_next(request)
            host = (request.headers.get("host") or "").split(":")[0].strip().lower()
            is_local = host in {"127.0.0.1", "localhost", "::1"}
            current = request.session.get("user")
            if is_local and not current:
                # Pick the first enabled super_admin as the auto-user.
                for candidate in service.user_store.list_users():
                    if candidate.role == "super_admin" and candidate.enabled:
                        request.session["user"] = session_payload(candidate)
                        current = request.session["user"]
                        break
            if current:
                _refresh_session_user(request, current)
            if (
                not is_local
                and not request.session.get("user")
                and not path.startswith("/auth/")
                and path not in _AUTH_PUBLIC_PATHS
                and not path.startswith("/api/")
            ):
                return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
            return await call_next(request)

    app.add_middleware(_LocalhostAuthMiddleware)
    app.add_middleware(SessionMiddleware, secret_key=secrets.token_urlsafe(32))
    app.mount("/static", StaticFiles(directory=_static_dir()), name="static")
    templates = Jinja2Templates(directory=str(_template_dir()))
    service = WebProjectService()
    app.state.web_service = service
    # Expose ``ui_language`` to every template via a Jinja global so
    # ``layout.html`` (shared by all pages) can seed
    # ``window.__AISE_LANG`` without every route having to plumb it
    # through the context dict.
    templates.env.globals["get_ui_language"] = service.get_ui_language
    # Server-side ``t(key, default=None, **params)`` backed by the same
    # locale JSON the client-side i18next uses. Registered as a Jinja
    # global so ``layout.html`` / ``global_config.html`` / any other
    # server-rendered template can localize strings without a page
    # reload dance.
    templates.env.globals["t"] = make_translator(service.get_ui_language)
    oauth = _build_oauth()
    dev_login_enabled = os.environ.get("AISE_WEB_ENABLE_DEV_LOGIN", "").lower() in {"1", "true", "yes"}
    local_admin_username = os.environ.get("AISE_ADMIN_USERNAME", "admin")

    def require_login(request: Request) -> dict[str, Any]:
        user = request.session.get("user")
        if not user:
            raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail="Login required")
        return user

    def require_permission(request: Request, permission: str) -> dict[str, Any]:
        user = require_login(request)
        if not has_permission(user, permission):
            raise HTTPException(status_code=403, detail=f"Permission denied: {permission}")
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
        user = service.user_store.authenticate(username, password)
        if user is None:
            return RedirectResponse(url="/login?error=用户名或密码错误", status_code=HTTP_303_SEE_OTHER)
        request.session["user"] = session_payload(user)
        return RedirectResponse(url="/", status_code=HTTP_303_SEE_OTHER)

    @app.get("/auth/dev-login")
    async def dev_login(request: Request, name: str = "Dev User", email: str = "dev@aise.local"):
        if not dev_login_enabled:
            raise HTTPException(status_code=404, detail="Not found")
        user = service.user_store.record_external_login(
            provider="dev",
            external_id=email,
            email=email,
            display_name=name,
        )
        # Dev login always grants super_admin so developers can poke every
        # page without a two-step "create user, promote" dance.
        try:
            service.user_store.update_user(user.id, role="super_admin")
        except Exception as exc:
            logger.warning("Failed to elevate dev user to super_admin: %s", exc)
        user = service.user_store.get_user(user.id) or user
        request.session["user"] = session_payload(user)
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
        user = service.user_store.record_external_login(
            provider=provider,
            external_id=str(userinfo.get("sub", "")),
            email=str(userinfo.get("email", "")),
            display_name=str(userinfo.get("name", "") or userinfo.get("email", "") or "User"),
        )
        if not user.enabled:
            return RedirectResponse(url="/login?error=账户已禁用，联系管理员", status_code=HTTP_303_SEE_OTHER)
        request.session["user"] = session_payload(user)
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
        process_type = str(form_data.get("process_type", "waterfall"))
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
                process_type=process_type,
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
                raw_lang = str(form.get("ui_language", "")).strip().lower()
                ui_language = raw_lang if raw_lang in ("zh", "en") else None
                service.save_global_workspace_data(
                    {
                        "projects_root": str(form.get("projects_root", "projects")),
                        "artifacts_root": str(form.get("artifacts_root", "artifacts")),
                        "auto_create_dirs": str(form.get("auto_create_dirs", "")) == "on",
                    },
                    ui_language=ui_language,
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
        require_permission(request, PERM_MANAGE_PROJECTS)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        try:
            project_id, run_id = service.create_project_with_initial_run(
                project_name=str(payload.get("project_name", "")).strip(),
                development_mode=str(payload.get("development_mode", "local")),
                agent_models={str(k): str(v) for k, v in (payload.get("agent_models") or {}).items()},
                initial_requirement=str(payload.get("initial_requirement", "")),
                process_type=str(payload.get("process_type", "waterfall")),
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
        require_permission(request, PERM_MANAGE_PROJECTS)
        try:
            service.delete_project(project_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"deleted": True, "project_id": project_id}

    @app.post("/api/projects/{project_id}/restart")
    async def api_restart_project(request: Request, project_id: str) -> dict[str, Any]:
        require_permission(request, PERM_RUN_PROJECTS)
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
        require_permission(request, PERM_RUN_PROJECTS)
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

    @app.post("/api/projects/{project_id}/runs/{run_id}/retry")
    async def api_retry_run(request: Request, project_id: str, run_id: str) -> dict[str, Any]:
        require_permission(request, PERM_RUN_PROJECTS)
        try:
            new_run_id = service.retry_run(project_id, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"retried": True, "project_id": project_id, "run_id": new_run_id, "parent_run_id": run_id}

    @app.post("/api/projects/{project_id}/runs/{run_id}/restart")
    async def api_restart_run(request: Request, project_id: str, run_id: str) -> dict[str, Any]:
        require_permission(request, PERM_RUN_PROJECTS)
        try:
            new_run_id = service.restart_run(project_id, run_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"restarted": True, "project_id": project_id, "run_id": new_run_id, "parent_run_id": run_id}

    @app.get("/api/config/global")
    async def api_get_global_config(request: Request) -> dict[str, Any]:
        require_login(request)
        return {"config_json": service.load_global_config_json()}

    @app.post("/api/config/global")
    async def api_set_global_config(request: Request) -> dict[str, Any]:
        require_permission(request, PERM_MANAGE_SYSTEM)
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
        require_permission(request, PERM_MANAGE_SYSTEM)
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

    # -- User management pages + API ----------------------------------------

    @app.get("/users", response_class=HTMLResponse)
    async def users_page(request: Request) -> HTMLResponse:
        user = require_login(request)
        if not has_permission(user, PERM_MANAGE_USERS):
            raise HTTPException(status_code=403, detail="Permission denied")
        return templates.TemplateResponse(
            request,
            "users.html",
            {"user": user},
        )

    @app.get("/api/users/me")
    async def api_current_user(request: Request) -> dict[str, Any]:
        user = require_login(request)
        return {"user": user}

    @app.get("/api/users")
    async def api_list_users(request: Request) -> dict[str, Any]:
        require_permission(request, PERM_MANAGE_USERS)
        users = [u.to_dict() for u in service.user_store.list_users()]
        return {"users": users, "roles": service.user_store.list_role_definitions()}

    @app.get("/api/roles")
    async def api_list_roles(request: Request) -> dict[str, Any]:
        require_login(request)
        return {
            "roles": service.user_store.list_role_definitions(),
            "permissions": service.user_store.list_all_permissions(),
        }

    @app.post("/api/users")
    async def api_create_user(request: Request) -> dict[str, Any]:
        require_permission(request, PERM_MANAGE_USERS)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        try:
            user = service.user_store.create_user(
                username=str(payload.get("username", "")),
                email=str(payload.get("email", "")),
                display_name=str(payload.get("display_name", "")),
                role=str(payload.get("role", "viewer")),
                password=str(payload.get("password", "")),
                enabled=bool(payload.get("enabled", True)),
                provider=str(payload.get("provider", "local")),
                notes=str(payload.get("notes", "")),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"user": user.to_dict()}

    @app.put("/api/users/{user_id}")
    async def api_update_user(request: Request, user_id: str) -> dict[str, Any]:
        require_permission(request, PERM_MANAGE_USERS)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        kwargs: dict[str, Any] = {}
        for key in ("email", "display_name", "role", "notes"):
            if key in payload:
                kwargs[key] = str(payload[key]) if payload[key] is not None else ""
        if "enabled" in payload:
            kwargs["enabled"] = bool(payload["enabled"])
        try:
            user = service.user_store.update_user(user_id, **kwargs)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"user": user.to_dict()}

    @app.post("/api/users/{user_id}/password")
    async def api_set_user_password(request: Request, user_id: str) -> dict[str, Any]:
        require_permission(request, PERM_MANAGE_USERS)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        try:
            service.user_store.set_password(user_id, str(payload.get("password", "")))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"updated": True}

    @app.delete("/api/users/{user_id}")
    async def api_delete_user(request: Request, user_id: str) -> dict[str, Any]:
        require_permission(request, PERM_MANAGE_USERS)
        session_user = request.session.get("user") or {}
        if session_user.get("id") == user_id:
            raise HTTPException(status_code=400, detail="Cannot delete yourself")
        try:
            service.user_store.delete_user(user_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"deleted": True, "user_id": user_id}

    # -- Logs page + API ----------------------------------------------------

    @app.get("/logs", response_class=HTMLResponse)
    async def logs_page(request: Request) -> HTMLResponse:
        user = require_login(request)
        if not has_permission(user, PERM_VIEW_LOGS):
            raise HTTPException(status_code=403, detail="Permission denied")
        return templates.TemplateResponse(request, "logs.html", {"user": user})

    @app.get("/api/logs/files")
    async def api_list_log_files(request: Request) -> dict[str, Any]:
        require_permission(request, PERM_VIEW_LOGS)
        files = service.log_service.list_files()
        return {"files": files, "log_dir": str(service.log_service.log_dir)}

    @app.get("/api/logs/tail")
    async def api_tail_log(
        request: Request,
        filename: str,
        limit: int = 500,
        level: str | None = None,
        logger: str | None = None,
        q: str | None = None,
        since: str | None = None,
        until: str | None = None,
    ) -> dict[str, Any]:
        require_permission(request, PERM_VIEW_LOGS)
        try:
            return service.log_service.read_tail(
                filename=filename,
                limit=limit,
                level=level,
                logger_filter=logger,
                query=q,
                since=since,
                until=until,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=f"Log file not found: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/logs/analyze")
    async def api_analyze_logs(request: Request) -> dict[str, Any]:
        require_permission(request, PERM_ANALYZE_LOGS)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        try:
            return service.log_service.analyze(
                records_text=str(payload.get("text", "")),
                focus=str(payload.get("focus", "")),
                agent_name=str(payload.get("agent", "rd_director")),
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            logger.error("Log analyze failed: %s", exc)
            raise HTTPException(status_code=500, detail=f"Analysis failed: {exc}") from exc

    return app
