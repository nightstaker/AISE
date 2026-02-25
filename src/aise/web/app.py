"""FastAPI web system for project management."""

from __future__ import annotations

import json
import os
import re
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
from starlette.middleware.sessions import SessionMiddleware
from starlette.status import HTTP_303_SEE_OTHER, HTTP_401_UNAUTHORIZED

from ..config import ProjectConfig
from ..core.artifact import Artifact, ArtifactType
from ..core.project import Project, ProjectStatus
from ..core.project_manager import ProjectManager
from ..core.task_state import RunTaskStateStore, TaskDocRef, TaskMemoryRecorder
from ..core.workflow import WorkflowEngine
from ..langchain.agent_node import SKILL_INPUT_HINTS, build_retry_skill_input
from ..main import create_team
from ..runtime import AgentRuntime, InMemoryMemoryManager, MasterAgent, validate_task_plan_payload
from ..runtime.exceptions import AuthorizationError as RuntimeAuthorizationError
from ..runtime.models import Principal
from ..runtime.registry import WorkerRegistry
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
    phase_results: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RequirementEntry:
    """Represents one requirement dispatch entry."""

    requirement_id: str
    text: str
    created_at: datetime
    source: str = "web"


@dataclass
class TaskExecUnit:
    phase_key: str
    task_key: str
    agent_name: str
    skill_name: str
    execution_scope: str = "full_skill"
    downstream_index: int = 0
    display_name: str = ""


class WebProjectService:
    """Coordinates project operations used by the web layer."""

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
        self._active_retry_ops: set[str] = set()
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
            project = self.project_manager.get_project(project_id)
            if project is not None:
                self._attach_langchain_runtime(project)
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

            workflow_nodes = self._build_workflow_nodes(project)
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
            project = self.project_manager.get_project(project_id)
            run = self._find_run(project_id, run_id)
            if run is not None:
                self._recover_stale_run_execution_state_locked(project_id, run_id, run)
                payload = self._serialize_run(run)
                payload = self._augment_live_phase_results(project_id, payload, run=run, project=project)
                task_summary = self.get_run_task_state_summary(project_id, run_id)
                payload["task_state_summary"] = task_summary.get("tasks", {})
                payload["active_operation"] = task_summary.get("active_operation")
                payload["retry_supported"] = True
                payload["retry_modes"] = ["current", "downstream"]
                return payload
        return None

    def get_task_logs(
        self,
        project_id: str,
        run_id: str,
        *,
        phase_key: str,
        task_key: str,
        limit: int = 300,
    ) -> dict[str, Any] | None:
        with self._lock:
            project = self.project_manager.get_project(project_id)
            run = self._find_run(project_id, run_id)
            if project is None or run is None:
                return None

            events: list[dict[str, Any]] = []
            events.extend(self._collect_runtime_task_events(run, phase_key=phase_key, task_key=task_key))
            events.extend(self._collect_trace_task_events(project, run, phase_key=phase_key, task_key=task_key))
            events.extend(self._collect_app_log_events(project, run, phase_key=phase_key, task_key=task_key))

            def _sort_key(item: dict[str, Any]) -> tuple[str, str]:
                return (str(item.get("ts", "")), str(item.get("id", "")))

            dedup: dict[str, dict[str, Any]] = {}
            for item in sorted(events, key=_sort_key):
                event_id = str(item.get("id", "")).strip()
                if not event_id:
                    continue
                dedup[event_id] = item

            merged = sorted(dedup.values(), key=_sort_key)
            if limit > 0:
                merged = merged[-limit:]

            return {
                "project_id": project_id,
                "run_id": run_id,
                "phase_key": phase_key,
                "task_key": task_key,
                "events": merged,
            }

    def get_task_state(
        self,
        project_id: str,
        run_id: str,
        *,
        phase_key: str,
        task_key: str,
    ) -> dict[str, Any] | None:
        with self._lock:
            project = self.project_manager.get_project(project_id)
            run = self._find_run(project_id, run_id)
            if project is None or run is None:
                return None
            self._recover_stale_run_execution_state_locked(project_id, run_id, run)
            store = self._run_task_state_store(project_id, run_id)
            item = store.get_task(phase_key, task_key)
            summary = store.summary()
            return {
                "project_id": project_id,
                "run_id": run_id,
                "phase_key": phase_key,
                "task_key": task_key,
                "task_state": item,
                "active_operation": summary.get("active_operation"),
            }

    def get_run_task_state_summary(self, project_id: str, run_id: str) -> dict[str, Any]:
        store = self._run_task_state_store(project_id, run_id)
        return store.summary()

    def retry_task(
        self,
        project_id: str,
        run_id: str,
        *,
        phase_key: str,
        task_key: str,
        mode: str = "current",
    ) -> dict[str, Any]:
        normalized_mode = "downstream" if str(mode).strip().lower() == "downstream" else "current"
        with self._lock:
            project = self.project_manager.get_project(project_id)
            run = self._find_run(project_id, run_id)
            if project is None or run is None:
                raise ValueError("Run not found")
            self._recover_stale_run_execution_state_locked(project_id, run_id, run)
            if str(run.status).lower() in {"pending", "running"}:
                store_check = self._run_task_state_store(project_id, run_id).load().get("active_operation")
                if not (isinstance(store_check, dict) and str(store_check.get("status", "")).lower() == "running"):
                    raise RuntimeError("当前 run 正在执行中，暂不支持并发任务重试")
            store = self._run_task_state_store(project_id, run_id)
            current_state = store.load()
            active = current_state.get("active_operation")
            if isinstance(active, dict) and str(active.get("status", "")).lower() == "running":
                raise RuntimeError("当前 run 已有任务正在执行/重试，请稍后再试")

            plan = self._build_task_execution_plan(
                project,
                run,
                phase_key=phase_key,
                task_key=task_key,
                mode=normalized_mode,
            )
            if not plan:
                raise ValueError("未找到可执行任务计划")

            op_id = f"retry_{uuid.uuid4().hex[:10]}"
            active_op = {
                "op_id": op_id,
                "type": "task_retry",
                "status": "running",
                "phase_key": phase_key,
                "task_key": task_key,
                "mode": normalized_mode,
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
            store.set_active_operation(active_op)
            self._active_retry_ops.add(op_id)
            run.status = "running"
            run.error = ""
            self._save_state()

        Thread(
            target=self._execute_task_retry,
            args=(project_id, run_id, plan, active_op),
            daemon=True,
        ).start()

        return {
            "accepted": True,
            "status": "queued",
            "op_id": op_id,
            "project_id": project_id,
            "run_id": run_id,
            "phase_key": phase_key,
            "task_key": task_key,
            "mode": normalized_mode,
        }

    def run_requirement(self, project_id: str, requirement_text: str) -> str:
        """Submit requirement and execute workflow asynchronously."""
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
            run = WorkflowRun(
                run_id=run_id,
                requirement_text=requirement,
                started_at=datetime.now(timezone.utc),
                status="pending",
            )
            self._runs_by_project.setdefault(project_id, []).append(run)
            self._active_workflow_runs.add((project_id, run_id))
            self._save_state()
            logger.info("Web requirement queued: project_id=%s run_id=%s", project_id, run_id)

        Thread(
            target=self._execute_workflow_run,
            args=(project_id, run_id, requirement),
            daemon=True,
        ).start()

        return run_id

    def _execute_task_retry(
        self,
        project_id: str,
        run_id: str,
        plan: list[TaskExecUnit],
        active_op: dict[str, Any],
    ) -> None:
        store = self._run_task_state_store(project_id, run_id)
        op_id = str(active_op.get("op_id", ""))
        error_message = ""
        try:
            for index, unit in enumerate(plan):
                self._execute_task_exec_unit(
                    project_id=project_id,
                    run_id=run_id,
                    unit=TaskExecUnit(
                        phase_key=unit.phase_key,
                        task_key=unit.task_key,
                        agent_name=unit.agent_name,
                        skill_name=unit.skill_name,
                        execution_scope=unit.execution_scope,
                        downstream_index=index,
                        display_name=unit.display_name,
                    ),
                    mode=str(active_op.get("mode", "current")),
                    kind="retry",
                )
        except Exception as exc:
            logger.exception("Task retry failed: project_id=%s run_id=%s op_id=%s", project_id, run_id, op_id)
            error_message = str(exc)
        finally:
            with self._lock:
                self._active_retry_ops.discard(op_id)
                run = self._find_run(project_id, run_id)
                if run is not None:
                    run.error = error_message
                    run.status = "failed" if error_message else "completed"
                    run.completed_at = datetime.now(timezone.utc)
                    self._save_state()
            latest = store.load()
            active = latest.get("active_operation")
            if isinstance(active, dict) and str(active.get("op_id", "")) == op_id:
                latest["active_operation"] = {
                    **active,
                    "status": "failed" if error_message else "completed",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                    "error": error_message,
                }
                store.save(latest)

    def _execute_task_exec_unit(
        self,
        *,
        project_id: str,
        run_id: str,
        unit: TaskExecUnit,
        mode: str,
        kind: str,
    ) -> None:
        with self._lock:
            project = self.project_manager.get_project(project_id)
            run = self._find_run(project_id, run_id)
            if project is None or run is None:
                raise ValueError("Run not found")
            project_input = {
                "raw_requirements": run.requirement_text,
                "user_memory": [
                    entry.text for entry in self._requirements_by_project.get(project_id, []) if entry.text.strip()
                ],
                "_run_id": run_id,
                "_project_id": project_id,
            }
            phase_results_map = self._phase_results_to_deep_result_map(run.phase_results)
            artifact_ids = self._collect_artifact_ids_from_phase_results(run.phase_results)
            retry_input, defaults = build_retry_skill_input(
                artifact_store=project.orchestrator.artifact_store,
                skill_name=unit.skill_name,
                project_input=project_input,
                phase=unit.phase_key,
                phase_results=phase_results_map,
                artifact_ids=artifact_ids,
            )
            recorder = TaskMemoryRecorder(self._run_task_state_store(project_id, run_id))
            retry_input.setdefault("retry_task_key", unit.task_key)
            retry_input.setdefault("retry_mode", mode)
            if getattr(project, "config", None) is not None:
                retry_input.setdefault(
                    "_review_round_limits",
                    {
                        "min_rounds": int(getattr(project.config.workflow, "review_min_rounds", 2) or 2),
                        "max_rounds": int(getattr(project.config.workflow, "review_max_rounds", 3) or 3),
                    },
                )
                retry_input.setdefault(
                    "_developer_sr_task_retry_attempts",
                    max(1, int(getattr(project.config.workflow, "developer_sr_task_retry_attempts", 2) or 2)),
                )

            attempt_started = recorder.record_task_attempt_start(
                phase_key=unit.phase_key,
                task_key=unit.task_key,
                display_name=unit.display_name or unit.task_key.rsplit(".", 1)[-1],
                kind=kind,
                mode=mode,
                executor={
                    "agent": unit.agent_name,
                    "skill": unit.skill_name,
                    "task_key": unit.task_key,
                    "execution_scope": unit.execution_scope,
                },
            )
            attempt = attempt_started.get("attempt", {})
            attempt_no = int((attempt or {}).get("attempt_no", 0) or 0)

            input_hints = self._task_input_hints_from_workflow(project, unit.phase_key, unit.task_key)
            doc_refs = [ref.to_dict() for ref in self._resolve_doc_refs_for_task(project, input_hints, unit.task_key)]
            recorder.record_task_attempt_context(
                phase_key=unit.phase_key,
                task_key=unit.task_key,
                attempt_no=attempt_no,
                context={
                    "input_hints": input_hints,
                    "input_keys": sorted(retry_input.keys()),
                    "doc_refs": doc_refs,
                    "notes": self._retry_notes_for_task(unit.task_key, unit.execution_scope),
                },
            )

        agent = project.orchestrator.agents.get(unit.agent_name) if project is not None else None
        if agent is None:
            recorder.record_task_attempt_end(
                phase_key=unit.phase_key,
                task_key=unit.task_key,
                attempt_no=attempt_no,
                status="failed",
                error=f"agent not found: {unit.agent_name}",
            )
            raise ValueError(f"agent not found: {unit.agent_name}")

        parameters = {
            "project_root": project.project_root or "",
            "phase": unit.phase_key,
            "phase_key": unit.phase_key,
            "agent_name": unit.agent_name,
            "project_name": project.config.project_name if getattr(project, "config", None) else "",
            "input_defaults": defaults,
            "task_memory_recorder": recorder,
            "retry_task_key": unit.task_key,
            "retry_mode": mode,
            "execution_scope": unit.execution_scope,
            "run_id": run_id,
            "project_id": project_id,
        }
        if "_task_memory_recorder" not in retry_input:
            retry_input["_task_memory_recorder"] = recorder
        if "_run_id" not in retry_input:
            retry_input["_run_id"] = run_id
        if "_project_id" not in retry_input:
            retry_input["_project_id"] = project_id

        try:
            artifact = agent.execute_skill(
                skill_name=unit.skill_name,
                input_data=retry_input,
                project_name=project.config.project_name if getattr(project, "config", None) else "",
                parameters=parameters,
            )
            outputs = self._extract_task_outputs(project, artifact)
            recorder.record_task_attempt_output(
                phase_key=unit.phase_key,
                task_key=unit.task_key,
                attempt_no=attempt_no,
                outputs=outputs,
            )
            recorder.record_task_attempt_end(
                phase_key=unit.phase_key,
                task_key=unit.task_key,
                attempt_no=attempt_no,
                status="completed",
                error="",
            )
        except Exception as exc:
            recorder.record_task_attempt_end(
                phase_key=unit.phase_key,
                task_key=unit.task_key,
                attempt_no=attempt_no,
                status="failed",
                error=str(exc),
            )
            raise

    def _execute_workflow_run(self, project_id: str, run_id: str, requirement: str) -> None:
        task_store = self._run_task_state_store(project_id, run_id)
        task_recorder = TaskMemoryRecorder(task_store)
        try:
            with self._lock:
                run = self._find_run(project_id, run_id)
                if run is None:
                    return
                run.status = "running"
                run.error = ""
                memory_items = [
                    entry.text for entry in self._requirements_by_project.get(project_id, []) if entry.text.strip()
                ]
                self._save_state()

            try:
                results = self.project_manager.run_project_workflow(
                    project_id,
                    {
                        "raw_requirements": requirement,
                        "user_memory": memory_items,
                        "_task_memory_recorder": task_recorder,
                        "_run_id": run_id,
                        "_project_id": project_id,
                    },
                )
                completed_status = "completed"
                error_message = ""
            except Exception as exc:
                logger.exception("Web requirement failed: project_id=%s run_id=%s", project_id, run_id)
                results = []
                completed_status = "failed"
                error_message = str(exc)

            with self._lock:
                run = self._find_run(project_id, run_id)
                if run is None:
                    return
                run.phase_results = results
                run.status = completed_status
                run.error = error_message
                run.completed_at = datetime.now(timezone.utc)

                project = self.project_manager.get_project(project_id)
                if completed_status == "completed" and project is not None and project.project_root:
                    runs_dir = Path(project.project_root) / "runs"
                    runs_dir.mkdir(parents=True, exist_ok=True)
                    run_path = runs_dir / f"{run_id}.json"
                    run_path.write_text(
                        json.dumps(self._serialize_run(run), ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )
                self._save_state()
                logger.info(
                    "Web requirement finished: project_id=%s run_id=%s status=%s",
                    project_id,
                    run_id,
                    completed_status,
                )
        finally:
            with self._lock:
                self._active_workflow_runs.discard((project_id, run_id))

    def _find_run(self, project_id: str, run_id: str) -> WorkflowRun | None:
        for run in self._runs_by_project.get(project_id, []):
            if run.run_id == run_id:
                return run
        return None

    def _recover_stale_run_execution_state_locked(self, project_id: str, run_id: str, run: WorkflowRun) -> None:
        store = self._run_task_state_store(project_id, run_id)
        state = store.load()
        active = state.get("active_operation")
        now_iso = datetime.now(timezone.utc).isoformat()
        dirty_run = False

        if isinstance(active, dict) and str(active.get("status", "")).lower() == "running":
            op_id = str(active.get("op_id", "")).strip()
            if not op_id or op_id not in self._active_retry_ops:
                stale_error = "任务重试异常终止，已自动回收卡住的 running 状态"
                state["active_operation"] = {
                    **active,
                    "status": "failed",
                    "completed_at": now_iso,
                    "error": stale_error,
                }
                store.save(state)
                store.fail_running_attempts(stale_error)
                if str(run.status).lower() in {"pending", "running"}:
                    run.status = "failed"
                    run.error = stale_error
                    run.completed_at = datetime.now(timezone.utc)
                    dirty_run = True

        active_after = state.get("active_operation")
        has_retry_running = isinstance(active_after, dict) and str(active_after.get("status", "")).lower() == "running"
        if str(run.status).lower() in {"pending", "running"} and not has_retry_running:
            if (project_id, run_id) not in self._active_workflow_runs:
                stale_error = "任务执行异常终止，已自动回收卡住的 running 状态"
                run.status = "failed"
                run.error = stale_error
                run.completed_at = datetime.now(timezone.utc)
                dirty_run = True
                store.fail_running_attempts(stale_error)

        if dirty_run:
            self._save_state()

    def _run_task_state_store(self, project_id: str, run_id: str) -> RunTaskStateStore:
        project = self.project_manager.get_project(project_id)
        if project is None or not project.project_root:
            # Fallback path under projects root for robustness.
            path = self.project_manager._projects_root / project_id / "runs" / f"{run_id}.task_state.json"
        else:
            path = Path(project.project_root) / "runs" / f"{run_id}.task_state.json"
        return RunTaskStateStore(path, project_id=project_id, run_id=run_id)

    def _phase_results_to_deep_result_map(self, phase_results: list[dict[str, Any]]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if not isinstance(phase_results, list):
            return out
        for row in phase_results:
            if not isinstance(row, dict):
                continue
            phase = str(row.get("phase", "")).strip()
            if not phase:
                continue
            status = str(row.get("status", "")).strip().lower()
            tasks = row.get("tasks", {})
            agent_name = ""
            if isinstance(tasks, dict):
                for key in tasks:
                    if isinstance(key, str) and "." in key:
                        agent_name = key.split(".", 1)[0]
                        if agent_name:
                            break
            if not agent_name:
                agent_name = {
                    "requirements": "product_manager",
                    "design": "architect",
                    "implementation": "developer",
                    "testing": "qa_engineer",
                }.get(phase, "unknown_agent")
            out[f"{phase}_{agent_name}"] = "completed" if status == "completed" else "failed"
        return out

    def _collect_artifact_ids_from_phase_results(self, phase_results: list[dict[str, Any]]) -> list[str]:
        ids: list[str] = []
        if not isinstance(phase_results, list):
            return ids
        for row in phase_results:
            if not isinstance(row, dict):
                continue
            tasks = row.get("tasks", {})
            if not isinstance(tasks, dict):
                continue
            for task in tasks.values():
                if not isinstance(task, dict):
                    continue
                artifact_id = str(task.get("artifact_id", "")).strip()
                if artifact_id:
                    ids.append(artifact_id)
        # preserve order, drop duplicates
        seen: set[str] = set()
        ordered: list[str] = []
        for item in ids:
            if item in seen:
                continue
            seen.add(item)
            ordered.append(item)
        return ordered

    def _build_task_execution_plan(
        self,
        project: Project,
        run: WorkflowRun,
        *,
        phase_key: str,
        task_key: str,
        mode: str,
    ) -> list[TaskExecUnit]:
        nodes = self._build_workflow_nodes(project)
        ordered_units: list[TaskExecUnit] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            pkey = str(node.get("name", "")).strip()
            if not pkey:
                continue
            raw_agent_tasks = node.get("agent_tasks", [])
            if not isinstance(raw_agent_tasks, list):
                continue
            for group in raw_agent_tasks:
                if not isinstance(group, dict):
                    continue
                tasks = group.get("tasks", [])
                if not isinstance(tasks, list):
                    continue
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    tkey = str(task.get("key", "")).strip()
                    if not tkey:
                        continue
                    mapping = self._map_task_key_to_execution(tkey)
                    ordered_units.append(
                        TaskExecUnit(
                            phase_key=pkey,
                            task_key=tkey,
                            agent_name=mapping["agent_name"],
                            skill_name=mapping["skill_name"],
                            execution_scope=mapping["execution_scope"],
                            display_name=str(task.get("name", "")) or tkey.rsplit(".", 1)[-1],
                        )
                    )

        start_idx = next(
            (
                idx
                for idx, unit in enumerate(ordered_units)
                if unit.phase_key == phase_key and unit.task_key == task_key
            ),
            -1,
        )
        if start_idx < 0:
            return []
        if mode == "downstream":
            return ordered_units[start_idx:]
        return [ordered_units[start_idx]]

    @staticmethod
    def _map_task_key_to_execution(task_key: str) -> dict[str, str]:
        agent_name = task_key.split(".", 1)[0] if "." in task_key else ""
        skill_name = task_key.split(".", 2)[1] if task_key.count(".") >= 2 else task_key.rsplit(".", 1)[-1]
        execution_scope = "full_skill"

        if task_key.startswith("product_manager.deep_product_workflow.step1"):
            skill_name = "deep_product_workflow"
            execution_scope = "step1"
        elif task_key.startswith("product_manager.deep_product_workflow.step2."):
            skill_name = "deep_product_workflow"
            execution_scope = "step2_loop"
        elif task_key.startswith("product_manager.deep_product_workflow.step3."):
            skill_name = "deep_product_workflow"
            execution_scope = "step3_loop"
        elif task_key.startswith("product_manager.deep_product_workflow"):
            skill_name = "deep_product_workflow"
            execution_scope = "full_skill"
        elif task_key.startswith("architect.deep_architecture_workflow.step1."):
            skill_name = "deep_architecture_workflow"
            execution_scope = "step1_loop"
        elif task_key.startswith("architect.deep_architecture_workflow.step2_3"):
            skill_name = "deep_architecture_workflow"
            execution_scope = "step2_3"
        elif task_key.startswith("architect.deep_architecture_workflow.step2"):
            skill_name = "deep_architecture_workflow"
            execution_scope = "step2"
        elif task_key.startswith("architect.deep_architecture_workflow.step3"):
            skill_name = "deep_architecture_workflow"
            execution_scope = "step3"
        elif task_key.startswith("architect.deep_architecture_workflow.step4."):
            skill_name = "deep_architecture_workflow"
            execution_scope = "step4_loop"
        elif task_key.startswith("architect.deep_architecture_workflow.step5"):
            skill_name = "deep_architecture_workflow"
            execution_scope = "step5"
        elif task_key.startswith("architect.deep_architecture_workflow"):
            skill_name = "deep_architecture_workflow"
            execution_scope = "full_skill"
        elif task_key.startswith("developer.deep_developer_workflow.step1"):
            skill_name = "deep_developer_workflow"
            execution_scope = "step1"
        elif task_key.startswith("developer.deep_developer_workflow.step2."):
            skill_name = "deep_developer_workflow"
            execution_scope = "step2_loop"
        elif task_key.startswith("developer.deep_developer_workflow"):
            skill_name = "deep_developer_workflow"
            execution_scope = "full_skill"
        elif "." in task_key:
            parts = task_key.split(".", 1)
            agent_name = parts[0]
            skill_name = parts[1]

        return {
            "agent_name": agent_name,
            "skill_name": skill_name,
            "execution_scope": execution_scope,
        }

    def _task_input_hints_from_workflow(self, project: Project, phase_key: str, task_key: str) -> list[str]:
        nodes = self._build_workflow_nodes(project)
        for node in nodes:
            if not isinstance(node, dict) or str(node.get("name", "")) != phase_key:
                continue
            for group in node.get("agent_tasks", []) if isinstance(node.get("agent_tasks", []), list) else []:
                if not isinstance(group, dict):
                    continue
                for task in group.get("tasks", []) if isinstance(group.get("tasks", []), list) else []:
                    if not isinstance(task, dict):
                        continue
                    if str(task.get("key", "")) == task_key:
                        hints = task.get("input_hints", [])
                        return [str(x) for x in hints] if isinstance(hints, list) else []
        mapping = self._map_task_key_to_execution(task_key)
        return list(SKILL_INPUT_HINTS.get(mapping["skill_name"], []))

    def _resolve_doc_refs_for_task(self, project: Project, input_hints: list[str], task_key: str) -> list[TaskDocRef]:
        refs: list[TaskDocRef] = []
        if not project.project_root:
            return refs
        root = Path(project.project_root)
        docs_dir = root / "docs"
        hint_map: dict[str, tuple[str, str | None]] = {
            "system_design_doc": ("docs/system-design.md", None),
            "system_requirements_doc": ("docs/system-requirements.md", None),
            "system_architecture_doc": ("docs/system-architecture.md", None),
            "source_dir": ("src", None),
            "tests_dir": ("tests", None),
        }
        glob_map: dict[str, tuple[str, str]] = {
            "subsystem_detail_design_docs": ("docs", "subsystem-*-design.md|*-detail-design.md"),
        }
        seen: set[str] = set()
        for hint in input_hints:
            if hint in hint_map:
                rel, _ = hint_map[hint]
                path = root / rel
                key = f"{hint}:{rel}"
                if key in seen:
                    continue
                seen.add(key)
                refs.append(TaskDocRef(role=hint, path=rel, name=Path(rel).name, exists=path.exists()))
            elif hint in glob_map:
                base_rel, pattern = glob_map[hint]
                base = root / base_rel
                patterns = [p for p in pattern.split("|") if p]
                matches = []
                if base.exists():
                    for item_pattern in patterns:
                        matches.extend(sorted(base.glob(item_pattern)))
                key = f"{hint}:{base_rel}:{pattern}"
                if key in seen:
                    continue
                seen.add(key)
                refs.append(
                    TaskDocRef(
                        role=hint,
                        path=base_rel,
                        name=Path(base_rel).name,
                        exists=bool(matches),
                        glob=pattern,
                    )
                )
        # Deep task-specific补充
        if (
            task_key.startswith("architect.deep_architecture_workflow")
            and (docs_dir / "system-architecture.md").exists()
        ):
            key = "system_architecture_doc:docs/system-architecture.md"
            if key not in seen:
                refs.append(
                    TaskDocRef(
                        role="system_architecture_doc",
                        path="docs/system-architecture.md",
                        name="system-architecture.md",
                        exists=True,
                    )
                )
        return refs

    @staticmethod
    def _retry_notes_for_task(task_key: str, execution_scope: str) -> list[str]:
        notes: list[str] = []
        if ".review" in task_key and execution_scope.endswith("_loop"):
            notes.append("review task maps to parent loop retry for consistency")
        if execution_scope != "full_skill" and "deep_" in task_key:
            notes.append(f"execution scope: {execution_scope}")
        return notes

    def _extract_task_outputs(self, project: Project, artifact: Artifact) -> dict[str, Any]:
        content = artifact.content if isinstance(artifact.content, dict) else {}
        generated_files: list[str] = []
        for key in ("generated_files", "generated_docs", "generated_sources"):
            value = content.get(key)
            if isinstance(value, list):
                generated_files.extend(str(x) for x in value if str(x).strip())
        if "generated" in content and isinstance(content.get("generated"), dict):
            generated = content.get("generated", {})
            for key in ("source_files", "test_files"):
                value = generated.get(key)
                if isinstance(value, list):
                    generated_files.extend(str(x) for x in value if str(x).strip())
        artifact_ids: list[str] = [artifact.id]
        ids_map = content.get("artifact_ids")
        if isinstance(ids_map, dict):
            artifact_ids.extend(str(v) for v in ids_map.values() if str(v).strip())
        normalized_files: list[str] = []
        root = Path(project.project_root).resolve() if project.project_root else None
        seen: set[str] = set()
        for item in generated_files:
            text = str(item).strip()
            if not text:
                continue
            try:
                p = Path(text)
                if root is not None:
                    resolved = p.resolve() if p.is_absolute() else (root / p).resolve()
                    try:
                        text = str(resolved.relative_to(root))
                    except ValueError:
                        text = str(resolved)
                else:
                    text = str(p)
            except Exception:
                pass
            if text in seen:
                continue
            seen.add(text)
            normalized_files.append(text)
        doc_outputs = [f for f in normalized_files if f.startswith("docs/")]
        result = {
            "artifact_ids": artifact_ids,
            "generated_files": normalized_files,
            "doc_outputs": doc_outputs,
        }
        workflow = str(content.get("workflow", "")).strip()
        if workflow:
            result["workflow"] = workflow
            result["workflow_summary"] = self._extract_workflow_output_summary(project, workflow, content)
        return result

    def _extract_workflow_output_summary(
        self,
        project: Project,
        workflow: str,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {"workflow": workflow}
        if workflow == "deep_product_workflow":
            step1 = content.get("step1", {}) if isinstance(content.get("step1"), dict) else {}
            step2 = content.get("step2", {}) if isinstance(content.get("step2"), dict) else {}
            step3 = content.get("step3", {}) if isinstance(content.get("step3"), dict) else {}
            summary["rounds"] = {
                "step1": int(step1.get("memory_items", 0) or 0),
                "step2": int(step2.get("rounds", 0) or 0),
                "step3": int(step3.get("rounds", 0) or 0),
            }
            return summary

        if workflow == "deep_architecture_workflow":
            steps = content.get("steps", {}) if isinstance(content.get("steps"), dict) else {}
            step1 = steps.get("step1", {}) if isinstance(steps.get("step1"), dict) else {}
            step4 = steps.get("step4", {}) if isinstance(steps.get("step4"), dict) else {}
            step2_3 = steps.get("step2_3", {}) if isinstance(steps.get("step2_3"), dict) else {}
            summary["rounds"] = {"step1": int(step1.get("rounds", 0) or 0)}
            summary["subsystem_rounds_each"] = {}
            try:
                status_artifact = project.orchestrator.artifact_store.get_latest(ArtifactType.STATUS_TRACKING)
                if status_artifact and isinstance(status_artifact.content, dict):
                    step4_map = status_artifact.content.get("step4_rounds_each", {})
                    if isinstance(step4_map, dict):
                        summary["subsystem_rounds_each"] = {
                            str(k): int(v or 0) for k, v in step4_map.items() if str(k).strip()
                        }
            except Exception:
                summary["subsystem_rounds_each"] = {}
            summary["subsystems"] = self._build_architecture_subsystem_cards(project, step2_3.get("assignments"))
            summary["step4_subsystems"] = (
                list(step4.get("subsystems", [])) if isinstance(step4.get("subsystems"), list) else []
            )
            return summary

        if workflow == "deep_developer_workflow":
            step1 = content.get("step1", {}) if isinstance(content.get("step1"), dict) else {}
            step2 = content.get("step2", {}) if isinstance(content.get("step2"), dict) else {}
            summary["rounds"] = {"step2": int(step2.get("rounds_per_subsystem", 0) or 0)}
            summary["sr_group_count"] = int(step2.get("sr_group_count", 0) or 0)
            summary["fn_count"] = int(step2.get("fn_count", 0) or 0)
            summary["subsystems"] = self._build_developer_subsystem_cards(project, step1.get("assignments"))
            return summary
        return summary

    def _build_architecture_subsystem_cards(self, project: Project, assignments_value: Any) -> list[dict[str, Any]]:
        assignments = assignments_value if isinstance(assignments_value, dict) else {}
        cards: list[dict[str, Any]] = []
        if not assignments:
            return cards
        for subsystem_id, item in assignments.items():
            if not isinstance(item, dict):
                continue
            cards.append(
                {
                    "subsystem_id": str(subsystem_id),
                    "subsystem_name": str(item.get("subsystem", subsystem_id)),
                    "assigned_sr_ids": (
                        [str(x) for x in item.get("assigned_sr_ids", [])]
                        if isinstance(item.get("assigned_sr_ids"), list)
                        else []
                    ),
                    "designer": str(item.get("subsystem_expert", "")),
                    "reviewer": str(item.get("architecture_reviewer", "")),
                }
            )
        if cards:
            return cards
        return cards

    def _build_developer_subsystem_cards(self, project: Project, assignments_value: Any) -> list[dict[str, Any]]:
        assignments = assignments_value if isinstance(assignments_value, dict) else {}
        cards: list[dict[str, Any]] = []
        if not assignments:
            return cards
        sr_allocation: dict[str, list[str]] = {}
        sr_groups_by_subsystem: dict[str, list[dict[str, Any]]] = {}
        try:
            arch_artifact = project.orchestrator.artifact_store.get_latest(ArtifactType.ARCHITECTURE_DESIGN)
            if arch_artifact and isinstance(arch_artifact.content, dict):
                alloc = arch_artifact.content.get("sr_allocation", {})
                if isinstance(alloc, dict):
                    for k, v in alloc.items():
                        if isinstance(v, list):
                            sr_allocation[str(k)] = [str(x) for x in v if str(x).strip()]
        except Exception:
            sr_allocation = {}
        try:
            functional_artifact = project.orchestrator.artifact_store.get_latest(ArtifactType.FUNCTIONAL_DESIGN)
            if functional_artifact and isinstance(functional_artifact.content, dict):
                grouped_fn: dict[str, dict[str, list[str]]] = {}
                for item in functional_artifact.content.get("functions", []):
                    if not isinstance(item, dict):
                        continue
                    subsystem_id = str(item.get("subsystem_id", "")).strip()
                    fn_id = str(item.get("id", "")).strip()
                    if not subsystem_id or not fn_id:
                        continue
                    sr_match = re.search(r"(SR-\d+)", fn_id.upper())
                    sr_id = sr_match.group(1) if sr_match else "SR-UNKNOWN"
                    grouped_fn.setdefault(subsystem_id, {}).setdefault(sr_id, []).append(fn_id)
                for subsystem_id, sr_map in grouped_fn.items():
                    sr_rows: list[dict[str, Any]] = []
                    for sr_id, fn_ids in sr_map.items():
                        sr_rows.append({"sr_id": sr_id, "fn_ids": list(fn_ids), "fn_count": len(fn_ids)})
                    sr_groups_by_subsystem[subsystem_id] = sr_rows
        except Exception:
            sr_groups_by_subsystem = {}

        for subsystem_id, item in assignments.items():
            if not isinstance(item, dict):
                continue
            cards.append(
                {
                    "subsystem_id": str(subsystem_id),
                    "subsystem_name": str(item.get("subsystem", subsystem_id)),
                    "assigned_sr_ids": list(sr_allocation.get(str(subsystem_id), [])),
                    "srs": list(sr_groups_by_subsystem.get(str(subsystem_id), [])),
                    "coder": str(item.get("coder", "")),
                    "reviewer": str(item.get("commiter", "")),
                }
            )
        return cards

    def _collect_runtime_task_events(
        self,
        run: WorkflowRun,
        *,
        phase_key: str,
        task_key: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for phase in run.phase_results:
            if not isinstance(phase, dict):
                continue
            if str(phase.get("phase", "")) != phase_key:
                continue
            events.append(
                {
                    "id": f"runtime-phase:{phase_key}:{str(phase.get('status', ''))}",
                    "ts": run.started_at.isoformat(),
                    "source": "runtime",
                    "level": "info",
                    "message": f"阶段状态: {phase.get('status', 'unknown')}",
                    "details": {
                        "phase": phase_key,
                        "task_count": len(phase.get("tasks", {}) or {}),
                    },
                }
            )
            tasks = phase.get("tasks", {})
            if not isinstance(tasks, dict):
                continue
            direct = tasks.get(task_key)
            if isinstance(direct, dict):
                events.append(
                    {
                        "id": f"runtime-task:{phase_key}:{task_key}",
                        "ts": run.started_at.isoformat(),
                        "source": "runtime",
                        "level": "info",
                        "message": f"任务状态: {direct.get('status', 'unknown')}",
                        "details": direct,
                    }
                )
                return events

            prefixes = self._runtime_task_aliases(phase_key, task_key)
            for alias in prefixes:
                item = tasks.get(alias)
                if isinstance(item, dict):
                    events.append(
                        {
                            "id": f"runtime-task:{phase_key}:{alias}",
                            "ts": run.started_at.isoformat(),
                            "source": "runtime",
                            "level": "info",
                            "message": f"运行时任务映射({alias})状态: {item.get('status', 'unknown')}",
                            "details": item,
                        }
                    )
                    break
            break
        return events

    def _runtime_task_aliases(self, phase_key: str, task_key: str) -> list[str]:
        aliases: list[str] = []
        if task_key.startswith("product_manager.deep_product_workflow"):
            aliases.extend(["product_manager.deep_product_workflow", "product_manager.requirements"])
        elif task_key.startswith("architect.deep_architecture_workflow"):
            aliases.extend(["architect.deep_architecture_workflow", "architect.design"])
        elif task_key.startswith("developer.deep_developer_workflow"):
            aliases.extend(["developer.deep_developer_workflow", "developer.implementation"])
        elif task_key.startswith("qa_engineer."):
            aliases.extend(["qa_engineer.testing", "qa_engineer.test_review"])
        aliases.append(f"{task_key.split('.', 1)[0]}.{phase_key}" if "." in task_key else task_key)
        return aliases

    def _collect_trace_task_events(
        self,
        project: Project,
        run: WorkflowRun,
        *,
        phase_key: str,
        task_key: str,
    ) -> list[dict[str, Any]]:
        if not project.project_root:
            return []
        trace_dir = Path(project.project_root) / "trace"
        if not trace_dir.exists():
            return []

        spec = self._task_log_match_spec(phase_key=phase_key, task_key=task_key)
        started_at = run.started_at
        events: list[dict[str, Any]] = []

        for trace_file in sorted(trace_dir.glob("*.json")):
            try:
                payload = json.loads(trace_file.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue

            called_at = self._parse_any_datetime(payload.get("called_at_iso")) or self._parse_trace_timestamp(
                str(payload.get("timestamp", ""))
            )
            if called_at is not None and called_at < started_at:
                continue

            if not self._trace_matches_spec(payload, spec):
                continue

            event_ts = (
                called_at.isoformat()
                if called_at is not None
                else str(payload.get("called_at_iso", "") or payload.get("timestamp", ""))
            )
            output_text = str(payload.get("output", ""))
            purpose = str(payload.get("purpose", ""))
            provider_meta = payload.get("provider_response_meta")
            trace_input = payload.get("input")
            input_messages = None
            input_kwargs = None
            if isinstance(trace_input, dict):
                raw_messages = trace_input.get("messages")
                raw_kwargs = trace_input.get("kwargs")
                if isinstance(raw_messages, list):
                    input_messages = raw_messages
                if isinstance(raw_kwargs, dict):
                    input_kwargs = raw_kwargs
            events.append(
                {
                    "id": f"trace:{str(payload.get('call_id', trace_file.stem))}",
                    "ts": event_ts,
                    "source": "trace",
                    "level": "info",
                    "message": purpose or f"LLM trace: {trace_file.name}",
                    "details": {
                        "trace_file": str(trace_file.relative_to(trace_dir.parent)),
                        "agent": str(payload.get("agent", "")),
                        "skill": str(payload.get("skill", "")),
                        "model": str(payload.get("model", "")),
                        "provider": str(payload.get("provider", "")),
                        "purpose_meta": self._parse_purpose_meta(purpose),
                        "provider_response_meta": provider_meta if isinstance(provider_meta, dict) else {},
                        "input_messages": input_messages if isinstance(input_messages, list) else [],
                        "input_kwargs": input_kwargs if isinstance(input_kwargs, dict) else {},
                        "output": output_text,
                        "output_preview": output_text[:1200],
                    },
                }
            )
        return events

    def _collect_app_log_events(
        self,
        project: Project,
        run: WorkflowRun,
        *,
        phase_key: str,
        task_key: str,
    ) -> list[dict[str, Any]]:
        spec = self._task_log_match_spec(phase_key=phase_key, task_key=task_key)
        log_path = Path(self.project_manager._global_config.logging.log_dir) / "aise.log"
        if not log_path.exists():
            return []

        started_at = run.started_at
        project_id = project.project_id
        project_name = project.config.project_name if getattr(project, "config", None) else ""
        events: list[dict[str, Any]] = []
        line_re = re.compile(
            r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \| (?P<level>[A-Z]+) \| (?P<logger>[^|]+) \| (?P<msg>.*)$"
        )
        try:
            lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            return []

        for idx, line in enumerate(lines, start=1):
            m = line_re.match(line)
            if not m:
                continue
            ts = self._parse_any_datetime(m.group("ts"))
            if ts is not None and ts < started_at:
                continue
            msg = m.group("msg")
            if project_id and f"project_id={project_id}" in msg:
                pass
            elif project_name and f"project={project_name}" in msg:
                pass
            elif not any(token and token in msg for token in spec["log_tokens"]):
                continue

            if spec["log_tokens"] and not any(token in msg for token in spec["log_tokens"] if token):
                continue

            events.append(
                {
                    "id": f"aise.log:{idx}",
                    "ts": (ts.isoformat() if ts is not None else ""),
                    "source": "aise.log",
                    "level": m.group("level").lower(),
                    "message": msg,
                    "details": {"logger": m.group("logger").strip(), "line": idx},
                }
            )
        return events

    def _task_log_match_spec(self, *, phase_key: str, task_key: str) -> dict[str, Any]:
        agent = task_key.split(".", 1)[0] if "." in task_key else ""
        spec: dict[str, Any] = {
            "agent": agent,
            "skill": "",
            "purpose_prefixes": [],
            "purpose_contains": [],
            "log_tokens": [phase_key, task_key],
        }

        if task_key.startswith("product_manager.deep_product_workflow"):
            spec["agent"] = "product_manager"
            spec["skill"] = "deep_product_workflow"
            spec["log_tokens"].extend(["agent=product_manager", "deep_product_workflow"])
            if task_key.startswith("product_manager.deep_product_workflow.step1"):
                spec["purpose_prefixes"] = [
                    "subagent:product_designer step:requirement_expansion.core",
                    "subagent:product_designer step:requirement_expansion.context",
                    "agent:product_manager role:product_manager skill:deep_product_workflow",
                ]
            elif task_key.startswith("product_manager.deep_product_workflow.step2.design"):
                spec["purpose_prefixes"] = ["subagent:product_designer step:product_design"]
            elif task_key.startswith("product_manager.deep_product_workflow.step2.review"):
                spec["purpose_prefixes"] = ["subagent:product_reviewer step:product_review"]
            elif task_key.startswith("product_manager.deep_product_workflow.step3.design"):
                spec["purpose_prefixes"] = ["subagent:product_designer step:system_requirement_design"]
            elif task_key.startswith("product_manager.deep_product_workflow.step3.review"):
                spec["purpose_prefixes"] = ["subagent:product_reviewer step:system_requirement_review"]
            elif task_key != "product_manager.deep_product_workflow":
                spec["purpose_prefixes"] = [f"task_key:{task_key}"]
        elif task_key.startswith("architect.deep_architecture_workflow.step1.design"):
            spec["agent"] = "architect"
            spec["skill"] = "deep_architecture_workflow"
            spec["purpose_prefixes"] = ["subagent:architect step:architecture_design"]
            spec["log_tokens"].extend(["subagent:architect", "architecture_design"])
        elif task_key.startswith("architect.deep_architecture_workflow.step1.review"):
            spec["agent"] = "architect"
            spec["skill"] = "deep_architecture_workflow"
            spec["purpose_prefixes"] = ["subagent:architecture_reviewer step:architecture_review"]
            spec["log_tokens"].extend(["subagent:architecture_reviewer", "architecture_review"])
        elif task_key.startswith("architect.deep_architecture_workflow.step4.design"):
            spec["agent"] = "architect"
            spec["skill"] = "deep_architecture_workflow"
            spec["purpose_prefixes"] = ["subagent:subsystem_expert step:subsystem_detail_design"]
            spec["log_tokens"].extend(["subagent:subsystem_expert", "subsystem_detail_design"])
        elif task_key.startswith("architect.deep_architecture_workflow.step4.review"):
            spec["agent"] = "architect"
            spec["skill"] = "deep_architecture_workflow"
            spec["purpose_prefixes"] = ["subagent:subsystem_reviewer step:subsystem_detail_review"]
            spec["log_tokens"].extend(["subagent:subsystem_reviewer", "subsystem_detail_review"])
        elif task_key.startswith("architect.deep_architecture_workflow.step2_3"):
            spec["agent"] = "architect"
            spec["skill"] = "deep_architecture_workflow"
            spec["purpose_prefixes"] = [
                "subagent:architect step:bootstrap_architecture_code",
                "subagent:architect step:subsystem_task_split",
            ]
            spec["log_tokens"].extend(["bootstrap_architecture_code", "subsystem_task_split"])
        elif task_key.startswith("architect.deep_architecture_workflow.step2"):
            spec["agent"] = "architect"
            spec["skill"] = "deep_architecture_workflow"
            spec["purpose_prefixes"] = ["subagent:architect step:bootstrap_architecture_code"]
        elif task_key.startswith("architect.deep_architecture_workflow.step3"):
            spec["agent"] = "architect"
            spec["skill"] = "deep_architecture_workflow"
            spec["purpose_prefixes"] = ["subagent:architect step:subsystem_task_split"]
        elif task_key.startswith("architect.deep_architecture_workflow.step5"):
            spec["agent"] = "architect"
            spec["skill"] = "deep_architecture_workflow"
            spec["purpose_prefixes"] = ["subagent:subsystem_expert step:subsystem_code_init_and_api_definition"]
        elif task_key.startswith("architect.deep_architecture_workflow"):
            spec["agent"] = "architect"
            spec["skill"] = "deep_architecture_workflow"
            spec["log_tokens"].extend(["agent=architect", "deep_architecture_workflow"])
            if task_key != "architect.deep_architecture_workflow":
                spec["purpose_prefixes"] = [f"task_key:{task_key}"]
        elif task_key.startswith("developer.deep_developer_workflow"):
            spec["agent"] = "developer"
            spec["skill"] = "deep_developer_workflow"
            spec["log_tokens"].extend(["agent=developer", "deep_developer_workflow"])
            if task_key.startswith("developer.deep_developer_workflow.step1"):
                spec["purpose_prefixes"] = ["subagent:coder step:subsystem_task_assignment"]
            elif task_key.startswith("developer.deep_developer_workflow.step2.develop"):
                spec["purpose_prefixes"] = [
                    "subagent:coder step:fn_code_generation",
                    "subagent:coder step:fn_test_generation",
                    "agent:developer role:developer skill:deep_developer_workflow",
                ]
            elif task_key.startswith("developer.deep_developer_workflow.step2.review"):
                spec["purpose_prefixes"] = ["subagent:commiter step:fn_code_and_test_review"]
            elif task_key.startswith("developer.deep_developer_workflow.step2.revision"):
                spec["purpose_prefixes"] = ["subagent:commiter step:revision_feedback_record"]
            elif task_key.startswith("developer.deep_developer_workflow.step2.merge"):
                spec["purpose_prefixes"] = [
                    "subagent:coder step:subsystem_batch_merge_after_review_rounds",
                    "subagent:coder step:fn_merge_after_three_rounds",
                ]
            elif task_key != "developer.deep_developer_workflow":
                spec["purpose_prefixes"] = [f"task_key:{task_key}"]
        elif task_key.startswith("qa_engineer."):
            spec["agent"] = "qa_engineer"
            spec["log_tokens"].extend(["agent=qa_engineer", "qa_engineer"])

        return spec

    def _trace_matches_spec(self, payload: dict[str, Any], spec: dict[str, Any]) -> bool:
        agent = str(payload.get("agent", ""))
        skill = str(payload.get("skill", ""))
        purpose = str(payload.get("purpose", ""))

        expected_agent = str(spec.get("agent", "") or "")
        if expected_agent and agent != expected_agent:
            return False
        expected_skill = str(spec.get("skill", "") or "")
        if expected_skill and skill and skill != expected_skill:
            return False

        purpose_prefixes = [str(x) for x in spec.get("purpose_prefixes", []) if str(x)]
        if purpose_prefixes:
            return any(purpose.startswith(prefix) for prefix in purpose_prefixes)

        purpose_contains = [str(x) for x in spec.get("purpose_contains", []) if str(x)]
        if purpose_contains and not any(token in purpose for token in purpose_contains):
            return False

        if expected_skill and not skill:
            return purpose.startswith(f"agent:{expected_agent}") or expected_skill in purpose

        return True

    def _parse_purpose_meta(self, purpose: str) -> dict[str, str]:
        text = str(purpose or "").strip()
        if not text:
            return {}
        meta: dict[str, str] = {}
        for token in text.split():
            if ":" not in token:
                continue
            key, value = token.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key or not value:
                continue
            if key in {
                "subagent",
                "step",
                "agent",
                "role",
                "skill",
                "project",
                "round",
                "subsystem",
                "sr",
                "fn",
                "module",
                "owner",
                "reviewer",
                "reqs",
                "features",
            }:
                meta[key] = value
        return meta

    def _parse_trace_timestamp(self, value: str) -> datetime | None:
        raw = value.strip()
        if not raw:
            return None
        for fmt in ("%Y%m%d-%H%M%S",):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
        return None

    def _parse_any_datetime(self, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                local_tz = datetime.now().astimezone().tzinfo or timezone.utc
                return dt.replace(tzinfo=local_tz).astimezone(timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
        try:
            local_tz = datetime.now().astimezone().tzinfo or timezone.utc
            return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=local_tz).astimezone(timezone.utc)
        except Exception:
            return None

    def _augment_live_phase_results(
        self,
        project_id: str,
        run_payload: dict[str, Any],
        *,
        run: WorkflowRun | None = None,
        project: Project | None = None,
    ) -> dict[str, Any]:
        status = str(run_payload.get("status", ""))
        if status not in {"pending", "running"}:
            return run_payload

        if project is None:
            project = self.project_manager.get_project(project_id)
        if project is None or not project.project_root:
            return run_payload

        started_at = self._parse_any_datetime(run_payload.get("started_at")) or datetime.now(timezone.utc)

        def _is_fresh_file(path: Path) -> bool:
            if not path.exists() or not path.is_file():
                return False
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except Exception:
                return False
            return modified >= started_at

        def _has_fresh_content(
            dir_path: Path,
            *,
            suffixes: set[str] | None = None,
            exclude_names: set[str] | None = None,
        ) -> bool:
            if not dir_path.exists() or not dir_path.is_dir():
                return False
            normalized_suffixes = {s.lower() for s in (suffixes or set()) if str(s).strip()}
            normalized_excludes = {name.lower() for name in (exclude_names or set()) if str(name).strip()}
            try:
                for file_path in dir_path.rglob("*"):
                    if not file_path.is_file():
                        continue
                    if normalized_excludes and file_path.name.lower() in normalized_excludes:
                        continue
                    if normalized_suffixes and file_path.suffix.lower() not in normalized_suffixes:
                        continue
                    modified = datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
                    if modified >= started_at:
                        return True
            except Exception:
                return False
            return False

        docs_dir = Path(project.project_root) / "docs"
        requirements_ready = _is_fresh_file(docs_dir / "system-design.md") and _is_fresh_file(
            docs_dir / "system-requirements.md"
        )
        design_ready = _is_fresh_file(docs_dir / "system-architecture.md")
        project_src = Path(project.project_root) / "src"
        project_tests = Path(project.project_root) / "tests"
        implementation_ready = _has_fresh_content(
            project_src / "services",
            suffixes={".py"},
            exclude_names={"__init__.py"},
        ) and _has_fresh_content(
            project_tests / "services",
            suffixes={".py"},
            exclude_names={"__init__.py", "revision.md"},
        )
        if not (requirements_ready or design_ready or implementation_ready):
            return run_payload

        phase_results = run_payload.get("phase_results", [])
        if not isinstance(phase_results, list):
            phase_results = []

        has_requirements_row = any(
            isinstance(row, dict) and str(row.get("phase", "")) == "requirements" for row in phase_results
        )
        has_design_row = any(isinstance(row, dict) and str(row.get("phase", "")) == "design" for row in phase_results)
        has_implementation_row = any(
            isinstance(row, dict) and str(row.get("phase", "")) == "implementation" for row in phase_results
        )

        synthetic_rows: list[dict[str, Any]] = []
        if requirements_ready and not has_requirements_row:
            synthetic_rows.append(
                {
                    "phase": "requirements",
                    "status": "completed",
                    "tasks": {
                        "product_manager.requirements": {"status": "success"},
                        "product_manager.deep_product_workflow": {"status": "success"},
                    },
                }
            )
        if design_ready and not has_design_row:
            synthetic_rows.append(
                {
                    "phase": "design",
                    "status": "completed",
                    "tasks": {
                        "architect.design": {"status": "success"},
                        "architect.deep_architecture_workflow": {"status": "success"},
                    },
                }
            )
        if implementation_ready and not has_implementation_row:
            synthetic_rows.append(
                {
                    "phase": "implementation",
                    "status": "completed",
                    "tasks": {
                        "developer.implementation": {"status": "success"},
                        "developer.deep_developer_workflow": {"status": "success"},
                    },
                }
            )
        if synthetic_rows:
            run_payload["phase_results"] = [*synthetic_rows, *phase_results]
        if run is not None:
            self._augment_live_task_states(project, run, run_payload)
        return run_payload

    def _augment_live_task_states(self, project: Project, run: WorkflowRun, run_payload: dict[str, Any]) -> None:
        try:
            workflow_nodes = self._build_workflow_nodes(project)
        except Exception:
            return
        if not isinstance(workflow_nodes, list) or not workflow_nodes:
            return

        phase_results = run_payload.get("phase_results", [])
        phase_rows: dict[str, dict[str, Any]] = {}
        if isinstance(phase_results, list):
            for row in phase_results:
                if not isinstance(row, dict):
                    continue
                phase_key = str(row.get("phase", "")).strip()
                if phase_key:
                    phase_rows[phase_key] = row

        live_task_states: dict[str, dict[str, Any]] = {}

        for node in workflow_nodes:
            if not isinstance(node, dict):
                continue
            phase_key = str(node.get("name", "")).strip()
            if not phase_key:
                continue
            phase_row = phase_rows.get(phase_key)
            phase_status = str((phase_row or {}).get("status", "")).strip()
            task_status_map = (phase_row or {}).get("tasks", {})
            if not isinstance(task_status_map, dict):
                task_status_map = {}

            raw_agent_tasks = node.get("agent_tasks", [])
            task_keys: list[str] = []
            if isinstance(raw_agent_tasks, list):
                for group in raw_agent_tasks:
                    if not isinstance(group, dict):
                        continue
                    group_tasks = group.get("tasks", [])
                    if not isinstance(group_tasks, list):
                        continue
                    for task in group_tasks:
                        if not isinstance(task, dict):
                            continue
                        task_key = str(task.get("key", "")).strip()
                        if task_key:
                            task_keys.append(task_key)
            if not task_keys:
                fallback_task_keys = node.get("tasks", [])
                if isinstance(fallback_task_keys, list):
                    task_keys = [str(x).strip() for x in fallback_task_keys if str(x).strip()]

            seen_task_keys: set[str] = set()
            for task_key in task_keys:
                if task_key in seen_task_keys:
                    continue
                seen_task_keys.add(task_key)

                runtime_status, runtime_match_key = self._resolve_runtime_task_status_map(
                    task_status_map,
                    phase_key,
                    task_key,
                )
                trace_events = self._collect_trace_task_events(project, run, phase_key=phase_key, task_key=task_key)
                event_count = len(trace_events)
                last_event = self._select_latest_event(trace_events)

                inferred_status = self._infer_live_task_status(
                    phase_status=phase_status,
                    runtime_status=runtime_status,
                    has_trace_events=bool(trace_events),
                )
                if not inferred_status:
                    continue

                payload: dict[str, Any] = {
                    "status": inferred_status,
                    "phase_status": phase_status,
                    "event_count": event_count,
                }
                if runtime_match_key:
                    payload["runtime_task_key"] = runtime_match_key
                if runtime_status:
                    payload["runtime_status"] = runtime_status
                if last_event:
                    payload["last_event"] = {
                        "ts": str(last_event.get("ts", "")),
                        "source": str(last_event.get("source", "")),
                        "level": str(last_event.get("level", "")),
                        "message": str(last_event.get("message", ""))[:240],
                    }
                    details = last_event.get("details")
                    if isinstance(details, dict):
                        meta = details.get("purpose_meta")
                        if isinstance(meta, dict) and meta:
                            compact_meta: dict[str, str] = {}
                            for key in (
                                "subagent",
                                "step",
                                "round",
                                "subsystem",
                                "sr",
                                "fn",
                                "module",
                                "reviewer",
                                "owner",
                            ):
                                value = meta.get(key)
                                if value:
                                    compact_meta[key] = str(value)
                            if compact_meta:
                                payload["last_event"]["purpose_meta"] = compact_meta

                live_task_states[f"{phase_key}::{task_key}"] = payload

        if live_task_states:
            run_payload["live_task_states"] = live_task_states

    def _resolve_runtime_task_status_map(
        self,
        task_status_map: dict[str, Any],
        phase_key: str,
        task_key: str,
    ) -> tuple[str, str]:
        candidates: list[str] = [task_key, *self._runtime_task_aliases(phase_key, task_key)]
        seen: set[str] = set()
        for candidate in candidates:
            key = str(candidate or "").strip()
            if not key or key in seen:
                continue
            seen.add(key)
            item = task_status_map.get(key)
            if not isinstance(item, dict):
                continue
            value = str(item.get("status", "")).strip().lower()
            if value:
                return value, key
        return "", ""

    @staticmethod
    def _select_latest_event(events: list[dict[str, Any]]) -> dict[str, Any] | None:
        if not events:
            return None
        try:
            return max(events, key=lambda item: (str(item.get("ts", "")), str(item.get("id", ""))))
        except Exception:
            return events[-1]

    @staticmethod
    def _infer_live_task_status(*, phase_status: str, runtime_status: str, has_trace_events: bool) -> str:
        normalized_runtime = str(runtime_status or "").strip().lower()
        if normalized_runtime in {"success", "completed", "done"}:
            return "completed"
        if normalized_runtime in {"failed", "error"}:
            return "failed"
        if normalized_runtime in {"running", "in_progress", "in-review", "in_review", "started"}:
            return "running"
        normalized_phase = str(phase_status or "").strip().lower()
        if has_trace_events and normalized_phase in {"failed"}:
            return "failed"
        if has_trace_events and normalized_phase in {"completed"}:
            return "completed"
        if has_trace_events:
            return "running"
        if normalized_phase in {"completed"}:
            return "completed"
        if normalized_phase in {"failed"}:
            return "pending"
        if normalized_phase in {"running", "in_progress", "in_review"}:
            return "pending"
        return ""

    def delete_project(self, project_id: str) -> None:
        """Delete a project and its persisted directory."""
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
            self._save_state()
            logger.info("Web project deleted: project_id=%s", project_id)

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
                orchestrator = create_team(config, project_root=str(project_dir))
                project = Project(
                    project_id=project_id,
                    config=config,
                    orchestrator=orchestrator,
                    project_root=str(project_dir),
                )
                self._attach_langchain_runtime(project)
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
            logger.warning("Failed to load web state from %s: %s", self._state_path, exc)
            return
        if not isinstance(data, dict):
            logger.warning("Invalid web state format in %s: expected JSON object", self._state_path)
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
                    completed_at = item.get("completed_at")
                    try:
                        started = datetime.fromisoformat(str(started_at))
                    except Exception:
                        started = datetime.now(timezone.utc)
                    completed: datetime | None = None
                    if isinstance(completed_at, str) and completed_at:
                        try:
                            completed = datetime.fromisoformat(completed_at)
                        except Exception:
                            completed = None
                    status = str(item.get("status", ""))
                    if not status:
                        status = "completed" if item.get("phase_results") else "pending"
                    self._runs_by_project[project_id].append(
                        WorkflowRun(
                            run_id=str(item.get("run_id", "")),
                            requirement_text=str(item.get("requirement_text", "")),
                            started_at=started,
                            status=status,
                            completed_at=completed,
                            error=str(item.get("error", "")),
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
        # Atomic replace to avoid readers seeing partially written JSON.
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

    def _attach_langchain_runtime(self, project: Project) -> None:
        """Wrap project orchestrator with DeepOrchestrator for web workflows."""
        from ..langchain.deep_orchestrator import DeepOrchestrator

        if project.project_root and getattr(project.orchestrator, "project_root", None) != project.project_root:
            project.orchestrator.project_root = project.project_root  # type: ignore[assignment]

        if isinstance(project.orchestrator, DeepOrchestrator):
            wrapped = getattr(project.orchestrator, "orchestrator", None)
            if (
                project.project_root
                and wrapped is not None
                and getattr(wrapped, "project_root", None) != project.project_root
            ):
                wrapped.project_root = project.project_root
            return
        project.orchestrator = DeepOrchestrator.from_orchestrator(  # type: ignore[assignment]
            project.orchestrator,
            config=project.config,
        )

    def _build_workflow_nodes(self, project: Project) -> list[dict[str, Any]]:
        """Build workflow node metadata for UI based on active runtime."""
        from ..langchain.agent_node import PHASE_SKILL_PLAYBOOK, SKILL_INPUT_HINTS
        from ..langchain.deep_orchestrator import DeepOrchestrator
        from ..langchain.state import PHASE_AGENT_MAP, WORKFLOW_PHASES

        if isinstance(project.orchestrator, DeepOrchestrator):
            available_agents = set(project.orchestrator.agents.keys())
            nodes: list[dict[str, Any]] = []
            for phase in WORKFLOW_PHASES:
                agent_name = PHASE_AGENT_MAP.get(phase, "")
                phase_skills = PHASE_SKILL_PLAYBOOK.get(agent_name, {}).get(phase, [])
                if agent_name not in available_agents:
                    tasks: list[str] = []
                else:
                    registered = set(project.orchestrator.agents[agent_name].skills.keys())
                    tasks = [f"{agent_name}.{skill}" for skill in phase_skills if skill in registered]
                agent_tasks = self._group_tasks_by_agent(tasks, SKILL_INPUT_HINTS)
                agent_tasks = self._expand_phase_subagents(phase, tasks, agent_tasks)
                nodes.append(
                    {
                        "name": phase,
                        "tasks": tasks,
                        "agent_tasks": agent_tasks,
                        "review_gate": None,
                    }
                )
            return nodes

        default_workflow = WorkflowEngine.create_default_workflow()
        return [
            {
                "name": phase.name,
                "tasks": phase_task_keys,
                "agent_tasks": self._expand_phase_subagents(
                    phase.name,
                    phase_task_keys,
                    self._group_tasks_by_agent(phase_task_keys, {}),
                ),
                "review_gate": (
                    f"{phase.review_gate.reviewer_agent}.{phase.review_gate.review_skill}"
                    if phase.review_gate
                    else None
                ),
            }
            for phase in default_workflow.phases
            for phase_task_keys in [[f"{task.agent}.{task.skill}" for task in phase.tasks]]
        ]

    @staticmethod
    def _group_tasks_by_agent(
        task_keys: list[str],
        input_hints: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        ordered_agents: list[str] = []

        for task_key in task_keys:
            agent, sep, task_name = str(task_key).partition(".")
            agent_key = agent or "unknown"
            task_label = task_name if sep else str(task_key)
            if agent_key not in grouped:
                grouped[agent_key] = []
                ordered_agents.append(agent_key)
            grouped[agent_key].append(
                {
                    "key": str(task_key),
                    "name": task_label,
                    "input_hints": list(input_hints.get(task_label, [])),
                }
            )

        return [{"agent": agent, "tasks": grouped[agent]} for agent in ordered_agents]

    @staticmethod
    def _expand_phase_subagents(
        phase: str,
        task_keys: list[str],
        base_agent_tasks: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if phase == "requirements" and "product_manager.deep_product_workflow" in task_keys:
            return [
                {
                    "agent": "product_designer",
                    "tasks": [
                        {
                            "key": "product_manager.deep_product_workflow.step1",
                            "name": "raw_requirement_expansion",
                            "input_hints": ["raw_requirements", "user_memory"],
                        },
                        {
                            "key": "product_manager.deep_product_workflow.step2.design",
                            "name": "product_design_iterations",
                            "input_hints": ["expanded_understanding", "review_feedback"],
                        },
                        {
                            "key": "product_manager.deep_product_workflow.step3.design",
                            "name": "system_requirement_design_iterations",
                            "input_hints": ["system_design_doc", "review_feedback"],
                        },
                    ],
                },
                {
                    "agent": "product_reviewer",
                    "tasks": [
                        {
                            "key": "product_manager.deep_product_workflow.step2.review",
                            "name": "product_design_review",
                            "input_hints": ["expanded_understanding", "system_design_doc"],
                        },
                        {
                            "key": "product_manager.deep_product_workflow.step3.review",
                            "name": "system_requirement_review",
                            "input_hints": ["system_design_doc", "system_requirements_doc"],
                        },
                    ],
                },
            ]

        if phase == "design" and "architect.deep_architecture_workflow" in task_keys:
            return [
                {
                    "agent": "architect",
                    "tasks": [
                        {
                            "key": "architect.deep_architecture_workflow.step1.design",
                            "name": "system_architecture_design_iterations",
                            "input_hints": ["system_design_doc", "system_requirements_doc", "review_feedback"],
                        },
                        {
                            "key": "architect.deep_architecture_workflow.step2_3",
                            "name": "bootstrap_and_subsystem_split",
                            "input_hints": ["system_architecture_doc", "system_requirements_doc"],
                        },
                    ],
                },
                {
                    "agent": "architecture_reviewer[*]",
                    "tasks": [
                        {
                            "key": "architect.deep_architecture_workflow.step1.review",
                            "name": "system_architecture_review",
                            "input_hints": ["system_architecture_doc", "system_requirements_doc"],
                        }
                    ],
                },
                {
                    "agent": "subsystem_reviewer[*]",
                    "tasks": [
                        {
                            "key": "architect.deep_architecture_workflow.step4.review",
                            "name": "subsystem_detail_review",
                            "input_hints": ["subsystem_detail_design_doc", "system_requirements_doc"],
                        }
                    ],
                },
                {
                    "agent": "subsystem_expert[*]",
                    "tasks": [
                        {
                            "key": "architect.deep_architecture_workflow.step4.design",
                            "name": "subsystem_detail_design_iterations",
                            "input_hints": ["subsystem_info", "system_requirements_doc", "system_architecture_doc"],
                        },
                        {
                            "key": "architect.deep_architecture_workflow.step5",
                            "name": "subsystem_code_init_and_api_definition",
                            "input_hints": ["subsystem_detail_design_doc"],
                        },
                    ],
                },
            ]

        if phase == "implementation" and "developer.deep_developer_workflow" in task_keys:
            return [
                {
                    "agent": "coder[*]",
                    "tasks": [
                        {
                            "key": "developer.deep_developer_workflow.step1",
                            "name": "subsystem_task_assignment",
                            "input_hints": ["system_architecture_doc", "subsystem_detail_design_docs"],
                        },
                        {
                            "key": "developer.deep_developer_workflow.step2.develop",
                            "name": "subsystem_batch_sr_group_parallel_development_rounds",
                            "input_hints": ["subsystem_detail_design_doc", "sr_grouped_fn_info", "existing_code"],
                        },
                        {
                            "key": "developer.deep_developer_workflow.step2.merge",
                            "name": "subsystem_batch_merge_after_review_rounds",
                            "input_hints": ["commit_info", "revision_feedback"],
                        },
                    ],
                },
                {
                    "agent": "commiter[*]",
                    "tasks": [
                        {
                            "key": "developer.deep_developer_workflow.step2.review",
                            "name": "subsystem_batch_code_and_test_review_rounds",
                            "input_hints": ["subsystem_detail_design_doc", "sr_grouped_fn_info", "workspace_changes"],
                        },
                        {
                            "key": "developer.deep_developer_workflow.step2.revision",
                            "name": "revision_feedback_record",
                            "input_hints": ["review_comments", "revision_history"],
                        },
                    ],
                },
            ]

        return base_agent_tasks


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
    runtime_worker_registry = WorkerRegistry()
    runtime_memory_manager = InMemoryMemoryManager()
    runtime_master_agent = MasterAgent(
        worker_registry=runtime_worker_registry,
        memory_manager=runtime_memory_manager,
    )
    app.state.master_agent = runtime_master_agent
    app.state.agent_runtime = AgentRuntime(
        master_agent=runtime_master_agent,
        worker_registry=runtime_worker_registry,
        memory_manager=runtime_memory_manager,
    )
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

    def runtime_principal_from_request(request: Request) -> Principal:
        user = require_login(request)
        role = str(user.get("role", "")).lower()
        permissions = set(str(p) for p in user.get("permissions", []))
        roles: list[str] = []
        if role in {"super_admin", "admin"} or "super_admin" in permissions:
            roles.append("Admin")
        if role in {"operator"}:
            roles.append("Operator")
        if role in {"viewer"}:
            roles.append("Viewer")
        if not roles:
            roles = ["Viewer"]
        return Principal(
            user_id=str(user.get("id", "web-user")),
            tenant_id="web-default",
            roles=roles,
            attributes={"provider": user.get("provider", "unknown"), "email": user.get("email", "")},
        )

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

    @app.get("/runtime/tasks/{task_id}", response_class=HTMLResponse)
    async def runtime_task_detail_page(request: Request, task_id: str) -> HTMLResponse:
        user = request.session.get("user")
        if not user:
            return RedirectResponse(url="/login", status_code=HTTP_303_SEE_OTHER)
        principal = runtime_principal_from_request(request)
        runtime: AgentRuntime = app.state.agent_runtime
        try:
            task_payload = runtime.get_task(task_id, principal=principal)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

        plan = task_payload.get("plan") or {}
        plan_meta = plan.get("metadata") if isinstance(plan, dict) else {}
        selected_process = (plan_meta or {}).get("selected_process")
        process_context = (plan_meta or {}).get("process_context") or {}
        process_steps = process_context.get("steps", []) if isinstance(process_context, dict) else []
        node_results = task_payload.get("node_results", {})
        tasks = plan.get("tasks", []) if isinstance(plan, dict) else []

        return templates.TemplateResponse(
            "runtime_task_detail.html",
            {
                "request": request,
                "user": user,
                "task": task_payload,
                "plan": plan,
                "plan_meta": plan_meta or {},
                "selected_process": selected_process,
                "process_steps": process_steps,
                "plan_tasks": tasks,
                "node_results": node_results,
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
            project_id, run_id = service.create_project_with_initial_run(
                project_name=project_name.strip(),
                development_mode=development_mode,
                agent_models=agent_models,
                initial_requirement=initial_requirement,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if run_id:
            return RedirectResponse(
                url=f"/projects/{project_id}/runs/{run_id}",
                status_code=HTTP_303_SEE_OTHER,
            )
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
        if section not in {"models", "agents", "workspace", "workflow", "logging", "json"}:
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
            project_id, run_id = service.create_project_with_initial_run(
                project_name=project_name,
                development_mode=development_mode,
                agent_models={str(k): str(v) for k, v in agent_models.items()},
                initial_requirement=initial_requirement,
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

    @app.get("/api/projects/{project_id}/runs/{run_id}/task-logs")
    async def api_get_task_logs(
        request: Request,
        project_id: str,
        run_id: str,
        phase_key: str,
        task_key: str,
        limit: int = 300,
    ) -> dict[str, Any]:
        require_login(request)
        payload = service.get_task_logs(
            project_id,
            run_id,
            phase_key=phase_key,
            task_key=task_key,
            limit=max(20, min(limit, 1000)),
        )
        if payload is None:
            raise HTTPException(status_code=404, detail="Run not found")
        return payload

    @app.get("/api/projects/{project_id}/runs/{run_id}/task-state")
    async def api_get_task_state(
        request: Request,
        project_id: str,
        run_id: str,
        phase_key: str,
        task_key: str,
    ) -> dict[str, Any]:
        require_login(request)
        payload = service.get_task_state(project_id, run_id, phase_key=phase_key, task_key=task_key)
        if payload is None:
            raise HTTPException(status_code=404, detail="Task state not found")
        return payload

    @app.post("/api/projects/{project_id}/runs/{run_id}/task-retries")
    async def api_post_task_retry(request: Request, project_id: str, run_id: str) -> dict[str, Any]:
        require_login(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        phase_key = str(payload.get("phase_key", "")).strip()
        task_key = str(payload.get("task_key", "")).strip()
        mode = str(payload.get("mode", "current")).strip().lower() or "current"
        if not phase_key or not task_key:
            raise HTTPException(status_code=400, detail="phase_key and task_key are required")
        try:
            return service.retry_task(project_id, run_id, phase_key=phase_key, task_key=task_key, mode=mode)
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

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
            if "workflow" in payload:
                workflow_cfg = payload.get("workflow", {})
                if not isinstance(workflow_cfg, dict):
                    raise HTTPException(status_code=400, detail="workflow must be an object")
                service.save_global_workflow_data(workflow_cfg)
            if not {"models", "agents", "agent_model_selection", "workspace", "workflow", "logging"} & set(
                payload.keys()
            ):
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

    # Runtime API (independent from project workflow APIs)
    @app.post("/api/runtime/tasks")
    async def api_runtime_submit_task(request: Request) -> dict[str, Any]:
        principal = runtime_principal_from_request(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        prompt = str(payload.get("prompt", "")).strip()
        if not prompt:
            raise HTTPException(status_code=400, detail="prompt is required")
        run_sync = bool(payload.get("run_sync", True))
        constraints = payload.get("constraints", {})
        metadata = payload.get("metadata", {})
        if not isinstance(constraints, dict):
            raise HTTPException(status_code=400, detail="constraints must be an object")
        if not isinstance(metadata, dict):
            raise HTTPException(status_code=400, detail="metadata must be an object")
        task_plan = constraints.get("task_plan")
        if task_plan is not None:
            if not isinstance(task_plan, dict):
                raise HTTPException(status_code=400, detail="constraints.task_plan must be an object")
            try:
                validate_task_plan_payload(task_plan)
            except Exception as exc:
                raise HTTPException(status_code=400, detail=f"Invalid task plan: {exc}") from exc
        runtime: AgentRuntime = app.state.agent_runtime
        try:
            task_id = runtime.submit_task(
                prompt=prompt,
                principal=principal,
                task_name=str(payload.get("task_name", "")).strip() or None,
                constraints=constraints,
                metadata=metadata,
                run_sync=run_sync,
            )
        except RuntimeAuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        task_status = runtime.get_task_status(task_id, principal=principal)
        return {"task_id": task_id, "status": task_status["status"], "run_sync": run_sync}

    @app.get("/api/runtime/tasks/{task_id}")
    async def api_runtime_get_task(request: Request, task_id: str) -> dict[str, Any]:
        principal = runtime_principal_from_request(request)
        runtime: AgentRuntime = app.state.agent_runtime
        try:
            return runtime.get_task(task_id, principal=principal)
        except RuntimeAuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runtime/tasks/{task_id}/status")
    async def api_runtime_get_task_status(request: Request, task_id: str) -> dict[str, Any]:
        principal = runtime_principal_from_request(request)
        runtime: AgentRuntime = app.state.agent_runtime
        try:
            return runtime.get_task_status(task_id, principal=principal)
        except RuntimeAuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runtime/tasks/{task_id}/result")
    async def api_runtime_get_task_result(request: Request, task_id: str) -> dict[str, Any]:
        principal = runtime_principal_from_request(request)
        runtime: AgentRuntime = app.state.agent_runtime
        try:
            return runtime.get_task_result(task_id, principal=principal)
        except RuntimeAuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runtime/tasks/{task_id}/logs")
    async def api_runtime_get_task_logs(request: Request, task_id: str) -> dict[str, Any]:
        principal = runtime_principal_from_request(request)
        runtime: AgentRuntime = app.state.agent_runtime
        try:
            return {"task_id": task_id, "events": runtime.get_task_logs(task_id, principal=principal)}
        except RuntimeAuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/runtime/tasks/{task_id}/report")
    async def api_runtime_get_task_report(request: Request, task_id: str) -> dict[str, Any]:
        principal = runtime_principal_from_request(request)
        runtime: AgentRuntime = app.state.agent_runtime
        try:
            return runtime.get_task_report(task_id, principal=principal)
        except RuntimeAuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/runtime/tasks/{task_id}/retry-node")
    async def api_runtime_retry_node(request: Request, task_id: str) -> dict[str, Any]:
        principal = runtime_principal_from_request(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        node_id = str(payload.get("node_id", "")).strip()
        if not node_id:
            raise HTTPException(status_code=400, detail="node_id is required")
        runtime: AgentRuntime = app.state.agent_runtime
        try:
            return runtime.retry_node(task_id, node_id, principal=principal)
        except RuntimeAuthorizationError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/runtime/plans/validate")
    async def api_runtime_validate_plan(request: Request) -> dict[str, Any]:
        runtime_principal_from_request(request)
        payload = await request.json()
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid JSON body")
        plan = payload.get("plan")
        if not isinstance(plan, dict):
            raise HTTPException(status_code=400, detail="plan must be an object")
        try:
            validate_task_plan_payload(plan)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"valid": True}

    return app
