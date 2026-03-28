"""Multi-Skill Task Allocator.

This module provides intelligent task allocation for tasks requiring
multiple skills, with team-based assignment and skill coverage optimization.
"""

from __future__ import annotations

from dataclasses import dataclass

from aise.core.task_allocation import AgentCapability


@dataclass
class MultiSkillTask:
    """A task requiring multiple skills."""

    task_id: str
    description: str
    required_skills: list[str]
    optional_skills: list[str] = None  # type: ignore
    priority: int = 5
    max_agents: int | None = None  # Maximum team size

    def __post_init__(self) -> None:
        """Initialize optional fields."""
        if self.optional_skills is None:
            self.optional_skills = []


@dataclass
class TeamAssignment:
    """Assignment of agents to a multi-skill task."""

    task_id: str
    agents: list[str]
    skill_coverage: float  # 0-1, fraction of required skills covered
    total_capability: float  # Sum of capability ratings for assigned skills
    skill_breakdown: dict[str, tuple[str, float]]  # skill -> (agent, rating)
    recommendations: list[str]  # Recommended additional agents for missing skills


class MultiSkillAllocator:
    """Allocator for multi-skill tasks."""

    def __init__(self):
        """Initialize the allocator."""
        self._capabilities: dict[str, dict[str, float]] = {}  # agent -> {skill -> rating}

    def add_capability(self, capability: AgentCapability) -> None:
        """Add an agent capability.

        Args:
            capability: The capability to add.
        """
        if capability.agent not in self._capabilities:
            self._capabilities[capability.agent] = {}
        self._capabilities[capability.agent][capability.skill] = capability.rating

    def remove_capability(self, agent: str, skill: str) -> bool:
        """Remove an agent capability.

        Args:
            agent: Agent name.
            skill: Skill name.

        Returns:
            Whether the capability was removed.
        """
        if agent in self._capabilities and skill in self._capabilities[agent]:
            del self._capabilities[agent][skill]
            if not self._capabilities[agent]:
                del self._capabilities[agent]
            return True
        return False

    def find_agents_for_skill(self, skill: str) -> list[AgentCapability]:
        """Find all agents with a specific skill.

        Args:
            skill: The skill to search for.

        Returns:
            List of AgentCapability objects, sorted by rating descending.
        """
        results = []
        for agent, skills in self._capabilities.items():
            if skill in skills:
                results.append(AgentCapability(agent=agent, skill=skill, rating=skills[skill]))
        return sorted(results, key=lambda x: x.rating, reverse=True)

    def get_agent_skills(self, agent: str) -> dict[str, float]:
        """Get all skills for an agent.

        Args:
            agent: Agent name.

        Returns:
            Dictionary of skill -> rating.
        """
        return self._capabilities.get(agent, {}).copy()

    def get_all_agents(self) -> list[str]:
        """Get all registered agents.

        Returns:
            List of agent names.
        """
        return list(self._capabilities.keys())

    def allocate_task(self, task: MultiSkillTask, max_agents: int | None = None) -> TeamAssignment | None:
        """Allocate a team of agents to a multi-skill task.

        Args:
            task: The task to allocate.
            max_agents: Maximum number of agents (overrides task.max_agents).

        Returns:
            TeamAssignment or None if no valid assignment possible.
        """
        if not task.required_skills:
            return TeamAssignment(
                task_id=task.task_id,
                agents=[],
                skill_coverage=1.0,
                total_capability=0.0,
                skill_breakdown={},
                recommendations=[],
            )

        limit = max_agents or task.max_agents

        # Find best agent for each required skill
        skill_to_agents: dict[str, list[AgentCapability]] = {}
        for skill in task.required_skills:
            agents = self.find_agents_for_skill(skill)
            skill_to_agents[skill] = agents

        # Check which skills are available
        available_skills = [skill for skill, agents in skill_to_agents.items() if agents]
        missing_skills = [skill for skill, agents in skill_to_agents.items() if not agents]

        if not available_skills:
            # No skills available at all
            return TeamAssignment(
                task_id=task.task_id,
                agents=[],
                skill_coverage=0.0,
                total_capability=0.0,
                skill_breakdown={},
                recommendations=missing_skills,
            )

        # Greedy assignment: pick best agent for each skill
        assigned_agents: set[str] = set()
        skill_breakdown: dict[str, tuple[str, float]] = {}

        # Sort skills by number of available agents (hardest to fill first)
        sorted_skills = sorted(available_skills, key=lambda s: len(skill_to_agents[s]))

        for skill in sorted_skills:
            agents = skill_to_agents[skill]
            best_agent = agents[0].agent
            best_rating = agents[0].rating

            skill_breakdown[skill] = (best_agent, best_rating)
            assigned_agents.add(best_agent)

            # Respect max_agents limit
            if limit and len(assigned_agents) >= limit:
                break

        # Calculate metrics
        skill_coverage = len(skill_breakdown) / len(task.required_skills)
        total_capability = sum(rating for _, rating in skill_breakdown.values())

        # Generate recommendations for missing skills
        recommendations = missing_skills.copy()

        return TeamAssignment(
            task_id=task.task_id,
            agents=list(assigned_agents),
            skill_coverage=skill_coverage,
            total_capability=total_capability,
            skill_breakdown=skill_breakdown,
            recommendations=recommendations,
        )

    def find_optimal_team(self, task: MultiSkillTask, max_agents: int | None = None) -> TeamAssignment | None:
        """Find the optimal team for a task (considering agent overlap).

        This method tries to minimize the number of agents while maximizing
        skill coverage and total capability.

        Args:
            task: The task to allocate.
            max_agents: Maximum number of agents.

        Returns:
            Optimal TeamAssignment.
        """
        limit = max_agents or task.max_agents

        if not task.required_skills:
            return TeamAssignment(
                task_id=task.task_id,
                agents=[],
                skill_coverage=1.0,
                total_capability=0.0,
                skill_breakdown={},
                recommendations=[],
            )

        # Get all candidate agents
        all_candidates = set()
        for skill in task.required_skills:
            for cap in self.find_agents_for_skill(skill):
                all_candidates.add(cap.agent)

        if not all_candidates:
            return TeamAssignment(
                task_id=task.task_id,
                agents=[],
                skill_coverage=0.0,
                total_capability=0.0,
                skill_breakdown={},
                recommendations=list(task.required_skills),
            )

        # Try different team sizes
        best_assignment: TeamAssignment | None = None

        for team_size in range(1, min(len(all_candidates) + 1, (limit or 10))):
            # This is a simplified approach - full enumeration would be expensive
            # For now, use greedy with agent count constraint
            assignment = self._greedy_assign_with_limit(task, team_size)

            if assignment and (best_assignment is None or assignment.skill_coverage > best_assignment.skill_coverage):
                best_assignment = assignment

            # Stop if we have full coverage
            if best_assignment and best_assignment.skill_coverage == 1.0:
                break

        return best_assignment

    def _greedy_assign_with_limit(self, task: MultiSkillTask, max_agents: int) -> TeamAssignment | None:
        """Greedy assignment with agent count limit.

        Args:
            task: The task to allocate.
            max_agents: Maximum number of agents.

        Returns:
            TeamAssignment or None.
        """
        assigned_agents: set[str] = set()
        skill_breakdown: dict[str, tuple[str, float]] = {}
        uncovered_skills = set(task.required_skills)

        while uncovered_skills and len(assigned_agents) < max_agents:
            # Find best agent that covers most uncovered skills
            best_agent: str | None = None
            best_coverage = 0
            best_breakdown: dict[str, tuple[str, float]] = {}

            for agent in self.get_all_agents():
                if agent in assigned_agents:
                    continue

                agent_skills = self.get_agent_skills(agent)
                coverage = 0
                breakdown: dict[str, tuple[str, float]] = {}

                for skill in uncovered_skills:
                    if skill in agent_skills:
                        coverage += 1
                        breakdown[skill] = (agent, agent_skills[skill])

                if coverage > best_coverage:
                    best_coverage = coverage
                    best_agent = agent
                    best_breakdown = breakdown

            if best_agent is None or best_coverage == 0:
                break

            assigned_agents.add(best_agent)
            skill_breakdown.update(best_breakdown)
            for skill in best_breakdown:
                uncovered_skills.discard(skill)

        if not skill_breakdown:
            return None

        skill_coverage = len(skill_breakdown) / len(task.required_skills)
        total_capability = sum(r for _, r in skill_breakdown.values())

        missing = list(uncovered_skills)

        return TeamAssignment(
            task_id=task.task_id,
            agents=list(assigned_agents),
            skill_coverage=skill_coverage,
            total_capability=total_capability,
            skill_breakdown=skill_breakdown,
            recommendations=missing,
        )
