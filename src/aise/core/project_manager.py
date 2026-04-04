"""Project Manager for managing multiple concurrent projects."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import ProjectConfig
from ..core.agent import AgentRole
from ..utils.logging import get_logger
from .project import Project, ProjectStatus

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)

_SDLC_PHASES = ["requirements", "design", "implementation", "testing"]
_PRIMARY_SKILL_BY_PHASE: dict[str, str] = {
    "requirements": "deep_product_workflow",
    "design": "deep_architecture_workflow",
    "implementation": "deep_developer_workflow",
    "testing": "test_plan_design",
}


class ProjectManager:
    """Manages multiple concurrent projects and their lifecycle.

    The ProjectManager creates and coordinates multiple isolated projects,
    each with its own team of agents, message bus, and artifact store.
    """

    def __init__(
        self,
        *,
        projects_root: str | Path = "projects",
        global_config_path: str | Path = "config/global_project_config.json",
    ) -> None:
        """Initialize the project manager."""
        self._projects: dict[str, Project] = {}
        self._project_counter = 0
        # Resolve once so background threads are not affected by process cwd changes.
        self._projects_root = Path(projects_root).resolve()
        self._global_config_path = Path(global_config_path).resolve()
        self._global_config = self._load_global_config()
        logger.info(
            "ProjectManager initialized: projects_root=%s global_config=%s",
            self._projects_root,
            self._global_config_path,
        )

    def create_project(
        self,
        project_name: str,
        config: ProjectConfig | None = None,
        agent_counts: dict[AgentRole, int] | None = None,
    ) -> str:
        """Create a new project with its own agent team.

        Args:
            project_name: Human-readable project name
            config: Optional project configuration (GitHub settings, model config, etc.)
            agent_counts: Optional dict mapping AgentRole to count
                         Example: {AgentRole.DEVELOPER: 3, AgentRole.QA_ENGINEER: 2}
                         Default: 1 agent per role

        Returns:
            Unique project ID for referencing this project

        Example:
            ```python
            pm = ProjectManager()
            project_id = pm.create_project(
                "E-commerce Platform",
                config=ProjectConfig(development_mode="github"),
                agent_counts={AgentRole.DEVELOPER: 3, AgentRole.QA_ENGINEER: 2}
            )
            ```
        """
        # Generate unique project ID
        project_id = f"project_{self._project_counter}"
        self._project_counter += 1

        # Prepare configuration (inherit global defaults by default)
        config = config or self.create_default_project_config(project_name)
        config.project_name = project_name

        # Persist project directory and config snapshot
        project_root = self._prepare_project_root(project_id, project_name)
        config.to_json_file(project_root / "project_config.json")

        # Create isolated orchestrator with agents
        # Import locally to avoid circular dependency
        from ..main import create_team

        orchestrator = create_team(config, agent_counts)
        orchestrator.project_root = str(project_root)

        # Create project container
        project = Project(
            project_id=project_id,
            config=config,
            orchestrator=orchestrator,
            project_root=str(project_root),
        )

        # Store project
        self._projects[project_id] = project
        logger.info(
            "Project created: project_id=%s name=%s mode=%s agents=%d",
            project_id,
            project_name,
            project.development_mode,
            project.agent_count,
        )

        return project_id

    def create_default_project_config(self, project_name: str) -> ProjectConfig:
        """Create a project config by inheriting global defaults."""
        config = ProjectConfig.from_dict(self._global_config.to_dict())
        config.project_name = project_name
        return config

    def _load_global_config(self) -> ProjectConfig:
        """Load global config if available, otherwise use built-in defaults."""
        if not self._global_config_path.exists():
            logger.info("Global config not found, using defaults: path=%s", self._global_config_path)
            return ProjectConfig()
        logger.info("Loading global config: path=%s", self._global_config_path)
        return ProjectConfig.from_json_file(self._global_config_path)

    def _prepare_project_root(self, project_id: str, project_name: str) -> Path:
        """Create and return the filesystem root for a project."""
        safe_name = "".join(c.lower() if c.isalnum() else "-" for c in project_name).strip("-")
        safe_name = "-".join(filter(None, safe_name.split("-"))) or "project"
        project_root = self._projects_root / f"{project_id}-{safe_name}"
        project_root.mkdir(parents=True, exist_ok=True)
        for subdir in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace"):
            (project_root / subdir).mkdir(parents=True, exist_ok=True)
        return project_root

    def get_project(self, project_id: str) -> Project | None:
        """Get a project by its ID.

        Args:
            project_id: The project ID

        Returns:
            Project instance or None if not found
        """
        return self._projects.get(project_id)

    def list_projects(
        self,
        status_filter: ProjectStatus | None = None,
    ) -> list[Project]:
        """List all projects, optionally filtered by status.

        Args:
            status_filter: Optional status to filter by (ACTIVE, PAUSED, COMPLETED, ARCHIVED)

        Returns:
            List of Project instances
        """
        if status_filter is None:
            return list(self._projects.values())

        return [p for p in self._projects.values() if p.status == status_filter]

    def delete_project(self, project_id: str) -> bool:
        """Delete a project and clean up its resources.

        Args:
            project_id: The project ID to delete

        Returns:
            True if project was deleted, False if not found
        """
        if project_id in self._projects:
            project = self._projects[project_id]
            # Archive before deletion for cleanup
            project.archive()
            del self._projects[project_id]
            return True
        return False

    def run_project_workflow(
        self,
        project_id: str,
        requirements: dict[str, Any],
        progress_callback: Any = None,
    ) -> list[dict[str, Any]]:
        """Run the AI-planned dynamic workflow for a specific project.

        Uses AIPlanner to dynamically select processes and generate an
        execution plan based on the actual requirements, instead of
        following a fixed 4-phase pipeline.

        Falls back to the classic static workflow if dynamic planning
        is unavailable or fails.

        Args:
            project_id: The project ID
            requirements: Project requirements (dict with "raw_requirements" key)

        Returns:
            List of phase results from the workflow execution

        Raises:
            ValueError: If project not found
        """
        project = self.get_project(project_id)
        if project is None:
            raise ValueError(f"Project {project_id} not found")

        logger.info("Project workflow started: project_id=%s name=%s", project_id, project.project_name)
        orchestrator = project.orchestrator

        # --- AI-First path: dynamic workflow via AIPlanner ---
        base_orchestrator = getattr(orchestrator, "orchestrator", orchestrator)
        if hasattr(base_orchestrator, "run_dynamic_workflow"):
            try:
                # Get an LLM client from any registered agent for the planner
                llm_client = self._get_planner_llm_client(base_orchestrator)
                logger.info(
                    "Using AI-First dynamic workflow: project_id=%s name=%s",
                    project_id,
                    project.project_name,
                )
                # Reuse preview plan if available to avoid regenerating
                preview_plan = getattr(project, "_dynamic_plan", None)
                dynamic_result = base_orchestrator.run_dynamic_workflow(
                    project_input=requirements,
                    project_name=project.project_name,
                    llm_client=llm_client,
                    progress_callback=progress_callback,
                    existing_plan=preview_plan,
                )
                # Store the dynamic plan on the project for UI access
                project._dynamic_plan = dynamic_result.get("plan")  # type: ignore[attr-defined]
                rows = self._normalize_dynamic_workflow_result(dynamic_result)
                if rows:
                    return rows
                logger.warning(
                    "Dynamic workflow returned empty result, falling back: project_id=%s",
                    project_id,
                )
            except Exception:
                logger.exception(
                    "Dynamic workflow failed, falling back to static: project_id=%s",
                    project_id,
                )

        # --- Fallback: DeepOrchestrator (LangGraph supervisor) ---
        if hasattr(orchestrator, "run_workflow"):
            deep_result = orchestrator.run_workflow(  # type: ignore[call-arg]
                requirements,
                project.project_name,
            )
            rows = self._normalize_deep_workflow_result(deep_result)
            if rows:
                return rows

        # --- Fallback: classic static workflow ---
        if hasattr(orchestrator, "run_default_workflow"):
            logger.warning(
                "Falling back to static default workflow: project_id=%s",
                project_id,
            )
            return orchestrator.run_default_workflow(  # type: ignore[no-any-return]
                requirements,
                project.project_name,
            )

        base_orch = getattr(orchestrator, "orchestrator", None)
        if base_orch is not None and hasattr(base_orch, "run_default_workflow"):
            return base_orch.run_default_workflow(  # type: ignore[no-any-return]
                requirements,
                project.project_name,
            )

        raise ValueError(f"Project {project_id} orchestrator does not support workflow execution")

    @staticmethod
    def _get_planner_llm_client(orchestrator: Any) -> Any:
        """Extract an LLM client from the orchestrator's registered agents."""
        agents = getattr(orchestrator, "_agents", {})
        for agent in agents.values():
            client = getattr(agent, "llm_client", None)
            if client is not None:
                return client
        return None

    def _normalize_dynamic_workflow_result(
        self,
        result: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Convert DynamicEngine output to the phase-result list shape for the UI."""
        if not isinstance(result, dict):
            return []

        step_results = result.get("step_results", [])
        plan = result.get("plan", {})

        # Group steps by their process's phase affinity
        phase_groups: dict[str, list[dict[str, Any]]] = {}
        for step in step_results:
            process_id = step.get("process", "")
            # Infer phase from the plan step
            phase = self._infer_phase_from_process(process_id, plan)
            if phase not in phase_groups:
                phase_groups[phase] = []
            phase_groups[phase].append(step)

        rows: list[dict[str, Any]] = []
        for phase, steps in phase_groups.items():
            tasks: dict[str, dict[str, Any]] = {}
            phase_status = "completed"
            for step in steps:
                task_key = f"{step.get('agent', 'unknown')}.{step.get('process', 'unknown')}"
                step_status = step.get("status", "unknown")
                tasks[task_key] = {
                    "status": "success" if step_status == "completed" else step_status,
                    "artifact_id": step.get("artifact_id"),
                    "duration": step.get("duration"),
                }
                if step_status == "running":
                    phase_status = "running"
                elif step_status == "pending" and phase_status == "completed":
                    phase_status = "pending"
                elif step_status not in {"completed", "skipped", "running", "pending"}:
                    phase_status = "failed"
            rows.append(
                {
                    "phase": phase,
                    "status": phase_status,
                    "tasks": tasks,
                }
            )
        return rows

    @staticmethod
    def _infer_phase_from_process(process_id: str, plan: dict[str, Any]) -> str:
        """Infer phase name from a process ID using the plan.

        Phase names MUST match what _build_dynamic_workflow_nodes uses,
        which is the step's 'phase' field (defaulting to process_id).
        This ensures phase_results keys align with workflow_nodes names
        so the UI can map progress correctly.
        """
        # Check plan steps for phase info — must match _build_dynamic_workflow_nodes logic
        for step in plan.get("steps", []):
            if step.get("process_id") == process_id:
                # Use same logic as _build_dynamic_workflow_nodes:
                # phase = step.get("phase", step.get("process_id", "unknown"))
                return step.get("phase", step.get("process_id", process_id))

        # Fallback: use process_id directly (matches _build_dynamic_workflow_nodes)
        return process_id

    def _normalize_deep_workflow_result(
        self,
        result: Any,
    ) -> list[dict[str, Any]]:
        """Convert DeepOrchestrator output to the legacy phase-result list shape."""
        if not isinstance(result, dict):
            return []

        phase_results_raw = result.get("phase_results", {})
        if not isinstance(phase_results_raw, dict):
            phase_results_raw = {}
        artifact_ids = result.get("artifact_ids", [])
        if not isinstance(artifact_ids, list):
            artifact_ids = []
        error_message = str(result.get("error", "")) if result.get("error") is not None else ""

        rows: list[dict[str, Any]] = []
        consumed: set[str] = set()

        for phase in _SDLC_PHASES:
            key = next((k for k in phase_results_raw if isinstance(k, str) and k.startswith(f"{phase}_")), "")
            if not key:
                continue
            consumed.add(key)
            agent = key[len(phase) + 1 :] if len(key) > len(phase) + 1 else "unknown_agent"
            status_value = str(phase_results_raw.get(key, ""))
            task_state = "success" if status_value == "completed" else "error"
            task_payload: dict[str, Any] = {"status": task_state}
            if artifact_ids:
                task_payload["artifact_id"] = str(artifact_ids[-1])
            if task_state == "error" and error_message:
                task_payload["error"] = error_message
            rows.append(
                {
                    "phase": phase,
                    "status": "completed" if task_state == "success" else "failed",
                    "tasks": self._build_phase_task_payload(agent, phase, task_payload),
                }
            )

        for key, value in phase_results_raw.items():
            if not isinstance(key, str) or key in consumed:
                continue
            phase, agent = self._split_phase_agent_key(key)
            status_value = str(value)
            task_state = "success" if status_value == "completed" else "error"
            task_payload = {"status": task_state}
            if task_state == "error" and error_message:
                task_payload["error"] = error_message
            rows.append(
                {
                    "phase": phase,
                    "status": "completed" if task_state == "success" else "failed",
                    "tasks": self._build_phase_task_payload(agent, phase, task_payload),
                }
            )

        if not rows and error_message:
            rows.append(
                {
                    "phase": "workflow",
                    "status": "failed",
                    "tasks": {
                        "deep_orchestrator.run_workflow": {
                            "status": "error",
                            "error": error_message,
                        }
                    },
                }
            )

        return rows

    def _split_phase_agent_key(self, key: str) -> tuple[str, str]:
        """Split '<phase>_<agent>' key into phase and agent parts."""
        for phase in _SDLC_PHASES:
            prefix = f"{phase}_"
            if key.startswith(prefix):
                agent = key[len(prefix) :] or "unknown_agent"
                return phase, agent
        if "_" in key:
            phase, agent = key.rsplit("_", 1)
            return phase or "unknown_phase", agent or "unknown_agent"
        return key, "unknown_agent"

    def _build_phase_task_payload(
        self,
        agent: str,
        phase: str,
        task_payload: dict[str, Any],
    ) -> dict[str, Any]:
        tasks = {f"{agent}.{phase}": dict(task_payload)}
        primary_skill = _PRIMARY_SKILL_BY_PHASE.get(phase)
        if primary_skill:
            tasks[f"{agent}.{primary_skill}"] = dict(task_payload)
        return tasks

    def pause_project(self, project_id: str) -> bool:
        """Pause a project (stop accepting new work).

        Args:
            project_id: The project ID

        Returns:
            True if project was paused, False if not found
        """
        project = self.get_project(project_id)
        if project:
            project.pause()
            return True
        return False

    def resume_project(self, project_id: str) -> bool:
        """Resume a paused project.

        Args:
            project_id: The project ID

        Returns:
            True if project was resumed, False if not found or not paused
        """
        project = self.get_project(project_id)
        if project and project.status == ProjectStatus.PAUSED:
            project.resume()
            return True
        return False

    def complete_project(self, project_id: str) -> bool:
        """Mark a project as completed.

        Args:
            project_id: The project ID

        Returns:
            True if project was marked complete, False if not found
        """
        project = self.get_project(project_id)
        if project:
            project.complete()
            return True
        return False

    def get_project_info(self, project_id: str) -> dict[str, Any] | None:
        """Get project information as a dictionary.

        Args:
            project_id: The project ID

        Returns:
            Dictionary with project metadata or None if not found
        """
        project = self.get_project(project_id)
        if project:
            return project.get_info()
        return None

    def get_all_projects_info(self) -> list[dict[str, Any]]:
        """Get information for all projects.

        Returns:
            List of project info dictionaries
        """
        return [project.get_info() for project in self._projects.values()]

    @property
    def project_count(self) -> int:
        """Get the total number of projects."""
        return len(self._projects)

    def __repr__(self) -> str:
        """String representation of the project manager."""
        return f"ProjectManager(projects={self.project_count})"
