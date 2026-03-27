"""Tests for Agent Capability Learning."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from aise.core.agent_capability_learning import (
    AgentCapabilityLearner,
    TaskExecutionRecord,
)


class TestTaskExecutionRecord:
    """Test TaskExecutionRecord dataclass."""

    def test_create_record(self) -> None:
        """Test creating a task execution record."""
        now = datetime.now()
        record = TaskExecutionRecord(
            task_id="task-001",
            agent_name="agent-1",
            skill_name="coding",
            start_time=now,
            end_time=now + timedelta(seconds=60),
            success=True,
            duration_seconds=60.0,
            quality_score=85.0,
        )

        assert record.task_id == "task-001"
        assert record.agent_name == "agent-1"
        assert record.skill_name == "coding"
        assert record.success is True
        assert record.duration_seconds == 60.0
        assert record.quality_score == 85.0
        assert record.error_message == ""

    def test_create_failed_record(self) -> None:
        """Test creating a failed task execution record."""
        now = datetime.now()
        record = TaskExecutionRecord(
            task_id="task-002",
            agent_name="agent-2",
            skill_name="testing",
            start_time=now,
            end_time=now + timedelta(seconds=30),
            success=False,
            duration_seconds=30.0,
            quality_score=0.0,
            error_message="Task failed due to timeout",
        )

        assert record.success is False
        assert record.error_message == "Task failed due to timeout"


class TestAgentCapabilityLearner:
    """Test AgentCapabilityLearner."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.learner = AgentCapabilityLearner()

    def test_initial_state(self) -> None:
        """Test learner starts with empty records."""
        assert len(self.learner.records) == 0

    def test_record_execution(self) -> None:
        """Test recording a task execution."""
        now = datetime.now()
        record = TaskExecutionRecord(
            task_id="task-001",
            agent_name="agent-1",
            skill_name="coding",
            start_time=now,
            end_time=now + timedelta(seconds=60),
            success=True,
            duration_seconds=60.0,
            quality_score=85.0,
        )

        self.learner.record_execution(record)

        assert len(self.learner.records) == 1
        assert self.learner.records[0].task_id == "task-001"

    def test_record_multiple_executions(self) -> None:
        """Test recording multiple task executions."""
        now = datetime.now()

        for i in range(5):
            record = TaskExecutionRecord(
                task_id=f"task-{i}",
                agent_name="agent-1",
                skill_name="coding",
                start_time=now,
                end_time=now + timedelta(seconds=60),
                success=True,
                duration_seconds=60.0,
                quality_score=80.0 + i * 2,
            )
            self.learner.record_execution(record)

        assert len(self.learner.records) == 5

    def test_get_capability_rating_single_record(self) -> None:
        """Test capability rating with single record."""
        now = datetime.now()
        record = TaskExecutionRecord(
            task_id="task-001",
            agent_name="agent-1",
            skill_name="coding",
            start_time=now,
            end_time=now + timedelta(seconds=60),
            success=True,
            duration_seconds=60.0,
            quality_score=80.0,
        )
        self.learner.record_execution(record)

        rating = self.learner.get_capability_rating("agent-1", "coding")

        # 80% quality = 4.0 rating (0-5 scale)
        assert rating == pytest.approx(4.0, rel=0.1)
        assert 0.0 <= rating <= 5.0

    def test_get_capability_rating_multiple_records(self) -> None:
        """Test capability rating with multiple records."""
        now = datetime.now()

        # Record 3 executions with different quality scores
        for quality in [70.0, 80.0, 90.0]:
            record = TaskExecutionRecord(
                task_id="task",
                agent_name="agent-1",
                skill_name="coding",
                start_time=now,
                end_time=now + timedelta(seconds=60),
                success=True,
                duration_seconds=60.0,
                quality_score=quality,
            )
            self.learner.record_execution(record)

        rating = self.learner.get_capability_rating("agent-1", "coding")

        # Average quality = 80% = 4.0 rating
        assert rating == pytest.approx(4.0, rel=0.1)

    def test_get_capability_rating_with_failures(self) -> None:
        """Test capability rating with failures reduces rating."""
        now = datetime.now()

        # Mix of successes and failures
        self.learner.record_execution(
            TaskExecutionRecord(
                task_id="t1",
                agent_name="agent-1",
                skill_name="coding",
                start_time=now,
                end_time=now + timedelta(seconds=60),
                success=True,
                duration_seconds=60.0,
                quality_score=100.0,
            )
        )
        self.learner.record_execution(
            TaskExecutionRecord(
                task_id="t2",
                agent_name="agent-1",
                skill_name="coding",
                start_time=now,
                end_time=now + timedelta(seconds=60),
                success=False,
                duration_seconds=60.0,
                quality_score=0.0,
            )
        )

        rating = self.learner.get_capability_rating("agent-1", "coding")

        # 50% success rate with 50% avg quality = 2.5 rating
        assert rating == pytest.approx(2.5, rel=0.1)

    def test_get_capability_rating_no_history(self) -> None:
        """Test capability rating with no history returns default."""
        rating = self.learner.get_capability_rating("unknown-agent", "unknown-skill")

        # Should return default rating (2.5)
        assert rating == 2.5

    def test_export_learned_capabilities(self) -> None:
        """Test exporting learned capabilities."""
        now = datetime.now()

        # Record executions for different agent-skill pairs
        self.learner.record_execution(
            TaskExecutionRecord(
                task_id="t1",
                agent_name="agent-1",
                skill_name="coding",
                start_time=now,
                end_time=now + timedelta(seconds=60),
                success=True,
                duration_seconds=60.0,
                quality_score=80.0,
            )
        )
        self.learner.record_execution(
            TaskExecutionRecord(
                task_id="t2",
                agent_name="agent-1",
                skill_name="testing",
                start_time=now,
                end_time=now + timedelta(seconds=60),
                success=True,
                duration_seconds=60.0,
                quality_score=90.0,
            )
        )
        self.learner.record_execution(
            TaskExecutionRecord(
                task_id="t3",
                agent_name="agent-2",
                skill_name="coding",
                start_time=now,
                end_time=now + timedelta(seconds=60),
                success=True,
                duration_seconds=60.0,
                quality_score=70.0,
            )
        )

        capabilities = self.learner.export_learned_capabilities()

        assert len(capabilities) == 3

        # Find and verify each capability
        agent1_coding = next(
            (c for c in capabilities if c.agent == "agent-1" and c.skill == "coding"),
            None,
        )
        assert agent1_coding is not None
        assert agent1_coding.rating == pytest.approx(4.0, rel=0.1)

        agent1_testing = next(
            (c for c in capabilities if c.agent == "agent-1" and c.skill == "testing"),
            None,
        )
        assert agent1_testing is not None
        assert agent1_testing.rating == pytest.approx(4.5, rel=0.1)

        agent2_coding = next(
            (c for c in capabilities if c.agent == "agent-2" and c.skill == "coding"),
            None,
        )
        assert agent2_coding is not None
        assert agent2_coding.rating == pytest.approx(3.5, rel=0.1)

    def test_load_history_empty_file(self) -> None:
        """Test loading from empty history file."""
        temp_dir = Path(tempfile.mkdtemp())
        temp_file = temp_dir / "test_empty_history.json"
        temp_file.write_text("[]")

        self.learner.history_file = temp_file
        self.learner.load_history()

        assert len(self.learner.records) == 0
        temp_file.unlink()

    def test_load_history_with_data(self) -> None:
        """Test loading history with data."""
        temp_dir = Path(tempfile.mkdtemp())
        now = datetime.now().isoformat()
        history_data = f"""[
            {{
                "task_id": "task-001",
                "agent_name": "agent-1",
                "skill_name": "coding",
                "start_time": "{now}",
                "end_time": "{now}",
                "success": true,
                "duration_seconds": 60.0,
                "quality_score": 80.0,
                "error_message": ""
            }}
        ]"""

        temp_file = temp_dir / "test_history.json"
        temp_file.write_text(history_data)

        self.learner.history_file = temp_file
        self.learner.load_history()

        assert len(self.learner.records) == 1
        assert self.learner.records[0].task_id == "task-001"

        temp_file.unlink()

    def test_save_history(self) -> None:
        """Test saving history to file."""
        temp_dir = Path(tempfile.mkdtemp())
        now = datetime.now()
        record = TaskExecutionRecord(
            task_id="task-001",
            agent_name="agent-1",
            skill_name="coding",
            start_time=now,
            end_time=now + timedelta(seconds=60),
            success=True,
            duration_seconds=60.0,
            quality_score=80.0,
        )
        self.learner.record_execution(record)

        temp_file = temp_dir / "test_save.json"
        self.learner.history_file = temp_file
        self.learner.save_history()

        assert temp_file.exists()
        content = temp_file.read_text()
        assert "task-001" in content

        temp_file.unlink()

    def test_load_and_save_round_trip(self) -> None:
        """Test that loading after saving preserves data."""
        temp_dir = Path(tempfile.mkdtemp())
        now = datetime.now()
        record = TaskExecutionRecord(
            task_id="task-001",
            agent_name="agent-1",
            skill_name="coding",
            start_time=now,
            end_time=now + timedelta(seconds=60),
            success=True,
            duration_seconds=60.0,
            quality_score=85.0,
        )
        self.learner.record_execution(record)

        temp_file = temp_dir / "test_roundtrip.json"
        self.learner.history_file = temp_file
        self.learner.save_history()

        # Create new learner and load
        new_learner = AgentCapabilityLearner()
        new_learner.history_file = temp_file
        new_learner.load_history()

        assert len(new_learner.records) == 1
        assert new_learner.records[0].task_id == "task-001"
        assert new_learner.records[0].quality_score == 85.0

        temp_file.unlink()

    def test_recent_executions_weighted_more(self) -> None:
        """Test that recent executions are weighted more heavily."""
        # Record old execution with low quality
        old_time = datetime.now() - timedelta(days=7)
        self.learner.record_execution(
            TaskExecutionRecord(
                task_id="old",
                agent_name="agent-1",
                skill_name="coding",
                start_time=old_time,
                end_time=old_time + timedelta(seconds=60),
                success=True,
                duration_seconds=60.0,
                quality_score=40.0,
            )
        )

        # Record recent execution with high quality
        now = datetime.now()
        self.learner.record_execution(
            TaskExecutionRecord(
                task_id="recent",
                agent_name="agent-1",
                skill_name="coding",
                start_time=now,
                end_time=now + timedelta(seconds=60),
                success=True,
                duration_seconds=60.0,
                quality_score=100.0,
            )
        )

        rating = self.learner.get_capability_rating("agent-1", "coding")

        # Should be closer to 5.0 (recent) than 2.0 (old)
        # With exponential decay, recent should dominate
        assert rating > 3.0
        assert rating < 5.0
