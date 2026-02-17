"""Task queue for distributing development work to sessions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .artifact import ArtifactStore, ArtifactType


@dataclass
class DevTask:
    """A development task derived from the status tracking registry."""

    element_id: str
    element_type: str  # "architecture_requirement" or "function"
    description: str
    parent_id: str | None = None
    priority: int = 0  # Lower = higher priority


class TaskQueue:
    """Reads the status tracking artifact and produces pending development tasks.

    A task is eligible if:
    - Its status is "未开始" (not started), OR
    - Its status is "进行中" (in progress) but last_updated exceeds the stale threshold

    Tasks already claimed by active sessions (in ``exclude_ids``) are skipped.
    """

    def __init__(
        self,
        artifact_store: ArtifactStore,
        stale_threshold_minutes: int = 10,
    ) -> None:
        self._store = artifact_store
        self._stale_threshold = timedelta(minutes=stale_threshold_minutes)

    def get_pending_tasks(self, exclude_ids: set[str] | None = None) -> list[DevTask]:
        """Return all tasks eligible for development, sorted by priority.

        Args:
            exclude_ids: Element IDs currently being worked on by active sessions.

        Returns:
            List of DevTask sorted by priority (0 = highest) then element_id.
        """
        exclude = exclude_ids or set()
        status_artifact = self._store.get_latest(ArtifactType.STATUS_TRACKING)
        if status_artifact is None:
            return []

        elements: dict[str, Any] = status_artifact.content.get("elements", {})
        now = datetime.now(timezone.utc)
        tasks: list[DevTask] = []

        for element_id, element in elements.items():
            if element_id in exclude:
                continue

            # Only pick leaf-level items: ARs or FNs
            if element.get("type") not in ("architecture_requirement", "function"):
                continue

            status = element.get("status", "")

            if status == "未开始":
                tasks.append(
                    DevTask(
                        element_id=element_id,
                        element_type=element["type"],
                        description=element.get("description", ""),
                        parent_id=element.get("parent"),
                    )
                )
            elif status == "进行中":
                last_updated_str = element.get("last_updated", "")
                if last_updated_str:
                    try:
                        last_updated = datetime.fromisoformat(last_updated_str)
                    except ValueError:
                        continue
                    if (now - last_updated) > self._stale_threshold:
                        tasks.append(
                            DevTask(
                                element_id=element_id,
                                element_type=element["type"],
                                description=element.get("description", ""),
                                parent_id=element.get("parent"),
                                priority=1,
                            )
                        )
                else:
                    # No timestamp at all — treat as stale
                    tasks.append(
                        DevTask(
                            element_id=element_id,
                            element_type=element["type"],
                            description=element.get("description", ""),
                            parent_id=element.get("parent"),
                            priority=1,
                        )
                    )

        tasks.sort(key=lambda t: (t.priority, t.element_id))
        return tasks
