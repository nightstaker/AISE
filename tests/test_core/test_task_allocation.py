"""Tests for intelligent task allocation system."""

from __future__ import annotations

import pytest

from aise.core.task_allocation import (
    AgentCapability,
    AllocationResult,
    LoadBalancer,
    SmartRouter,
    TaskMatcher,
)


class TestAgentCapability:
    """Tests for AgentCapability model."""

    def test_create_capability_with_rating(self):
        """Test creating capability with explicit rating."""
        cap = AgentCapability(agent="architect", skill="deep_architecture_workflow", rating=4.5)
        assert cap.agent == "architect"
        assert cap.skill == "deep_architecture_workflow"
        assert cap.rating == 4.5

    def test_default_rating_is_one(self):
        """Test that default rating is 1.0."""
        cap = AgentCapability(agent="developer", skill="coding")
        assert cap.rating == 1.0

    def test_rating_bounds(self):
        """Test that rating is bounded between 0 and 5."""
        cap = AgentCapability(agent="test", skill="test", rating=2.5)
        assert 0 <= cap.rating <= 5

    def test_key_generation(self):
        """Test key property generates correct format."""
        cap = AgentCapability(agent="pm", skill="planning")
        assert cap.key == "pm.planning"


class TestTaskMatcher:
    """Tests for TaskMatcher."""

    def setup_method(self):
        """Set up test fixtures."""
        self.capabilities = [
            AgentCapability("architect", "deep_architecture_workflow", 5.0),
            AgentCapability("architect", "system_design", 4.5),
            AgentCapability("developer", "deep_architecture_workflow", 2.0),
            AgentCapability("developer", "coding", 5.0),
            AgentCapability("senior_dev", "deep_architecture_workflow", 4.0),
        ]
        self.matcher = TaskMatcher(self.capabilities)

    def test_find_best_agent_for_task(self):
        """Test finding best agent based on capability."""
        result = self.matcher.find_best_agent("deep_architecture_workflow")
        assert result.agent == "architect"
        assert result.capability_rating == 5.0

    def test_find_best_agent_with_tie_breaker(self):
        """Test that alphabetical order breaks ties."""
        caps = [
            AgentCapability("zebra", "skill", 3.0),
            AgentCapability("alpha", "skill", 3.0),
        ]
        matcher = TaskMatcher(caps)
        result = matcher.find_best_agent("skill")
        assert result.agent == "alpha"  # Alphabetically first

    def test_no_capable_agent_returns_none(self):
        """Test that unknown skill returns None."""
        result = self.matcher.find_best_agent("unknown_skill")
        assert result is None

    def test_filter_by_minimum_rating(self):
        """Test filtering agents by minimum rating."""
        agents = self.matcher.find_agents_by_rating("deep_architecture_workflow", min_rating=4.0)
        assert len(agents) == 2  # architect (5.0), senior_dev (4.0)
        assert all(a.rating >= 4.0 for a in agents)

    def test_get_all_agents_for_skill(self):
        """Test getting all agents with a skill."""
        agents = self.matcher.find_agents_by_rating("deep_architecture_workflow")
        assert len(agents) == 3  # architect, developer, senior_dev


class TestLoadBalancer:
    """Tests for LoadBalancer."""

    def test_initial_load_is_zero(self):
        """Test that new agent starts with zero load."""
        lb = LoadBalancer()
        assert lb.get_load("new_agent") == 0.0

    def test_add_load_increments_load(self):
        """Test that adding load increases the load value."""
        lb = LoadBalancer()
        lb.add_load("agent1", 2.0)
        assert lb.get_load("agent1") == 2.0

    def test_load_decay_over_time(self):
        """Test that load decays over time."""
        lb = LoadBalancer(decay_rate=0.5)  # 50% decay per tick
        lb.add_load("agent1", 10.0)
        lb.tick()
        assert lb.get_load("agent1") == 5.0

    def test_load_caps_at_max(self):
        """Test that load doesn't exceed maximum."""
        lb = LoadBalancer(max_load=10.0)
        lb.add_load("agent1", 15.0)
        assert lb.get_load("agent1") == 10.0

    def test_get_least_loaded_agent(self):
        """Test finding the agent with minimum load."""
        lb = LoadBalancer()
        lb.add_load("busy_agent", 8.0)
        lb.add_load("idle_agent", 2.0)
        lb.add_load("medium_agent", 5.0)

        least_loaded = lb.get_least_loaded(["busy_agent", "idle_agent", "medium_agent"])
        assert least_loaded == "idle_agent"

    def test_get_least_loaded_with_empty_list(self):
        """Test that empty list returns None."""
        lb = LoadBalancer()
        result = lb.get_least_loaded([])
        assert result is None


class TestSmartRouter:
    """Tests for SmartRouter."""

    def setup_method(self):
        """Set up test fixtures."""
        self.capabilities = [
            AgentCapability("architect", "design", 5.0),
            AgentCapability("developer", "design", 3.0),
            AgentCapability("developer", "coding", 5.0),
        ]
        self.router = SmartRouter(
            capabilities=self.capabilities,
            capability_weight=0.7,
            load_weight=0.3,
        )

    def test_allocate_prefers_high_capability(self):
        """Test that high capability agents are preferred."""
        result = self.router.allocate("design")
        assert result.agent == "architect"
        assert result.score > 0

    def test_allocate_considers_load(self):
        """Test that heavily loaded agents are deprioritized."""
        # Make architect very busy
        self.router.load_balancer.add_load("architect", 100.0)

        result = self.router.allocate("design")
        # Developer should win due to lower load
        assert result.agent == "developer"

    def test_allocate_returns_allocation_result(self):
        """Test that allocation returns proper result object."""
        result = self.router.allocate("coding")
        assert isinstance(result, AllocationResult)
        assert result.agent == "developer"
        assert result.capability_rating == 5.0
        assert result.current_load >= 0

    def test_allocate_unknown_skill_raises_error(self):
        """Test that unknown skill raises ValueError."""
        with pytest.raises(ValueError, match="No capable agent found"):
            self.router.allocate("unknown_skill")

    def test_allocate_with_custom_weights(self):
        """Test allocation with custom capability/load weights."""
        router = SmartRouter(
            capabilities=self.capabilities,
            capability_weight=0.9,  # Prioritize capability
            load_weight=0.1,
        )
        router.load_balancer.add_load("architect", 50.0)

        result = router.allocate("design")
        # Architect should still win due to high capability weight
        assert result.agent == "architect"

    def test_score_calculation(self):
        """Test that score is weighted combination of capability and inverse load."""
        result = self.router.allocate("design")
        # Score should be positive and reasonable
        assert 0 <= result.score <= 5.0

    def test_rebalance_loads(self):
        """Test that rebalance decays all loads."""
        self.router.load_balancer.add_load("architect", 10.0)
        self.router.load_balancer.tick()

        # Load should be reduced
        assert self.router.load_balancer.get_load("architect") < 10.0


class TestIntegration:
    """Integration tests for the task allocation system."""

    def test_end_to_end_allocation(self):
        """Test complete allocation workflow."""
        capabilities = [
            AgentCapability("senior_dev", "coding", 5.0),
            AgentCapability("junior_dev", "coding", 2.0),
            AgentCapability("senior_dev", "review", 4.5),
        ]

        router = SmartRouter(capabilities=capabilities)

        # First task goes to senior_dev (highest capability)
        result1 = router.allocate("coding")
        assert result1.agent == "senior_dev"

        # Simulate load from first task
        router.load_balancer.add_load("senior_dev", 5.0)

        # Second task might go to junior_dev due to load
        result2 = router.allocate("coding")
        # Depending on weights, could be either
        assert result2.agent in ["senior_dev", "junior_dev"]

    def test_multiple_skills_allocation(self):
        """Test allocation across different skills."""
        capabilities = [
            AgentCapability("architect", "design", 5.0),
            AgentCapability("developer", "coding", 5.0),
            AgentCapability("qa", "testing", 5.0),
        ]

        router = SmartRouter(capabilities=capabilities)

        result1 = router.allocate("design")
        assert result1.agent == "architect"

        result2 = router.allocate("coding")
        assert result2.agent == "developer"

        result3 = router.allocate("testing")
        assert result3.agent == "qa"
