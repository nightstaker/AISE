"""Tests for Task Priority Scheduler."""

from __future__ import annotations

import threading
from datetime import datetime, timedelta

from aise.core.task_priority_scheduler import (
    PriorityTask,
    TaskPriorityScheduler,
    TaskState,
)


class TestPriorityTask:
    """Test PriorityTask dataclass."""

    def test_create_task(self) -> None:
        """Test creating a priority task."""
        task = PriorityTask(
            task_id="task-001",
            description="Test task",
            priority=5,
            assigned_agent="agent-1",
        )

        assert task.task_id == "task-001"
        assert task.description == "Test task"
        assert task.priority == 5
        assert task.assigned_agent == "agent-1"
        assert task.state == TaskState.PENDING

    def test_task_state_transitions(self) -> None:
        """Test task state transitions."""
        task = PriorityTask(
            task_id="task-001",
            description="Test task",
            priority=5,
        )

        # Transition to running
        task.state = TaskState.RUNNING
        assert task.state == TaskState.RUNNING

        # Transition to completed
        task.state = TaskState.COMPLETED
        assert task.state == TaskState.COMPLETED


class TestTaskPriorityScheduler:
    """Test TaskPriorityScheduler."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.scheduler = TaskPriorityScheduler()

    def test_initial_state(self) -> None:
        """Test scheduler starts with empty queues."""
        assert len(self.scheduler._priority_queues) == 0
        assert len(self.scheduler._all_tasks) == 0

    def test_add_task(self) -> None:
        """Test adding a task."""
        task = PriorityTask(
            task_id="task-001",
            description="High priority task",
            priority=10,
        )

        self.scheduler.add_task(task)

        assert len(self.scheduler._all_tasks) == 1
        assert 10 in self.scheduler._priority_queues
        assert "task-001" in self.scheduler._all_tasks

    def test_priority_ordering(self) -> None:
        """Test tasks are ordered by priority."""
        # Add tasks with different priorities
        self.scheduler.add_task(
            PriorityTask(
                task_id="low",
                description="Low priority",
                priority=1,
            )
        )
        self.scheduler.add_task(
            PriorityTask(
                task_id="high",
                description="High priority",
                priority=10,
            )
        )
        self.scheduler.add_task(
            PriorityTask(
                task_id="medium",
                description="Medium priority",
                priority=5,
            )
        )

        # Get next task (should be highest priority)
        task = self.scheduler.get_next_task()

        assert task.task_id == "high"
        assert task.priority == 10

    def test_fifo_within_same_priority(self) -> None:
        """Test FIFO ordering within same priority level."""
        # Add tasks with same priority
        self.scheduler.add_task(
            PriorityTask(
                task_id="first",
                description="First task",
                priority=5,
            )
        )
        self.scheduler.add_task(
            PriorityTask(
                task_id="second",
                description="Second task",
                priority=5,
            )
        )

        # First task added should be returned first
        task1 = self.scheduler.get_next_task()
        task2 = self.scheduler.get_next_task()

        assert task1.task_id == "first"
        assert task2.task_id == "second"

    def test_get_next_task_empty(self) -> None:
        """Test getting next task from empty scheduler."""
        task = self.scheduler.get_next_task()
        assert task is None

    def test_task_with_deadline(self) -> None:
        """Test tasks with deadlines get higher priority."""
        now = datetime.now()

        # Task with near deadline
        near_deadline = PriorityTask(
            task_id="near",
            description="Near deadline",
            priority=5,
            deadline=now + timedelta(minutes=1),
        )

        # Task with far deadline
        far_deadline = PriorityTask(
            task_id="far",
            description="Far deadline",
            priority=5,
            deadline=now + timedelta(hours=24),
        )

        self.scheduler.add_task(near_deadline)
        self.scheduler.add_task(far_deadline)

        # Near deadline task should have higher effective priority
        task = self.scheduler.get_next_task()

        assert task.task_id == "near"

    def test_urgent_tasks(self) -> None:
        """Test urgent tasks get highest priority."""
        self.scheduler.add_task(
            PriorityTask(
                task_id="normal",
                description="Normal task",
                priority=10,
            )
        )
        self.scheduler.add_task(
            PriorityTask(
                task_id="urgent",
                description="Urgent task",
                priority=5,
                urgent=True,
            )
        )

        # Urgent task should be returned first despite lower base priority
        task = self.scheduler.get_next_task()

        assert task.task_id == "urgent"

    def test_remove_task(self) -> None:
        """Test removing a task."""
        task = PriorityTask(
            task_id="task-001",
            description="Task to remove",
            priority=5,
        )
        self.scheduler.add_task(task)

        self.scheduler.remove_task("task-001")

        assert "task-001" not in self.scheduler._all_tasks

    def test_remove_nonexistent_task(self) -> None:
        """Test removing a nonexistent task."""
        # Should not raise exception
        self.scheduler.remove_task("nonexistent")

    def test_update_task_priority(self) -> None:
        """Test updating task priority."""
        task = PriorityTask(
            task_id="task-001",
            description="Task to update",
            priority=5,
        )
        self.scheduler.add_task(task)

        self.scheduler.update_task_priority("task-001", new_priority=10)

        updated_task = self.scheduler._all_tasks["task-001"]
        assert updated_task.priority == 10

    def test_get_task(self) -> None:
        """Test getting a specific task."""
        task = PriorityTask(
            task_id="task-001",
            description="Test task",
            priority=5,
        )
        self.scheduler.add_task(task)

        retrieved = self.scheduler.get_task("task-001")

        assert retrieved is not None
        assert retrieved.task_id == "task-001"

    def test_get_task_not_found(self) -> None:
        """Test getting a nonexistent task."""
        task = self.scheduler.get_task("nonexistent")
        assert task is None

    def test_get_tasks_by_state(self) -> None:
        """Test getting tasks filtered by state."""
        self.scheduler.add_task(
            PriorityTask(
                task_id="pending-1",
                description="Pending task",
                priority=5,
            )
        )
        self.scheduler.add_task(
            PriorityTask(
                task_id="running-1",
                description="Running task",
                priority=5,
            )
        )

        # Update state
        self.scheduler._all_tasks["running-1"].state = TaskState.RUNNING

        pending_tasks = self.scheduler.get_tasks_by_state(TaskState.PENDING)

        assert len(pending_tasks) == 1
        assert pending_tasks[0].task_id == "pending-1"

    def test_get_urgent_tasks(self) -> None:
        """Test getting urgent tasks."""
        self.scheduler.add_task(
            PriorityTask(
                task_id="urgent-1",
                description="Urgent task 1",
                priority=5,
                urgent=True,
            )
        )
        self.scheduler.add_task(
            PriorityTask(
                task_id="normal-1",
                description="Normal task",
                priority=10,
            )
        )

        urgent_tasks = self.scheduler.get_urgent_tasks()

        assert len(urgent_tasks) == 1
        assert urgent_tasks[0].task_id == "urgent-1"

    def test_thread_safety(self) -> None:
        """Test thread-safe task addition."""
        errors = []

        def add_tasks(start_id: int, count: int) -> None:
            try:
                for i in range(count):
                    task = PriorityTask(
                        task_id=f"task-{start_id + i}",
                        description="Concurrent task",
                        priority=5,
                    )
                    self.scheduler.add_task(task)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_tasks, args=(i * 100, 100)) for i in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(self.scheduler._all_tasks) == 1000

    def test_get_all_tasks(self) -> None:
        """Test getting all tasks."""
        for i in range(5):
            self.scheduler.add_task(
                PriorityTask(
                    task_id=f"task-{i}",
                    description="Test task",
                    priority=5,
                )
            )

        all_tasks = self.scheduler.get_all_tasks()

        assert len(all_tasks) == 5

    def test_clear_all_tasks(self) -> None:
        """Test clearing all tasks."""
        for i in range(5):
            self.scheduler.add_task(
                PriorityTask(
                    task_id=f"task-{i}",
                    description="Test task",
                    priority=5,
                )
            )

        self.scheduler.clear_all_tasks()

        assert len(self.scheduler._all_tasks) == 0
        assert len(self.scheduler._priority_queues) == 0

    def test_calculate_effective_priority(self) -> None:
        """Test effective priority calculation."""
        task = PriorityTask(
            task_id="task-001",
            description="Test task",
            priority=5,
        )

        effective = self.scheduler._calculate_effective_priority(task)

        # Base priority + small bonus for creation time
        assert effective >= 5
        assert effective < 100  # Urgent tasks get +100

    def test_urgent_bonus(self) -> None:
        """Test urgent task gets priority bonus."""
        normal_task = PriorityTask(
            task_id="normal",
            description="Normal",
            priority=10,
        )
        urgent_task = PriorityTask(
            task_id="urgent",
            description="Urgent",
            priority=1,
            urgent=True,
        )

        normal_effective = self.scheduler._calculate_effective_priority(normal_task)
        urgent_effective = self.scheduler._calculate_effective_priority(urgent_task)

        # Urgent task should have higher effective priority despite lower base
        assert urgent_effective > normal_effective

    def test_get_pending_count(self) -> None:
        """Test getting pending task count."""
        self.scheduler.add_task(
            PriorityTask(
                task_id="pending-1",
                description="Pending",
                priority=5,
            )
        )
        self.scheduler.add_task(
            PriorityTask(
                task_id="running-1",
                description="Running",
                priority=5,
            )
        )
        self.scheduler._all_tasks["running-1"].state = TaskState.RUNNING

        count = self.scheduler.get_pending_count()

        assert count == 1
