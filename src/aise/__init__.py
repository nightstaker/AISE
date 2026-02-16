"""AISE - Multi-Agent Software Development Team."""

__version__ = "0.1.0"

from .config import ProjectConfig
from .core import (
    MultiProjectSession,
    Project,
    ProjectManager,
    ProjectStatus,
)
from .main import (
    create_team,
    run_project,
    start_demand_session,
    start_multi_project_session,
    start_whatsapp_session,
)

__all__ = [
    "ProjectConfig",
    "Project",
    "ProjectManager",
    "ProjectStatus",
    "MultiProjectSession",
    "create_team",
    "run_project",
    "start_demand_session",
    "start_multi_project_session",
    "start_whatsapp_session",
]
