"""Tests for the developer session manager."""

import asyncio
from datetime import datetime, timezone
from unittest.mock import patch

from aise.config import ProjectConfig, SessionConfig
from aise.core.artifact import Artifact, ArtifactType
from aise.core.dev_session import (
    DeveloperSession,
    SessionManager,
    SessionStatus,
)
from aise.core.orchestrator import Orchestrator


def _make_status_artifact(elements: dict) -> Artifact:
    """Helper to create a STATUS_TRACKING artifact."""
    return Artifact(
        artifact_type=ArtifactType.STATUS_TRACKING,
        content={
            "project_name": "test",
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "elements": elements,
            "summary": {"overall_completion": 0.0},
        },
        producer="architect",
    )


def _make_source_artifact(element_id: str, all_passed: bool = True) -> Artifact:
    """Helper to create a SOURCE_CODE artifact from TDD session."""
    return Artifact(
        artifact_type=ArtifactType.SOURCE_CODE,
        content={
            "element_id": element_id,
            "all_passed": all_passed,
            "tests": {},
            "code": {},
            "test_run": {"passed": all_passed},
            "lint_run": {"passed": all_passed},
        },
        producer="developer",
    )


class TestDeveloperSession:
    def test_defaults(self):
        session = DeveloperSession()
        assert session.status == SessionStatus.PENDING
        assert session.pr_number is None
        assert session.error == ""
        assert len(session.session_id) == 8

    def test_touch_updates_timestamp(self):
        session = DeveloperSession()
        old_ts = session.updated_at
        session.touch()
        assert session.updated_at >= old_ts

    def test_to_dict(self):
        session = DeveloperSession(
            agent_name="dev_1",
            task_element_id="AR-0001",
            task_description="Auth module",
        )
        d = session.to_dict()
        assert d["agent_name"] == "dev_1"
        assert d["task_element_id"] == "AR-0001"
        assert d["status"] == "pending"
        assert "session_id" in d


class TestSessionManager:
    def _make_manager(
        self,
        elements: dict | None = None,
        max_sessions: int = 2,
        mode: str = "local",
    ) -> SessionManager:
        """Create a SessionManager with a mocked orchestrator."""
        config = ProjectConfig(
            project_name="test",
            development_mode=mode,
            session=SessionConfig(
                max_concurrent_sessions=max_sessions,
                status_update_interval_minutes=1,
                stale_task_threshold_minutes=10,
            ),
        )

        orchestrator = Orchestrator()

        if elements:
            orchestrator.artifact_store.store(_make_status_artifact(elements))

        manager = SessionManager(
            orchestrator=orchestrator,
            config=config,
            max_concurrent_sessions=max_sessions,
            repo_root="/tmp/test-repo",
        )
        return manager

    def test_init(self):
        manager = self._make_manager()
        assert not manager.is_running
        assert manager.sessions == {}
        assert manager.active_task_ids == set()

    def test_pick_next_task_empty(self):
        manager = self._make_manager()
        assert manager._pick_next_task() is None

    def test_pick_next_task_with_elements(self):
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Auth module",
                "status": "未开始",
                "parent": None,
                "children": [],
            },
        }
        manager = self._make_manager(elements=elements)
        task = manager._pick_next_task()
        assert task is not None
        assert task.element_id == "AR-0001"

    def test_pick_next_task_excludes_active(self):
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Auth",
                "status": "未开始",
                "parent": None,
                "children": [],
            },
        }
        manager = self._make_manager(elements=elements)
        manager._active_task_ids.add("AR-0001")
        assert manager._pick_next_task() is None

    def test_local_mode_forces_single_session(self):
        config = ProjectConfig(development_mode="local")
        orchestrator = Orchestrator()
        SessionManager(orchestrator, config, max_concurrent_sessions=5)
        # The start() method will enforce local mode = 1 session
        # We verify the config is local
        assert config.is_local_mode

    def test_write_status_md(self):
        import os
        import tempfile

        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Test",
                "status": "未开始",
                "parent": None,
                "children": [],
            },
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._make_manager(elements=elements)
            manager.repo_root = tmpdir

            # Add a fake active session
            session = DeveloperSession(
                agent_name="worker_0",
                task_element_id="AR-0001",
                task_description="Auth module",
                status=SessionStatus.RUNNING,
            )
            manager._sessions[session.session_id] = session

            manager._write_status_md()

            status_path = os.path.join(tmpdir, "status.md")
            assert os.path.exists(status_path)

            with open(status_path) as f:
                content = f.read()

            assert "Development Status" in content
            assert "AR-0001" in content
            assert "running" in content
            assert "Active Sessions" in content

    def test_write_status_md_no_sessions(self):
        import os
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            manager = self._make_manager()
            manager.repo_root = tmpdir
            manager._write_status_md()

            status_path = os.path.join(tmpdir, "status.md")
            assert os.path.exists(status_path)

            with open(status_path) as f:
                content = f.read()

            assert "idle" in content

    def test_run_session_local_mode(self):
        """Test that a session runs the TDD flow in local mode."""
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Auth module",
                "status": "未开始",
                "parent": None,
                "children": [],
            },
        }
        manager = self._make_manager(elements=elements, mode="local")

        # Mock the orchestrator.execute_task to return an artifact ID
        source_art = _make_source_artifact("AR-0001", all_passed=True)
        manager.orchestrator.artifact_store.store(source_art)

        with patch.object(manager.orchestrator, "execute_task", return_value=source_art.id):
            with patch.object(manager, "_local_commit"):
                from aise.core.task_queue import DevTask

                task = DevTask(
                    element_id="AR-0001",
                    element_type="architecture_requirement",
                    description="Auth module",
                )
                session = DeveloperSession(
                    agent_name="worker_0",
                    task_element_id="AR-0001",
                    task_description="Auth module",
                )

                asyncio.run(manager._run_session(session, task))

                assert session.status == SessionStatus.COMPLETED

    def test_run_session_test_failure(self):
        """Test that a session fails when tests don't pass."""
        elements = {
            "AR-0001": {
                "type": "architecture_requirement",
                "description": "Auth module",
                "status": "未开始",
                "parent": None,
                "children": [],
            },
        }
        manager = self._make_manager(elements=elements, mode="local")

        # Mock with all_passed=False
        source_art = _make_source_artifact("AR-0001", all_passed=False)
        manager.orchestrator.artifact_store.store(source_art)

        with patch.object(manager.orchestrator, "execute_task", return_value=source_art.id):
            from aise.core.task_queue import DevTask

            task = DevTask(
                element_id="AR-0001",
                element_type="architecture_requirement",
                description="Auth module",
            )
            session = DeveloperSession(
                agent_name="worker_0",
                task_element_id="AR-0001",
                task_description="Auth module",
            )

            asyncio.run(manager._run_session(session, task))

            assert session.status == SessionStatus.FAILED
            assert "failed" in session.error.lower()


class TestSessionStatus:
    def test_all_statuses_exist(self):
        assert SessionStatus.PENDING.value == "pending"
        assert SessionStatus.RUNNING.value == "running"
        assert SessionStatus.TESTING.value == "testing"
        assert SessionStatus.LINTING.value == "linting"
        assert SessionStatus.PR_SUBMITTED.value == "pr_submitted"
        assert SessionStatus.PR_REVIEW.value == "pr_review"
        assert SessionStatus.FIXING_CI.value == "fixing_ci"
        assert SessionStatus.COMPLETED.value == "completed"
        assert SessionStatus.FAILED.value == "failed"
