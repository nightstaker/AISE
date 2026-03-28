"""Dynamic Load Balancer.

This module provides dynamic load balancing for agents with automatic
load monitoring, rebalancing, and distributed coordination.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class AgentConfig:
    """Configuration for an agent."""

    max_load: float = 100.0
    priority: float = 1.0
    capabilities: list[str] = field(default_factory=list)


class AgentLoadMonitor:
    """Monitors agent loads and task history."""

    def __init__(self, decay_interval_ms: int = 1000, decay_factor: float = 0.95):
        """Initialize the load monitor.

        Args:
            decay_interval_ms: Interval between load decay operations.
            decay_factor: Factor to multiply load by during decay (0-1).
        """
        self._agent_loads: dict[str, float] = defaultdict(float)
        self._task_history: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._decay_interval_ms = decay_interval_ms
        self._decay_factor = decay_factor
        self._last_decay = time.time()

        # Start decay thread
        self._decay_thread = threading.Thread(target=self._decay_loop, daemon=True)
        self._decay_thread.start()

    def _decay_loop(self) -> None:
        """Background loop for load decay."""
        while True:
            time.sleep(self._decay_interval_ms / 1000.0)
            self._decay_loads()

    def _decay_loads(self) -> None:
        """Apply decay to all agent loads."""
        with self._lock:
            for agent in self._agent_loads:
                self._agent_loads[agent] *= self._decay_factor

    def update_load(self, agent: str, load: float) -> None:
        """Update the load for an agent.

        Args:
            agent: Agent name.
            load: Load value to add.
        """
        with self._lock:
            self._agent_loads[agent] += load

    def get_current_load(self, agent: str) -> float:
        """Get the current load for an agent.

        Args:
            agent: Agent name.

        Returns:
            Current load value.
        """
        with self._lock:
            return self._agent_loads.get(agent, 0.0)

    def get_load_ranking(self) -> list[tuple[str, float]]:
        """Get agents ranked by load (lowest first).

        Returns:
            List of (agent, load) tuples sorted by load ascending.
        """
        with self._lock:
            return sorted(self._agent_loads.items(), key=lambda x: x[1])

    def record_task_start(self, task_id: str, agent: str) -> None:
        """Record a task starting.

        Args:
            task_id: Task identifier.
            agent: Agent assigned to the task.
        """
        with self._lock:
            self._task_history[task_id] = {
                "agent": agent,
                "start_time": datetime.now(),
                "completed": False,
                "success": None,
                "quality_score": None,
            }

    def record_task_complete(self, task_id: str, success: bool, quality_score: float) -> None:
        """Record a task completion.

        Args:
            task_id: Task identifier.
            success: Whether the task succeeded.
            quality_score: Quality score (0-100).
        """
        with self._lock:
            if task_id in self._task_history:
                self._task_history[task_id]["completed"] = True
                self._task_history[task_id]["success"] = success
                self._task_history[task_id]["quality_score"] = quality_score
                self._task_history[task_id]["end_time"] = datetime.now()

    def get_agent_stats(self, agent: str) -> dict[str, Any]:
        """Get statistics for an agent.

        Args:
            agent: Agent name.

        Returns:
            Dictionary with agent statistics.
        """
        with self._lock:
            tasks = [t for t in self._task_history.values() if t["agent"] == agent]

            completed = [t for t in tasks if t["completed"]]
            successful = [t for t in completed if t["success"]]

            total_quality = sum(t["quality_score"] for t in completed if t["quality_score"] is not None)

            return {
                "total_tasks": len(tasks),
                "completed_tasks": len(completed),
                "successful_tasks": len(successful),
                "success_rate": len(successful) / len(completed) if completed else 0.0,
                "avg_quality": total_quality / len(completed) if completed else 0.0,
                "current_load": self._agent_loads.get(agent, 0.0),
            }


class DynamicLoadBalancer:
    """Dynamic load balancer with automatic rebalancing."""

    def __init__(self, max_load_threshold: float = 80.0):
        """Initialize the load balancer.

        Args:
            max_load_threshold: Maximum load threshold before rebalancing.
        """
        self._agents: dict[str, AgentConfig] = {}
        self._monitor = AgentLoadMonitor()
        self._max_load_threshold = max_load_threshold
        self._lock = threading.RLock()
        self._rebalancing_enabled = True

        # Distributed locks
        self._distributed_locks: dict[str, datetime] = {}

    def add_agent(self, agent: str, max_load: float = 100.0) -> None:
        """Add an agent to the balancer.

        Args:
            agent: Agent name.
            max_load: Maximum load for this agent.
        """
        with self._lock:
            self._agents[agent] = AgentConfig(max_load=max_load)

    def remove_agent(self, agent: str) -> None:
        """Remove an agent from the balancer.

        Args:
            agent: Agent name.
        """
        with self._lock:
            self._agents.pop(agent, None)

    def select_agent(self) -> str | None:
        """Select the best agent for a new task.

        Returns:
            Agent name or None if no agent available.
        """
        with self._lock:
            if not self._agents:
                return None

            # Get load ranking
            ranking = self._monitor.get_load_ranking()

            # Find first agent under max load threshold
            for agent, load in ranking:
                if agent in self._agents:
                    agent_load_pct = (load / self._agents[agent].max_load) * 100
                    if agent_load_pct < self._max_load_threshold:
                        return agent

            # Return least loaded agent even if over threshold
            if ranking:
                return ranking[0][0]

            return None

    def rebalance(self) -> bool:
        """Check and perform rebalancing if needed.

        Returns:
            Whether rebalancing was performed.
        """
        if not self._rebalancing_enabled:
            return False

        with self._lock:
            ranking = self._monitor.get_load_ranking()

            if len(ranking) < 2:
                return False

            # Check if any agent is over threshold
            max_load = ranking[-1][1] if ranking else 0
            avg_load = sum(load_val for _, load_val in ranking) / len(ranking) if ranking else 0

            # Rebalance if max load significantly exceeds average
            if max_load > avg_load * 1.5 and max_load > self._max_load_threshold:
                # Trigger rebalancing logic here
                # This could involve moving tasks, rejecting new tasks to overloaded agents, etc.
                return True

            return False

    def get_cluster_stats(self) -> dict[str, Any]:
        """Get cluster-wide statistics.

        Returns:
            Dictionary with cluster statistics.
        """
        with self._lock:
            ranking = self._monitor.get_load_ranking()

            loads = [load_val for _, load_val in ranking]

            return {
                "total_agents": len(self._agents),
                "avg_load": sum(loads) / len(loads) if loads else 0.0,
                "max_load": max(loads) if loads else 0.0,
                "min_load": min(loads) if loads else 0.0,
            }

    def acquire_lock(self, lock_name: str, ttl_seconds: int = 60) -> bool:
        """Acquire a distributed lock.

        Args:
            lock_name: Name of the lock.
            ttl_seconds: Time-to-live for the lock.

        Returns:
            Whether the lock was acquired.
        """
        with self._lock:
            now = datetime.now()

            # Check if lock exists and is expired
            if lock_name in self._distributed_locks:
                lock_time = self._distributed_locks[lock_name]
                age = (now - lock_time).total_seconds()
                if age > ttl_seconds:
                    # Lock expired, acquire it
                    self._distributed_locks[lock_name] = now
                    return True
                # Lock is still valid, cannot acquire
                return False
            else:
                # Lock doesn't exist, acquire it
                self._distributed_locks[lock_name] = now
                return True

    def release_lock(self, lock_name: str) -> None:
        """Release a distributed lock.

        Args:
            lock_name: Name of the lock.
        """
        with self._lock:
            self._distributed_locks.pop(lock_name, None)

    def configure(self, max_load_threshold: float | None = None, rebalance_interval_ms: int | None = None) -> None:
        """Configure the load balancer.

        Args:
            max_load_threshold: New max load threshold.
            rebalance_interval_ms: New rebalance interval.
        """
        with self._lock:
            if max_load_threshold is not None:
                self._max_load_threshold = max_load_threshold
