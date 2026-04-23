"""Project container for multi-project management."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import ProjectConfig
    from .orchestrator import Orchestrator


class ProjectStatus(Enum):
    """Status of a project in its lifecycle."""

    SCAFFOLDING = "scaffolding"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ARCHIVED = "archived"
    SCAFFOLDING_FAILED = "scaffolding_failed"


class Project:
    """Isolated container for a single project with its own agent team.

    Each Project maintains complete isolation from other projects via:
    - Dedicated Orchestrator instance
    - Dedicated MessageBus (owned by Orchestrator)
    - Dedicated ArtifactStore (owned by Orchestrator)

    This ensures messages and artifacts cannot leak across project boundaries.
    """

    def __init__(
        self,
        project_id: str,
        config: ProjectConfig,
        orchestrator: Orchestrator | None = None,
        project_root: str | None = None,
    ) -> None:
        """Initialize a project container.

        Args:
            project_id: Unique identifier for this project
            config: Project configuration (includes name, GitHub settings, agent counts)
            orchestrator: Optional orchestrator instance (None for runtime-managed projects)
            project_root: Optional root directory path for persisted project files
        """
        self.project_id = project_id
        self.config = config
        self.orchestrator = orchestrator
        self.project_root = project_root
        # Projects now start in SCAFFOLDING — the product-manager agent
        # is dispatched asynchronously to create the directory tree,
        # initialize git, and seed ``.gitignore``. The status flips to
        # ACTIVE once scaffolding succeeds, or SCAFFOLDING_FAILED if it
        # does not. Callers that need a ready-to-dispatch project
        # should wait for status != SCAFFOLDING before running
        # requirements (see ``WebProjectService.run_requirement``).
        self.status = ProjectStatus.SCAFFOLDING
        self.scaffolding_error: str | None = None
        self.created_at = datetime.now(timezone.utc)
        self.updated_at = self.created_at

    @property
    def project_name(self) -> str:
        """Get the project name from config."""
        return self.config.project_name

    @property
    def agent_count(self) -> int:
        """Get total number of agents in this project."""
        if self.orchestrator is None:
            return 0
        return len(self.orchestrator.agents)

    @property
    def development_mode(self) -> str:
        """Get the development mode (local or github)."""
        if hasattr(self.config, "development_mode"):
            return self.config.development_mode
        # Fallback to checking GitHub config
        return "github" if self.config.github.is_configured else "local"

    @property
    def process_type(self) -> str:
        """Get the development process (waterfall or agile)."""
        value = getattr(self.config, "process_type", "waterfall")
        return value if value in ("waterfall", "agile") else "waterfall"

    def finish_scaffolding(self) -> None:
        """Flip from SCAFFOLDING to ACTIVE on a successful scaffold.

        Idempotent: calling this on an already-active project is a
        no-op. Callers that beat the scaffolding thread to the status
        check (e.g. via an aggressive poll) won't regress a
        COMPLETED / PAUSED / ARCHIVED project.
        """
        if self.status == ProjectStatus.SCAFFOLDING:
            self.status = ProjectStatus.ACTIVE
            self.scaffolding_error = None
            self.updated_at = datetime.now(timezone.utc)

    def fail_scaffolding(self, error: str) -> None:
        """Mark the project as SCAFFOLDING_FAILED with an error blurb.

        Only takes effect while the project is still in SCAFFOLDING —
        after that, status transitions are driven by the workflow
        machinery and scaffolding failures become moot.
        """
        if self.status == ProjectStatus.SCAFFOLDING:
            self.status = ProjectStatus.SCAFFOLDING_FAILED
            self.scaffolding_error = error[:500] if error else "unknown scaffolding failure"
            self.updated_at = datetime.now(timezone.utc)

    def pause(self) -> None:
        """Pause the project (stop accepting new work)."""
        self.status = ProjectStatus.PAUSED
        self.updated_at = datetime.now(timezone.utc)

    def resume(self) -> None:
        """Resume a paused project."""
        if self.status == ProjectStatus.PAUSED:
            self.status = ProjectStatus.ACTIVE
            self.updated_at = datetime.now(timezone.utc)

    def complete(self) -> None:
        """Mark the project as completed."""
        self.status = ProjectStatus.COMPLETED
        self.updated_at = datetime.now(timezone.utc)

    def archive(self) -> None:
        """Archive the project (for cleanup/memory management)."""
        self.status = ProjectStatus.ARCHIVED
        self.updated_at = datetime.now(timezone.utc)

    def get_info(self) -> dict:
        """Get project information as a dictionary.

        Returns:
            Dictionary containing project metadata
        """
        return {
            "project_id": self.project_id,
            "project_name": self.project_name,
            "status": self.status.value,
            "development_mode": self.development_mode,
            "process_type": self.process_type,
            "agent_count": self.agent_count,
            "project_root": self.project_root,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "scaffolding_error": self.scaffolding_error,
        }

    def __repr__(self) -> str:
        """String representation of the project."""
        return (
            f"Project(id={self.project_id!r}, "
            f"name={self.project_name!r}, "
            f"status={self.status.value}, "
            f"mode={self.development_mode}, "
            f"agents={self.agent_count})"
        )
