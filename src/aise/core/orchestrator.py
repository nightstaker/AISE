"""Orchestrator that coordinates agents through the development workflow."""

from __future__ import annotations

from typing import Any

from .agent import Agent, AgentRole
from .artifact import ArtifactStore
from .message import MessageBus
from .workflow import Workflow, WorkflowEngine


class Orchestrator:
    """Coordinates agents and drives the workflow pipeline.

    The orchestrator manages the team of agents, routes tasks,
    and drives the workflow phases to completion.
    """

    def __init__(self) -> None:
        self.message_bus = MessageBus()
        self.artifact_store = ArtifactStore()
        self.workflow_engine = WorkflowEngine()
        self._agents: dict[str, Agent] = {}

    def register_agent(self, agent: Agent) -> None:
        """Register an agent with the orchestrator."""
        self._agents[agent.name] = agent

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
    ) -> str:
        """Execute a task on a specific agent and return the artifact ID."""
        agent = self._agents.get(agent_name)
        if agent is None:
            raise ValueError(f"No agent registered with name '{agent_name}'")

        artifact = agent.execute_skill(skill_name, input_data, project_name)
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

        while not workflow.is_complete:
            phase = workflow.current_phase
            if phase is None:
                break

            # Inject current input into all tasks in this phase
            for task in phase.tasks:
                task.input_data = {**current_input, **task.input_data}

            def executor(agent_name: str, skill_name: str, input_data: dict) -> str:
                return self.execute_task(
                    agent_name, skill_name, input_data, project_name
                )

            phase_result = self.workflow_engine.execute_phase(workflow, executor)
            results.append(phase_result)

            if phase_result["status"] == "failed":
                break

            # Run review gate if present
            if phase.review_gate:
                review_result = self.workflow_engine.run_review(workflow, executor)
                phase_result["review"] = review_result
                if not review_result.get("approved", False):
                    break

            workflow.advance()

        return results

    def run_default_workflow(
        self,
        project_input: dict[str, Any],
        project_name: str = "",
    ) -> list[dict[str, Any]]:
        """Run the default SDLC workflow."""
        workflow = WorkflowEngine.create_default_workflow()
        return self.run_workflow(workflow, project_input, project_name)
