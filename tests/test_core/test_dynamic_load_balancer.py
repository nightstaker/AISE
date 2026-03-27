"""Tests for Dynamic Load Balancer."""

from __future__ import annotations

import threading
import time

import pytest

from aise.core.dynamic_load_balancer import (
    AgentLoadMonitor,
    DynamicLoadBalancer,
)


class TestAgentLoadMonitor:
    """Test AgentLoadMonitor."""

    def test_initial_state(self) -> None:
        """Test monitor starts with empty state."""
        monitor = AgentLoadMonitor()
        assert len(monitor._agent_loads) == 0
        assert len(monitor._task_history) == 0

    def test_update_load(self) -> None:
        """Test updating agent load."""
        monitor = AgentLoadMonitor()

        monitor.update_load("agent-1", 5.0)

        assert monitor.get_current_load("agent-1") == 5.0

    def test_decay_load(self) -> None:
        """Test load decay over time."""
        monitor = AgentLoadMonitor(decay_interval_ms=100, decay_factor=0.5)

        monitor.update_load("agent-1", 100.0)
        time.sleep(0.15)  # Wait for decay interval

        load = monitor.get_current_load("agent-1")
        assert load < 100.0
        assert load > 0.0

    def test_get_load_ranking(self) -> None:
        """Test getting agents ranked by load."""
        monitor = AgentLoadMonitor()

        monitor.update_load("high-load", 90.0)
        monitor.update_load("medium-load", 50.0)
        monitor.update_load("low-load", 10.0)

        ranking = monitor.get_load_ranking()

        assert len(ranking) == 3
        assert ranking[0][0] == "low-load"  # Lowest load first
        assert ranking[1][0] == "medium-load"
        assert ranking[2][0] == "high-load"

    def test_record_task_start(self) -> None:
        """Test recording task start."""
        monitor = AgentLoadMonitor()

        task_id = "task-001"
        monitor.record_task_start(task_id, "agent-1")

        assert task_id in monitor._task_history
        assert monitor._task_history[task_id]["agent"] == "agent-1"

    def test_record_task_complete(self) -> None:
        """Test recording task completion."""
        monitor = AgentLoadMonitor()

        task_id = "task-001"
        monitor.record_task_start(task_id, "agent-1")
        monitor.record_task_complete(task_id, True, 85.0)

        task_record = monitor._task_history[task_id]
        assert task_record["completed"] is True
        assert task_record["success"] is True
        assert task_record["quality_score"] == 85.0

    def test_get_agent_stats(self) -> None:
        """Test getting agent statistics."""
        monitor = AgentLoadMonitor()

        # Record some tasks
        for i in range(5):
            task_id = f"task-{i}"
            monitor.record_task_start(task_id, "agent-1")
            monitor.record_task_complete(task_id, success=i < 4, quality_score=80.0 + i * 2)

        stats = monitor.get_agent_stats("agent-1")

        assert stats["total_tasks"] == 5
        assert stats["completed_tasks"] == 5
        assert stats["success_rate"] == pytest.approx(0.8, rel=0.01)  # 4/5
        assert stats["avg_quality"] == pytest.approx(84.0, rel=0.01)

    def test_thread_safety(self) -> None:
        """Test thread-safe operations."""
        monitor = AgentLoadMonitor()
        errors = []

        def add_load(agent: str, iterations: int) -> None:
            try:
                for i in range(iterations):
                    monitor.update_load(agent, i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=add_load, args=(f"agent-{i}", 100)) for i in range(10)]

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert len(monitor._agent_loads) == 10


class TestDynamicLoadBalancer:
    """Test DynamicLoadBalancer."""

    def test_initial_state(self) -> None:
        """Test balancer starts with defaults."""
        balancer = DynamicLoadBalancer()
        assert balancer._max_load_threshold == 80.0
        assert balancer._rebalancing_enabled is True

    def test_add_agent(self) -> None:
        """Test adding an agent."""
        balancer = DynamicLoadBalancer()

        balancer.add_agent("agent-1", max_load=100.0)

        assert "agent-1" in balancer._agents
        assert balancer._agents["agent-1"].max_load == 100.0

    def test_remove_agent(self) -> None:
        """Test removing an agent."""
        balancer = DynamicLoadBalancer()

        balancer.add_agent("agent-1")
        balancer.remove_agent("agent-1")

        assert "agent-1" not in balancer._agents

    def test_select_least_loaded_agent(self) -> None:
        """Test selecting the least loaded agent."""
        balancer = DynamicLoadBalancer()

        balancer.add_agent("heavy", max_load=100.0)
        balancer.add_agent("light", max_load=100.0)

        # Simulate load
        balancer._monitor.update_load("heavy", 80.0)
        balancer._monitor.update_load("light", 20.0)

        selected = balancer.select_agent()

        assert selected == "light"

    def test_select_agent_with_max_load_check(self) -> None:
        """Test that agents over max load are not selected."""
        balancer = DynamicLoadBalancer()

        balancer.add_agent("overloaded", max_load=50.0)
        balancer.add_agent("available", max_load=100.0)

        balancer._monitor.update_load("overloaded", 100.0)  # Over max
        balancer._monitor.update_load("available", 30.0)

        selected = balancer.select_agent()

        assert selected == "available"

    def test_auto_rebalance(self) -> None:
        """Test automatic load rebalancing."""
        balancer = DynamicLoadBalancer(max_load_threshold=50.0)

        balancer.add_agent("agent-1", max_load=100.0)
        balancer.add_agent("agent-2", max_load=100.0)

        balancer._monitor.update_load("agent-1", 90.0)
        balancer._monitor.update_load("agent-2", 10.0)

        # Trigger rebalance
        rebalanced = balancer.rebalance()

        assert rebalanced is True

    def test_get_cluster_stats(self) -> None:
        """Test getting cluster statistics."""
        balancer = DynamicLoadBalancer()

        balancer.add_agent("agent-1", max_load=100.0)
        balancer.add_agent("agent-2", max_load=100.0)

        balancer._monitor.update_load("agent-1", 60.0)
        balancer._monitor.update_load("agent-2", 40.0)

        stats = balancer.get_cluster_stats()

        assert stats["total_agents"] == 2
        assert stats["avg_load"] == 50.0
        assert stats["max_load"] == 60.0
        assert stats["min_load"] == 40.0

    def test_select_agent_no_available(self) -> None:
        """Test selection when all agents are overloaded."""
        balancer = DynamicLoadBalancer()

        balancer.add_agent("overloaded", max_load=50.0)

        balancer._monitor.update_load("overloaded", 100.0)

        selected = balancer.select_agent()

        # Should return least loaded even if over threshold
        assert selected == "overloaded"

    def test_distributed_lock(self) -> None:
        """Test distributed lock acquisition."""
        balancer = DynamicLoadBalancer()

        lock_name = "test-lock"

        # Acquire lock
        acquired = balancer.acquire_lock(lock_name, ttl_seconds=10)
        assert acquired is True

        # Try to acquire same lock
        acquired_again = balancer.acquire_lock(lock_name, ttl_seconds=10)
        assert acquired_again is False

        # Release lock
        balancer.release_lock(lock_name)

        # Should be able to acquire now
        acquired_after_release = balancer.acquire_lock(lock_name, ttl_seconds=10)
        assert acquired_after_release is True

    def test_configure_thresholds(self) -> None:
        """Test configuring load thresholds."""
        balancer = DynamicLoadBalancer()

        balancer.configure(max_load_threshold=90.0, rebalance_interval_ms=500)

        assert balancer._max_load_threshold == 90.0
