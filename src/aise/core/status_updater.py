"""Utility for updating element status in the status tracking artifact."""

from __future__ import annotations

from datetime import datetime, timezone

from .artifact import ArtifactStore, ArtifactType


class StatusUpdater:
    """Update element status in the STATUS_TRACKING artifact in-place.

    This is used by development sessions to mark elements as in-progress
    or completed as they work through the task queue.
    """

    def __init__(self, artifact_store: ArtifactStore) -> None:
        self._store = artifact_store

    def mark_in_progress(self, element_id: str) -> bool:
        """Mark an element as 进行中 with the current timestamp.

        Returns:
            True if the element was found and updated, False otherwise.
        """
        return self._update_element(element_id, "进行中")

    def mark_completed(self, element_id: str) -> bool:
        """Mark an element as 已完成 with the current timestamp.

        Returns:
            True if the element was found and updated, False otherwise.
        """
        return self._update_element(element_id, "已完成")

    def touch(self, element_id: str) -> bool:
        """Update the timestamp of an element without changing its status.

        Returns:
            True if the element was found and updated, False otherwise.
        """
        artifact = self._store.get_latest(ArtifactType.STATUS_TRACKING)
        if artifact is None:
            return False

        elements = artifact.content.get("elements", {})
        if element_id not in elements:
            return False

        elements[element_id]["last_updated"] = datetime.now(timezone.utc).isoformat()
        return True

    def _update_element(self, element_id: str, status: str) -> bool:
        """Update an element's status and timestamp."""
        artifact = self._store.get_latest(ArtifactType.STATUS_TRACKING)
        if artifact is None:
            return False

        elements = artifact.content.get("elements", {})
        if element_id not in elements:
            return False

        elements[element_id]["status"] = status
        elements[element_id]["last_updated"] = datetime.now(timezone.utc).isoformat()
        return True
