"""Tests for Multi-Skill Task Allocation."""

from __future__ import annotations

from aise.core.multi_skill_allocator import (
    MultiSkillAllocator,
    MultiSkillTask,
    TeamAssignment,
)


class TestMultiSkillTask:
    """Test MultiSkillTask dataclass."""

    def test_create_task(self) -> None:
        """Test creating a multi-skill task."""
        task = MultiSkillTask(
            task_id="task-001",
            description="Build a microservice",
            required_skills=["coding", "system_design"],
            priority=5,
        )

        assert task.task_id == "task-001"
        assert task.description == "Build a microservice"
        assert len(task.required_skills) == 2
        assert task.priority == 5

    def test_create_task_with_optional_skills(self) -> None:
        """Test creating task with optional skills."""
        task = MultiSkillTask(
            task_id="task-002",
            description="Build a complex system",
            required_skills=["coding"],
            optional_skills=["testing", "debugging"],
            priority=10,
        )

        assert len(task.required_skills) == 1
        assert len(task.optional_skills) == 2


class TestTeamAssignment:
    """Test TeamAssignment dataclass."""

    def test_create_assignment(self) -> None:
        """Test creating a team assignment."""
        assignment = TeamAssignment(
            task_id="task-001",
            agents=["agent-1", "agent-2"],
            skill_coverage=0.8,
            total_capability=8.5,
            skill_breakdown={"coding": ("agent-1", 4.5)},
            recommendations=[],
        )

        assert assignment.task_id == "task-001"
        assert len(assignment.agents) == 2
        assert assignment.skill_coverage == 0.8
        assert assignment.total_capability == 8.5


class TestMultiSkillAllocator:
    """Test MultiSkillAllocator."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.allocator = MultiSkillAllocator()

        # Add agents with various skills
        from aise.core.task_allocation import AgentCapability

        self.allocator.add_capability(AgentCapability("architect", "system_design", 5.0))
        self.allocator.add_capability(AgentCapability("architect", "api_design", 4.5))
        self.allocator.add_capability(AgentCapability("senior_dev", "coding", 4.8))
        self.allocator.add_capability(AgentCapability("senior_dev", "system_design", 4.0))
        self.allocator.add_capability(AgentCapability("developer", "coding", 4.5))
        self.allocator.add_capability(AgentCapability("developer", "debugging", 4.0))
        self.allocator.add_capability(AgentCapability("qa_engineer", "testing", 5.0))
        self.allocator.add_capability(AgentCapability("qa_engineer", "bug_reporting", 4.5))

    def test_initial_state(self) -> None:
        """Test allocator starts with correct state."""
        assert len(self.allocator._capabilities) == 4  # 4 agents

    def test_find_agents_for_single_skill(self) -> None:
        """Test finding agents for a single skill."""
        agents = self.allocator.find_agents_for_skill("coding")

        assert len(agents) == 2
        agent_names = [a.agent for a in agents]
        assert "senior_dev" in agent_names
        assert "developer" in agent_names

    def test_find_agents_for_nonexistent_skill(self) -> None:
        """Test finding agents for a skill no one has."""
        agents = self.allocator.find_agents_for_skill("nonexistent_skill")

        assert len(agents) == 0

    def test_allocate_simple_multi_skill_task(self) -> None:
        """Test allocating a task requiring two skills."""
        task = MultiSkillTask(
            task_id="task-001",
            description="Design and implement API",
            required_skills=["system_design", "coding"],
            priority=5,
        )

        assignment = self.allocator.allocate_task(task)

        assert assignment is not None
        assert len(assignment.agents) >= 2  # Need at least 2 agents

        # Check that agents cover required skills
        agent_names = assignment.agents
        assert "architect" in agent_names or "senior_dev" in agent_names  # system_design
        assert "senior_dev" in agent_names or "developer" in agent_names  # coding

    def test_allocate_with_full_skill_coverage(self) -> None:
        """Test allocation achieves full skill coverage."""
        task = MultiSkillTask(
            task_id="task-002",
            description="Design, code, and test",
            required_skills=["system_design", "coding", "testing"],
            priority=5,
        )

        assignment = self.allocator.allocate_task(task)

        assert assignment is not None
        assert assignment.skill_coverage == 1.0  # Full coverage
        assert len(assignment.agents) >= 3

    def test_allocate_with_partial_skill_coverage(self) -> None:
        """Test allocation with missing skill."""
        task = MultiSkillTask(
            task_id="task-003",
            description="Needs rare skill",
            required_skills=["coding", "rare_skill_xyz"],
            priority=5,
        )

        assignment = self.allocator.allocate_task(task)

        assert assignment is not None
        assert assignment.skill_coverage < 1.0  # Cannot cover rare_skill_xyz
        assert assignment.skill_coverage > 0.0  # Can cover coding

    def test_allocate_considers_agent_count(self) -> None:
        """Test allocation uses minimal number of agents."""
        task = MultiSkillTask(
            task_id="task-004",
            description="Single skill task",
            required_skills=["coding"],
            priority=5,
        )

        assignment = self.allocator.allocate_task(task)

        assert assignment is not None
        assert len(assignment.agents) == 1  # Only one agent needed

    def test_allocate_with_optional_skills(self) -> None:
        """Test allocation includes optional skills when available."""
        task = MultiSkillTask(
            task_id="task-005",
            description="Code with debugging support",
            required_skills=["coding"],
            optional_skills=["debugging"],
            priority=5,
        )

        assignment = self.allocator.allocate_task(task)

        assert assignment is not None
        # Should include developer who has both coding and debugging
        agent_names = assignment.agents
        assert "senior_dev" in agent_names or "developer" in agent_names

    def test_allocate_respects_max_agents(self) -> None:
        """Test allocation respects max_agents limit."""
        task = MultiSkillTask(
            task_id="task-006",
            description="Many skills",
            required_skills=[
                "system_design",
                "coding",
                "testing",
                "debugging",
            ],
            priority=5,
        )

        assignment = self.allocator.allocate_task(task, max_agents=2)

        assert assignment is not None
        assert len(assignment.agents) <= 2

    def test_allocate_calculates_total_capability(self) -> None:
        """Test total capability is calculated correctly."""
        task = MultiSkillTask(
            task_id="task-007",
            description="Single agent task",
            required_skills=["testing"],
            priority=5,
        )

        assignment = self.allocator.allocate_task(task)

        assert assignment is not None
        assert assignment.total_capability == 5.0  # qa_engineer has 5.0 for testing

    def test_get_agent_skills(self) -> None:
        """Test getting all skills for an agent."""
        skills = self.allocator.get_agent_skills("architect")

        assert len(skills) == 2
        assert "system_design" in skills
        assert "api_design" in skills

    def test_get_agent_skills_nonexistent_agent(self) -> None:
        """Test getting skills for nonexistent agent."""
        skills = self.allocator.get_agent_skills("nonexistent")

        assert len(skills) == 0

    def test_allocate_recommends_additional_agents(self) -> None:
        """Test allocation recommends agents for missing skills."""
        task = MultiSkillTask(
            task_id="task-008",
            description="Needs missing skill",
            required_skills=["coding", "missing_skill"],
            priority=5,
        )

        assignment = self.allocator.allocate_task(task)

        assert assignment is not None
        # Should have recommendation for missing_skill
        assert len(assignment.recommendations) > 0

    def test_remove_capability(self) -> None:
        """Test removing an agent capability."""
        self.allocator.remove_capability("qa_engineer", "testing")

        skills = self.allocator.get_agent_skills("qa_engineer")
        assert "testing" not in skills

    def test_get_all_agents(self) -> None:
        """Test getting all registered agents."""
        agents = self.allocator.get_all_agents()

        assert len(agents) == 4
        assert "architect" in agents
        assert "senior_dev" in agents

    def test_allocate_empty_skill_requirement(self) -> None:
        """Test allocating task with no skill requirements."""
        task = MultiSkillTask(
            task_id="task-009",
            description="No skills needed",
            required_skills=[],
            priority=5,
        )

        assignment = self.allocator.allocate_task(task)

        assert assignment is not None
        assert len(assignment.agents) == 0
        assert assignment.skill_coverage == 1.0  # Trivially covered
