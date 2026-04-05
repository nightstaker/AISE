"""Orchestrator that coordinates agents through the development workflow."""

from __future__ import annotations

from typing import Any

from ..utils.logging import get_logger
from .agent import Agent, AgentRole
from .artifact import ArtifactStore, ArtifactType
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

    def run_dynamic_workflow(
        self,
        project_input: dict[str, Any],
        project_name: str = "",
        llm_client: Any = None,
        goal_artifacts: list[ArtifactType] | None = None,
        constraints: list[str] | None = None,
        progress_callback: Any = None,
        existing_plan: dict[str, Any] | None = None,
        selected_process_id: str | None = None,
    ) -> dict[str, Any]:
        """Run an AI-planned dynamic workflow.

        Instead of the fixed 4-phase pipeline, this uses the AIPlanner
        to generate an optimal execution plan based on the actual
        requirements and available capabilities.

        If selected_process_id is provided, the plan must follow that
        process template (e.g., 'waterfall_standard_v1' or 'agile_sprint_v1').

        Args:
            project_input: Input data (must contain 'raw_requirements').
            project_name: Human-readable project name.
            llm_client: LLM client for the planner (optional; uses fallback if None).
            goal_artifacts: Desired output artifact types. Defaults to SOURCE_CODE.
            constraints: Additional constraints for the planner.
            selected_process_id: Optional process template ID to constrain the plan.

        Returns:
            Dict with status, step_results, artifact_ids, and plan metadata.
        """
        from .ai_planner import AIPlanner, PlannerContext
        from .dynamic_engine import DynamicEngine
        from .process_registry import ProcessRegistry

        logger.info("run_dynamic_workflow entered: project_name=%s, llm_client=%s",
                    project_name, type(llm_client).__name__ if llm_client else None)

        registry = ProcessRegistry.build_default()

        # Auto-discover skills from registered agents
        registry.auto_discover_from_agents(self._agents)

        if llm_client is not None:
            planner = AIPlanner.from_llm_client(registry, llm_client)
        else:
            planner = AIPlanner(registry=registry)

        engine = DynamicEngine(registry, planner, self.artifact_store, project_root=self.project_root)

        # Build planner context
        existing_artifacts: dict[ArtifactType, str] = {}
        for art_type in ArtifactType:
            latest = self.artifact_store.get_latest(art_type)
            if latest:
                existing_artifacts[art_type] = latest.id

        context = PlannerContext(
            user_requirements=str(project_input.get("raw_requirements", "")),
            available_artifacts=existing_artifacts,
            constraints=constraints or [],
            goal_artifacts=goal_artifacts or [ArtifactType.SOURCE_CODE],
            project_name=project_name,
        )

        def executor(agent_name: str, skill_name: str, input_data: dict, proj_name: str) -> str:
            return self.execute_task(agent_name, skill_name, input_data, proj_name)

        # Reuse existing plan (e.g., from preview) if provided,
        # to avoid regenerating and getting a different plan.
        if existing_plan and isinstance(existing_plan, dict) and existing_plan.get("steps"):
            from .ai_planner import ExecutionPlan, PlanStep

            reuse_steps = [
                PlanStep(
                    process_id=s.get("process_id", s.get("process", "")),
                    agent=s.get("agent", ""),
                    rationale=s.get("rationale", ""),
                    input_mapping=s.get("input_mapping", {}),
                    depends_on_steps=s.get("depends_on_steps", []),
                )
                for s in existing_plan["steps"]
                if isinstance(s, dict)
            ]
            reuse_plan = ExecutionPlan(
                goal=existing_plan.get("goal", context.user_requirements[:200]),
                steps=reuse_steps,
                reasoning=existing_plan.get("reasoning", "Reused from preview plan"),
            )
            # Auto-resolve any missing dependencies in the reused plan
            reuse_plan = engine._auto_resolve_dependencies(reuse_plan)
            result = engine.run_with_plan(
                reuse_plan,
                executor,
                project_name,
                available_artifacts=context.available_artifacts,
                progress_callback=progress_callback,
                project_input=project_input,
            )
        else:
            result = engine.run(
                context,
                executor,
                project_name,
                progress_callback=progress_callback,
                project_input=project_input,
                selected_process_id=selected_process_id,
            )

        return {
            "status": result.status,
            "step_results": [
                {
                    "process": r.process_id,
                    "agent": r.agent,
                    "status": r.status.value,
                    "artifact_id": r.artifact_id,
                    "error": r.error,
                    "duration": r.duration_seconds,
                }
                for r in result.step_results
            ],
            "artifact_ids": result.artifact_ids,
            "plan": self._serialize_plan(result.plan),
            "replans": result.replans,
            "total_duration": result.total_duration_seconds,
        }

    def preview_dynamic_plan(
        self,
        project_input: dict[str, Any],
        project_name: str = "",
        goal_artifacts: list[ArtifactType] | None = None,
        output_format: str = "text",
    ) -> str:
        """Generate and visualize an execution plan WITHOUT running it.

        Args:
            project_input: Input data (must contain 'raw_requirements').
            project_name: Human-readable project name.
            goal_artifacts: Desired output artifact types.
            output_format: 'text', 'mermaid', 'summary', or 'confirm'.

        Returns:
            Formatted plan visualization string.
        """
        from .ai_planner import AIPlanner, PlannerContext
        from .plan_visualizer import PlanVisualizer
        from .process_registry import ProcessRegistry

        registry = ProcessRegistry.build_default()
        registry.auto_discover_from_agents(self._agents)
        planner = AIPlanner(registry=registry)
        visualizer = PlanVisualizer(registry=registry)

        existing_artifacts: dict[ArtifactType, str] = {}
        for art_type in ArtifactType:
            latest = self.artifact_store.get_latest(art_type)
            if latest:
                existing_artifacts[art_type] = latest.id

        context = PlannerContext(
            user_requirements=str(project_input.get("raw_requirements", "")),
            available_artifacts=existing_artifacts,
            goal_artifacts=goal_artifacts or [ArtifactType.SOURCE_CODE],
            project_name=project_name,
        )

        plan = planner.generate_plan(context)

        formatters = {
            "text": visualizer.to_text_table,
            "mermaid": visualizer.to_mermaid,
            "summary": visualizer.to_summary,
            "confirm": visualizer.to_confirmation_prompt,
        }
        formatter = formatters.get(output_format, visualizer.to_text_table)
        return formatter(plan)

    def preview_plan(
        self,
        project_input: dict[str, Any],
        project_name: str = "",
        llm_client: Any = None,
        goal_artifacts: list[ArtifactType] | None = None,
    ) -> dict[str, Any]:
        """Generate an execution plan and return it as a dict for the UI.

        Unlike preview_dynamic_plan (which returns formatted text),
        this returns the raw plan dict so the web UI can render
        dynamic workflow nodes.
        """
        from .ai_planner import AIPlanner, PlannerContext
        from .process_registry import ProcessRegistry

        registry = ProcessRegistry.build_default()
        registry.auto_discover_from_agents(self._agents)

        if llm_client is not None:
            planner = AIPlanner.from_llm_client(registry, llm_client)
        else:
            planner = AIPlanner(registry=registry)

        existing_artifacts: dict[ArtifactType, str] = {}
        for art_type in ArtifactType:
            latest = self.artifact_store.get_latest(art_type)
            if latest:
                existing_artifacts[art_type] = latest.id

        context = PlannerContext(
            user_requirements=str(project_input.get("raw_requirements", "")),
            available_artifacts=existing_artifacts,
            goal_artifacts=goal_artifacts or [ArtifactType.SOURCE_CODE],
            project_name=project_name,
        )

        plan = planner.generate_plan(context)
        return self._serialize_plan(plan)

    @staticmethod
    def _serialize_plan(plan: Any) -> dict[str, Any]:
        """Serialize an ExecutionPlan to a dict."""
        return {
            "goal": getattr(plan, "goal", ""),
            "reasoning": getattr(plan, "reasoning", ""),
            "steps": [s.to_dict() for s in getattr(plan, "steps", [])],
        }

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
