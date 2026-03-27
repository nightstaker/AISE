"""Intelligent task allocation system for AISE."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AgentCapability:
    """Represents an agent's capability in a specific skill."""

    agent: str
    skill: str
    rating: float = 1.0  # Default rating

    def __post_init__(self) -> None:
        """Validate rating bounds."""
        if not 0 <= self.rating <= 5:
            raise ValueError(f"Rating must be between 0 and 5, got {self.rating}")

    @property
    def key(self) -> str:
        """Generate unique key for this capability."""
        return f"{self.agent}.{self.skill}"


@dataclass
class AllocationResult:
    """Result of a task allocation decision."""

    agent: str
    capability_rating: float
    current_load: float
    score: float


class TaskMatcher:
    """Matches tasks to agents based on capabilities."""

    def __init__(self, capabilities: list[AgentCapability]) -> None:
        """Initialize with list of agent capabilities."""
        self._capabilities = capabilities
        self._skill_index: dict[str, list[AgentCapability]] = self._build_index()

    def _build_index(self) -> dict[str, list[AgentCapability]]:
        """Build index of capabilities by skill."""
        index: dict[str, list[AgentCapability]] = {}
        for cap in self._capabilities:
            if cap.skill not in index:
                index[cap.skill] = []
            index[cap.skill].append(cap)
        return index

    def find_best_agent(self, skill: str) -> AllocationResult | None:
        """Find the best agent for a given skill.

        Args:
            skill: The skill name to find an agent for.

        Returns:
            AllocationResult with best agent, or None if no capable agent found.
        """
        candidates = self._skill_index.get(skill, [])
        if not candidates:
            return None

        # Sort by rating descending, then alphabetically by agent name for tie-breaking
        candidates.sort(key=lambda c: (-c.rating, c.agent))
        best = candidates[0]

        return AllocationResult(
            agent=best.agent,
            capability_rating=best.rating,
            current_load=0.0,
            score=best.rating,
        )

    def find_agents_by_rating(self, skill: str, min_rating: float = 0.0) -> list[AgentCapability]:
        """Find all agents with a skill above minimum rating.

        Args:
            skill: The skill name.
            min_rating: Minimum rating threshold.

        Returns:
            List of AgentCapability sorted by rating descending.
        """
        candidates = self._skill_index.get(skill, [])
        filtered = [c for c in candidates if c.rating >= min_rating]
        filtered.sort(key=lambda c: -c.rating)
        return filtered


class LoadBalancer:
    """Tracks and balances load across agents."""

    def __init__(
        self,
        decay_rate: float = 0.1,
        max_load: float = 10.0,
    ) -> None:
        """Initialize load balancer.

        Args:
            decay_rate: Load decay per tick (0-1).
            max_load: Maximum load an agent can have.
        """
        self._loads: dict[str, float] = {}
        self._decay_rate = decay_rate
        self._max_load = max_load

    def get_load(self, agent: str) -> float:
        """Get current load for an agent."""
        return self._loads.get(agent, 0.0)

    def add_load(self, agent: str, amount: float) -> None:
        """Add load to an agent."""
        current = self._loads.get(agent, 0.0)
        self._loads[agent] = min(current + amount, self._max_load)

    def tick(self) -> None:
        """Advance time by one tick, decaying all loads."""
        for agent in self._loads:
            self._loads[agent] = max(0.0, self._loads[agent] * (1 - self._decay_rate))

    def get_least_loaded(self, agents: list[str]) -> str | None:
        """Find the agent with minimum load.

        Args:
            agents: List of agent names to consider.

        Returns:
            Agent name with least load, or None if list is empty.
        """
        if not agents:
            return None

        return min(agents, key=lambda a: self.get_load(a))


class SmartRouter:
    """Intelligently routes tasks to agents based on capability and load."""

    def __init__(
        self,
        capabilities: list[AgentCapability],
        capability_weight: float = 0.7,
        load_weight: float = 0.3,
    ) -> None:
        """Initialize smart router.

        Args:
            capabilities: List of agent capabilities.
            capability_weight: Weight for capability in scoring (0-1).
            load_weight: Weight for load in scoring (0-1).
        """
        self._matcher = TaskMatcher(capabilities)
        self.load_balancer = LoadBalancer()
        self._capability_weight = capability_weight
        self._load_weight = load_weight

    def allocate(self, skill: str) -> AllocationResult:
        """Allocate a task to the best available agent.

        Args:
            skill: The skill required for the task.

        Returns:
            AllocationResult with chosen agent and scoring details.

        Raises:
            ValueError: If no capable agent is found.
        """
        candidates = self._matcher.find_agents_by_rating(skill)
        if not candidates:
            raise ValueError(f"No capable agent found for skill: {skill}")

        # Calculate score for each candidate
        best_score = -1.0
        best_result = None

        for cap in candidates:
            load = self.load_balancer.get_load(cap.agent)
            # Normalize load to 0-5 scale (inverted - lower load is better)
            normalized_load = 5.0 - (load / self._load_balancer_max() * 5.0) if self._load_balancer_max() > 0 else 5.0
            # Weighted score
            score = self._capability_weight * cap.rating + self._load_weight * normalized_load

            if score > best_score:
                best_score = score
                best_result = AllocationResult(
                    agent=cap.agent,
                    capability_rating=cap.rating,
                    current_load=load,
                    score=score,
                )

        if best_result is None:
            raise ValueError(f"No capable agent found for skill: {skill}")

        return best_result

    def _load_balancer_max(self) -> float:
        """Get maximum load across all agents."""
        if not self.load_balancer._loads:
            return 0.0
        return max(self.load_balancer._loads.values())
