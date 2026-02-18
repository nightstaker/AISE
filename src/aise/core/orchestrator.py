"""Orchestrator that coordinates agents through the development workflow."""

from __future__ import annotations

from typing import Any

from ..utils.logging import get_logger
from .agent import Agent, AgentRole
from .artifact import ArtifactStore
from .message import MessageBus
from .workflow import Workflow, WorkflowEngine

logger = get_logger(__name__)


class Orchestrator:
    """Coordinates agents and drives the workflow pipeline.

    The orchestrator manages the team of agents, routes tasks,
    and drives the workflow phases to completion.
    """

    def __init__(self, *, project_root: str | None = None) -> None:
        self.message_bus = MessageBus()
        self.artifact_store = ArtifactStore()
        self.workflow_engine = WorkflowEngine()
        self._agents: dict[str, Agent] = {}
        self.project_root = project_root
        # Routing state for multi-agent task distribution
        self._routing_state: dict[AgentRole, dict[str, Any]] = {}
        logger.info("Orchestrator initialized")

    def register_agent(self, agent: Agent) -> None:
        """Register an agent with the orchestrator."""
        self._agents[agent.name] = agent
        logger.info("Agent registered: name=%s role=%s", agent.name, agent.role.value)

    def get_agent(self, name: str) -> Agent | None:
        return self._agents.get(name)

    @property
    def agents(self) -> dict[str, Agent]:
        return dict(self._agents)

    def get_agents_by_role(self, role: AgentRole) -> list[Agent]:
        return [a for a in self._agents.values() if a.role == role]

    def execute_task(
        self,
        agent_name: str,
        skill_name: str,
        input_data: dict[str, Any],
        project_name: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """Execute a task on a specific agent and return the artifact ID."""
        logger.info(
            "Task dispatch: agent=%s skill=%s project=%s input_keys=%s",
            agent_name,
            skill_name,
            project_name,
            sorted(input_data.keys()),
        )
        agent = self._agents.get(agent_name)
        if agent is None:
            raise ValueError(f"No agent registered with name '{agent_name}'")

        skill_parameters = dict(parameters or {})
        if self.project_root:
            skill_parameters.setdefault("project_root", self.project_root)

        artifact = agent.execute_skill(skill_name, input_data, project_name, parameters=skill_parameters)
        logger.info(
            "Task completed: agent=%s skill=%s artifact_id=%s",
            agent_name,
            skill_name,
            artifact.id,
        )
        return artifact.id

    def run_workflow(
        self,
        workflow: Workflow,
        project_input: dict[str, Any],
        project_name: str = "",
    ) -> list[dict[str, Any]]:
        """Run a complete workflow from start to finish.

        Args:
            workflow: The workflow to execute.
            project_input: Initial input data (e.g., raw requirements).
            project_name: Name of the project.

        Returns:
            List of phase results.
        """
        results = []
        current_input = dict(project_input)
        logger.info("Workflow run started: workflow=%s project=%s", workflow.name, project_name)

        while not workflow.is_complete:
            phase = workflow.current_phase
            if phase is None:
                break

            # Inject current input into all tasks in this phase
            for task in phase.tasks:
                task.input_data = {**current_input, **task.input_data}

            def executor(agent_name: str, skill_name: str, input_data: dict) -> str:
                return self.execute_task(agent_name, skill_name, input_data, project_name)

            phase_result = self.workflow_engine.execute_phase(workflow, executor)
            results.append(phase_result)
            logger.info(
                "Workflow phase finished: workflow=%s phase=%s status=%s",
                workflow.name,
                phase_result.get("phase"),
                phase_result.get("status"),
            )

            if phase_result["status"] == "failed":
                break

            # Verify unit tests pass before review (implementation phase)
            if phase.require_tests_pass:
                test_result = self.workflow_engine.verify_tests_pass(workflow, executor)
                phase_result["test_verification"] = test_result
                if not test_result.get("passed", False):
                    logger.warning(
                        "Workflow phase test verification failed: workflow=%s phase=%s error=%s",
                        workflow.name,
                        phase.name,
                        test_result.get("error", ""),
                    )
                    break

            # Run review gate if present (enforces min_review_rounds)
            if phase.review_gate:
                review_result = self.workflow_engine.run_review(workflow, executor)
                phase_result["review"] = review_result
                if not review_result.get("approved", False):
                    logger.warning(
                        "Workflow review failed: workflow=%s phase=%s rounds=%s",
                        workflow.name,
                        phase.name,
                        review_result.get("rounds_completed"),
                    )
                    break

            workflow.advance()

        logger.info(
            "Workflow run completed: workflow=%s project=%s phases=%d", workflow.name, project_name, len(results)
        )
        return results

    def run_default_workflow(
        self,
        project_input: dict[str, Any],
        project_name: str = "",
    ) -> list[dict[str, Any]]:
        """Run the default SDLC workflow."""
        workflow = WorkflowEngine.create_default_workflow()
        return self.run_workflow(workflow, project_input, project_name)

    def execute_task_auto_route(
        self,
        role: AgentRole,
        skill_name: str,
        input_data: dict[str, Any],
        project_name: str = "",
        routing_strategy: str = "round_robin",
    ) -> str:
        """Execute a task on any agent of specified role using routing strategy.

        This method automatically selects an agent from all agents of the given role
        and executes the task on that agent. Useful for distributing work across
        multiple agents of the same type.

        Args:
            role: The agent role to execute the task
            skill_name: Name of the skill to execute
            input_data: Input data for the skill
            project_name: Name of the project
            routing_strategy: Strategy for selecting agent ("round_robin" or "load_based")

        Returns:
            Artifact ID from the executed task

        Raises:
            ValueError: If no agents available for the specified role
        """
        agents = self.get_agents_by_role(role)
        if not agents:
            raise ValueError(f"No agents available for role {role}")

        # Select agent based on strategy
        agent = self._select_agent(agents, role, routing_strategy)
        logger.info(
            "Auto route selected: role=%s strategy=%s agent=%s skill=%s",
            role.value,
            routing_strategy,
            agent.name,
            skill_name,
        )

        return self.execute_task(agent.name, skill_name, input_data, project_name)

    def _select_agent(
        self,
        agents: list[Agent],
        role: AgentRole,
        strategy: str,
    ) -> Agent:
        """Select an agent from the list based on routing strategy.

        Args:
            agents: List of agents to choose from
            role: The agent role (for tracking routing state)
            strategy: Routing strategy ("round_robin" or "load_based")

        Returns:
            Selected agent
        """
        if len(agents) == 1:
            return agents[0]

        # Initialize routing state for this role if needed
        if role not in self._routing_state:
            self._routing_state[role] = {
                "round_robin_index": 0,
                "load_counts": {agent.name: 0 for agent in agents},
            }

        state = self._routing_state[role]

        if strategy == "round_robin":
            # Round-robin: distribute tasks evenly in sequence
            index = state["round_robin_index"]
            selected = agents[index % len(agents)]
            state["round_robin_index"] = (index + 1) % len(agents)
            return selected

        elif strategy == "load_based":
            # Load-based: select agent with minimum load
            load_counts = state["load_counts"]

            # Ensure all current agents have entries in load_counts
            for agent in agents:
                if agent.name not in load_counts:
                    load_counts[agent.name] = 0

            # Select agent with minimum load
            selected = min(agents, key=lambda a: load_counts.get(a.name, 0))
            load_counts[selected.name] = load_counts.get(selected.name, 0) + 1
            return selected

        else:
            # Default to round-robin for unknown strategies
            return self._select_agent(agents, role, "round_robin")
