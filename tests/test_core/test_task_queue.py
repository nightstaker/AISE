"""Tests for the task queue."""

from datetime import datetime, timedelta, timezone

from aise.core.artifact import Artifact, ArtifactStore, ArtifactType
from aise.core.task_queue import DevTask, TaskQueue


def _make_status_artifact(elements: dict) -> Artifact:
    """Helper to create a STATUS_TRACKING artifact with given elements."""
    return Artifact(
        artifact_type=ArtifactType.STATUS_TRACKING,
        content={
            "project_name": "test",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "elements": elements,
            "summary": {},
        },
        producer="architect",
    )


class TestDevTask:
    def test_defaults(self):
        task = DevTask(element_id="AR-0001", element_type="architecture_requirement", description="desc")
        assert task.priority == 0
        assert task.parent_id is None


class TestTaskQueue:
    def test_empty_store_returns_no_tasks(self):
        store = ArtifactStore()
        queue = TaskQueue(store)
        assert queue.get_pending_tasks() == []

    def test_picks_not_started_tasks(self):
        store = ArtifactStore()
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Auth module",
                "status": "未开始",
                "parent": "SR-0001",
                "children": ["FN-001"],
            },
            "FN-001": {
                "type": "function",
                "description": "Login function",
                "status": "未开始",
                "parent": "AR-0001",
                "children": [],
            },
        }
        store.store(_make_status_artifact(elements))
        queue = TaskQueue(store)

        tasks = queue.get_pending_tasks()
        assert len(tasks) == 2
        assert tasks[0].element_id == "AR-0001"
        assert tasks[1].element_id == "FN-001"

    def test_ignores_non_leaf_types(self):
        store = ArtifactStore()
        elements = {
            "SF-001": {
                "type": "system_feature",
                "description": "Feature A",
                "status": "未开始",
                "parent": None,
                "children": ["SR-0001"],
            },
            "SR-0001": {
                "type": "system_requirement",
                "description": "Requirement A",
                "status": "未开始",
                "parent": "SF-001",
                "children": ["AR-0001"],
            },
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "AR A",
                "status": "未开始",
                "parent": "SR-0001",
                "children": [],
            },
        }
        store.store(_make_status_artifact(elements))
        queue = TaskQueue(store)

        tasks = queue.get_pending_tasks()
        # Only AR should be returned, not SF or SR
        assert len(tasks) == 1
        assert tasks[0].element_id == "AR-0001"

    def test_picks_stale_in_progress_tasks(self):
        store = ArtifactStore()
        stale_time = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Stale task",
                "status": "进行中",
                "parent": None,
                "children": [],
                "last_updated": stale_time,
            },
        }
        store.store(_make_status_artifact(elements))
        queue = TaskQueue(store, stale_threshold_minutes=10)

        tasks = queue.get_pending_tasks()
        assert len(tasks) == 1
        assert tasks[0].priority == 1

    def test_ignores_fresh_in_progress_tasks(self):
        store = ArtifactStore()
        fresh_time = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Fresh task",
                "status": "进行中",
                "parent": None,
                "children": [],
                "last_updated": fresh_time,
            },
        }
        store.store(_make_status_artifact(elements))
        queue = TaskQueue(store, stale_threshold_minutes=10)

        tasks = queue.get_pending_tasks()
        assert len(tasks) == 0

    def test_ignores_completed_tasks(self):
        store = ArtifactStore()
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Done",
                "status": "已完成",
                "parent": None,
                "children": [],
            },
        }
        store.store(_make_status_artifact(elements))
        queue = TaskQueue(store)

        tasks = queue.get_pending_tasks()
        assert len(tasks) == 0

    def test_excludes_active_session_ids(self):
        store = ArtifactStore()
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Task A",
                "status": "未开始",
                "parent": None,
                "children": [],
            },
            "AR-0002": {
                "type": "architecture_requirement",
                "description": "Task B",
                "status": "未开始",
                "parent": None,
                "children": [],
            },
        }
        store.store(_make_status_artifact(elements))
        queue = TaskQueue(store)

        tasks = queue.get_pending_tasks(exclude_ids={"AR-0001"})
        assert len(tasks) == 1
        assert tasks[0].element_id == "AR-0002"

    def test_priority_ordering(self):
        store = ArtifactStore()
        stale_time = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
        elements = {
            "FN-002": {
                "type": "function",
                "description": "Stale task",
                "status": "进行中",
                "parent": None,
                "children": [],
                "last_updated": stale_time,
            },
            "FN-001": {
                "type": "function",
                "description": "Fresh not started",
                "status": "未开始",
                "parent": None,
                "children": [],
            },
        }
        store.store(_make_status_artifact(elements))
        queue = TaskQueue(store, stale_threshold_minutes=10)

        tasks = queue.get_pending_tasks()
        assert len(tasks) == 2
        # Not-started (priority 0) comes before stale (priority 1)
        assert tasks[0].element_id == "FN-001"
        assert tasks[0].priority == 0
        assert tasks[1].element_id == "FN-002"
        assert tasks[1].priority == 1

    def test_in_progress_without_timestamp_treated_as_stale(self):
        store = ArtifactStore()
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "No timestamp",
                "status": "进行中",
                "parent": None,
                "children": [],
            },
        }
        store.store(_make_status_artifact(elements))
        queue = TaskQueue(store)

        tasks = queue.get_pending_tasks()
        assert len(tasks) == 1
        assert tasks[0].priority == 1
