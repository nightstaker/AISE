"""Project Manager — runtime-owned lifecycle for Web-driven projects.

This is the AI-First path forward: the web layer creates projects through
this manager, which will eventually dispatch the ``product_manager`` agent
to do environment preparation (directory scaffolding, git init, phase
tagging, per-phase summaries). Legacy callers (``MultiProjectSession``
on the ``aise multi-project`` CLI) still use the older
``aise.core.project_manager.ProjectManager`` and are intentionally not
migrated here — the two diverge as this file gains AI-First behaviors.

Scope of this file (PR-a, pure refactor — no behavior change):

- ``ProjectManager`` lifecycle — create / get / list / pause / resume /
  complete / delete — carried over verbatim from ``core.project_manager``.
- ``_prepare_project_root`` — still a plain ``mkdir`` of the standard
  sub-directories. Git init and other LLM-driven scaffolding land in
  a follow-up PR (PR-b).

What is intentionally *not* here (compared to ``core.project_manager``):

- ``run_project_workflow`` / ``_normalize_*_workflow_result`` / phase
  key splitters / SDLC-phase constants — these serve the legacy
  ``MultiProjectSession`` path, not the web runtime, and stay in the
  core module.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..config import ProjectConfig
from ..core.agent import AgentRole
from ..core.project import Project, ProjectStatus
from ..utils.logging import get_logger

if TYPE_CHECKING:
    pass

logger = get_logger(__name__)


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
        """Create and return the filesystem root for a project.

        Only the top-level directory is created synchronously — just
        enough to let ``create_project`` drop ``project_config.json``
        in. The standard sub-directories (``docs/``, ``src/``,
        ``tests/``, ``scripts/``, ``config/``, ``artifacts/``,
        ``trace/``) are now created by the product-manager agent during
        the SCAFFOLDING phase so the layout can vary by project type
        (e.g. a Go service has no ``tests/`` — it uses ``*_test.go``
        alongside sources). The safety net (PR-c) pins the minimum
        expected directories after scaffolding completes.
        """
        safe_name = "".join(c.lower() if c.isalnum() else "-" for c in project_name).strip("-")
        safe_name = "-".join(filter(None, safe_name.split("-"))) or "project"
        project_root = self._projects_root / f"{project_id}-{safe_name}"
        project_root.mkdir(parents=True, exist_ok=True)
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
