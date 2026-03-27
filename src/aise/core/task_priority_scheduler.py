"""Task Priority Scheduler.

This module provides task scheduling with priority-based ordering,
FIFO within same priority level, and deadline-aware scheduling.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class TaskState(Enum):
    """Task states."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class PriorityTask:
    """A task with priority and metadata."""

    task_id: str
    description: str
    priority: int  # 1-10, higher is more important
    assigned_agent: str | None = None
    state: TaskState = TaskState.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    deadline: datetime | None = None
    urgent: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __lt__(self, other: "PriorityTask") -> bool:
        """Compare tasks by priority (higher priority first)."""
        if self.priority != other.priority:
            return self.priority > other.priority  # Higher priority comes first
        # Same priority: FIFO (earlier creation time comes first)
        return self.created_at < other.created_at


class TaskPriorityScheduler:
    """Scheduler for priority-based task management."""

    def __init__(self):
        """Initialize the scheduler."""
        self._all_tasks: dict[str, PriorityTask] = {}
        self._priority_queues: dict[int, list[str]] = {}  # priority -> list of task_ids
        self._lock = threading.RLock()

    def _calculate_effective_priority(self, task: PriorityTask) -> int:
        """Calculate effective priority considering urgency and deadline.

        Args:
            task: The task to calculate priority for.

        Returns:
            Effective priority value.
        """
        effective = task.priority

        # Urgent tasks get +100 priority
        if task.urgent:
            effective += 100

        # Tasks with approaching deadlines get bonus
        if task.deadline:
            time_until_deadline = (task.deadline - datetime.now()).total_seconds()

            # More bonus the closer to deadline
            if time_until_deadline < 60:
                effective += 50  # Less than 1 minute
            elif time_until_deadline < 300:
                effective += 25  # Less than 5 minutes
            elif time_until_deadline < 3600:
                effective += 10  # Less than 1 hour
            elif time_until_deadline < 86400:
                effective += 5  # Less than 1 day

        # Small bonus for creation time (older tasks slightly preferred)
        age_seconds = (datetime.now() - task.created_at).total_seconds()
        effective += min(age_seconds / 3600, 5)  # Max 5 bonus for age

        return int(effective)

    def add_task(self, task: PriorityTask) -> None:
        """Add a task to the scheduler.

        Args:
            task: The task to add.
        """
        with self._lock:
            # Calculate effective priority for ordering
            effective_priority = self._calculate_effective_priority(task)

            # Store task
            self._all_tasks[task.task_id] = task

            # Add to priority queue
            if effective_priority not in self._priority_queues:
                self._priority_queues[effective_priority] = []
            self._priority_queues[effective_priority].append(task.task_id)

    def remove_task(self, task_id: str) -> bool:
        """Remove a task from the scheduler.

        Args:
            task_id: The task to remove.

        Returns:
            Whether the task was removed.
        """
        with self._lock:
            if task_id not in self._all_tasks:
                return False

            task = self._all_tasks.pop(task_id)
            effective_priority = self._calculate_effective_priority(task)

            # Remove from priority queue
            if effective_priority in self._priority_queues:
                self._priority_queues[effective_priority].remove(task_id)
                if not self._priority_queues[effective_priority]:
                    del self._priority_queues[effective_priority]

            return True

    def get_next_task(self) -> PriorityTask | None:
        """Get the next task to execute (highest priority).

        Returns:
            The next task, or None if no tasks available.
        """
        with self._lock:
            if not self._priority_queues:
                return None

            # Get highest priority queue
            highest_priority = max(self._priority_queues.keys())
            queue = self._priority_queues[highest_priority]

            if not queue:
                return None

            # Get first task in queue (FIFO)
            task_id = queue.pop(0)
            if not queue:
                del self._priority_queues[highest_priority]

            return self._all_tasks.get(task_id)

    def get_task(self, task_id: str) -> PriorityTask | None:
        """Get a specific task by ID.

        Args:
            task_id: The task to retrieve.

        Returns:
            The task, or None if not found.
        """
        with self._lock:
            return self._all_tasks.get(task_id)

    def update_task_priority(self, task_id: str, new_priority: int) -> bool:
        """Update a task's priority.

        Args:
            task_id: The task to update.
            new_priority: The new priority value.

        Returns:
            Whether the task was updated.
        """
        with self._lock:
            if task_id not in self._all_tasks:
                return False

            task = self._all_tasks[task_id]
            old_priority = task.priority
            task.priority = new_priority

            # Recalculate effective priorities
            old_effective = self._calculate_effective_priority(
                PriorityTask(
                    task_id=task_id,
                    description=task.description,
                    priority=old_priority,
                    deadline=task.deadline,
                    urgent=task.urgent,
                    created_at=task.created_at,
                )
            )
            new_effective = self._calculate_effective_priority(task)

            # Move between queues if needed
            if old_effective != new_effective:
                if old_effective in self._priority_queues:
                    self._priority_queues[old_effective].remove(task_id)
                    if not self._priority_queues[old_effective]:
                        del self._priority_queues[old_effective]

                if new_effective not in self._priority_queues:
                    self._priority_queues[new_effective] = []
                self._priority_queues[new_effective].append(task_id)

            return True

    def get_tasks_by_state(self, state: TaskState) -> list[PriorityTask]:
        """Get all tasks in a specific state.

        Args:
            state: The state to filter by.

        Returns:
            List of tasks in the specified state.
        """
        with self._lock:
            return [task for task in self._all_tasks.values() if task.state == state]

    def get_urgent_tasks(self) -> list[PriorityTask]:
        """Get all urgent tasks.

        Returns:
            List of urgent tasks.
        """
        with self._lock:
            return [task for task in self._all_tasks.values() if task.urgent]

    def get_all_tasks(self) -> list[PriorityTask]:
        """Get all tasks.

        Returns:
            List of all tasks.
        """
        with self._lock:
            return list(self._all_tasks.values())

    def clear_all_tasks(self) -> None:
        """Clear all tasks from the scheduler."""
        with self._lock:
            self._all_tasks.clear()
            self._priority_queues.clear()

    def get_pending_count(self) -> int:
        """Get the count of pending tasks.

        Returns:
            Number of pending tasks.
        """
        with self._lock:
            return sum(1 for task in self._all_tasks.values() if task.state == TaskState.PENDING)
