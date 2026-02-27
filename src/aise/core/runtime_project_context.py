"""Lightweight runtime-only project context (no Orchestrator/DeepOrchestrator)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .artifact import ArtifactStore


@dataclass(slots=True)
class RuntimeProjectContext:
    """Minimal container used by web/runtime project lifecycle.

    This context intentionally avoids constructing heavy orchestrator stacks.
    It provides only the fields accessed by current runtime-driven flows.
    """

    project_root: str | None = None
    artifact_store: ArtifactStore = field(default_factory=ArtifactStore)
    agents: dict[str, Any] = field(default_factory=dict)

