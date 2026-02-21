"""LangChain Deep Agent orchestrator — replaces the rule-based WorkflowEngine.

This module provides :class:`DeepOrchestrator`, which redesigns the
multi-agent management and scheduling system using:

* **LangChain ReAct agents** — each AISE agent becomes a reasoning agent
  that can plan and execute its skills via tool calls.
* **LangChain StructuredTools** — every AISE :class:`~aise.core.skill.Skill`
  is exposed as a typed tool that the agent can invoke with JSON arguments.
* **LangGraph StateGraph** — the SDLC workflow is a directed graph with
  conditional edges, enabling dynamic routing, retries, and parallel phases.
* **Supervisor pattern** — a supervisor node uses structured LLM output to
  route tasks to the correct agent at each step.

The :class:`DeepOrchestrator` wraps the existing :class:`Orchestrator`
so that all existing agent registrations, skills, artifacts, and configs
continue to work without modification.
"""

from __future__ import annotations

from typing import Any

from langchain_core.messages import HumanMessage

from ..config import ModelConfig, ProjectConfig
from ..core.agent import Agent
from ..core.artifact import ArtifactStore
from ..core.orchestrator import Orchestrator
from ..core.skill import SkillContext
from ..utils.logging import get_logger
from .agent_node import make_agent_node
from .graph import build_workflow_graph
from .state import PHASE_AGENT_MAP, AgentWorkflowState
from .supervisor import create_supervisor

logger = get_logger(__name__)


class DeepOrchestrator:
    """LangChain Deep Agent orchestrator for multi-agent SDLC workflows.

    Architecture
    ------------
    The orchestrator translates the existing AISE agent/skill/artifact
    model into a LangGraph ``StateGraph``::

        AISE Agent  ──wrap──► LangChain ReAct agent node
        AISE Skill  ──wrap──► LangChain StructuredTool
        Orchestrator ─────►  DeepOrchestrator (this class)
        WorkflowEngine ───►  LangGraph StateGraph

    Workflow execution proceeds through four SDLC phases:

    1. **Requirements** — ``product_manager`` agent
    2. **Design** — ``architect`` agent
    3. **Implementation** — ``developer`` agent
    4. **Testing** — ``qa_engineer`` agent

    A supervisor LLM decides which agent to invoke next based on the
    current workflow state, enabling adaptive routing and retry logic.

    Usage
    -----
    ::

        orchestrator = create_team(config)  # existing factory
        deep = DeepOrchestrator.from_orchestrator(orchestrator, config)
        result = deep.run_workflow(
            {"raw_requirements": "Build a REST API ..."},
            project_name="MyProject",
        )

    Parameters
    ----------
    orchestrator:
        Existing AISE :class:`~aise.core.orchestrator.Orchestrator` with
        registered agents and skills.
    project_config:
        Project-level configuration for model selection, GitHub mode, etc.
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        project_config: ProjectConfig | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.config = project_config
        self._graph: Any = None  # Compiled LangGraph app
        self._agent_nodes: dict[str, Any] = {}
        self._supervisor_fn: Any = None

        logger.info("DeepOrchestrator initialized: agents=%s", list(orchestrator.agents.keys()))

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def build(self) -> None:
        """Build the LangGraph workflow graph from registered agents.

        This step constructs:
        1. A :class:`~aise.langchain.tool_adapter.SkillTool` per skill
        2. A ReAct agent node per AISE agent
        3. A supervisor routing node
        4. A compiled :class:`~langgraph.graph.StateGraph`

        Call this explicitly or let :meth:`run_workflow` call it lazily.
        """
        agents = self.orchestrator.agents
        artifact_store = self.orchestrator.artifact_store
        default_model = self.config.default_model if self.config else ModelConfig()
        project_name = self.config.project_name if self.config else ""

        agent_nodes: dict[str, Any] = {}

        for agent_name, agent in agents.items():
            context = SkillContext(
                artifact_store=artifact_store,
                project_name=project_name,
                parameters={},
                model_config=agent.model_config,
                llm_client=agent.llm_client,
            )
            node_fn = make_agent_node(agent, context, agent.model_config)
            agent_nodes[agent_name] = node_fn
            logger.debug("Agent node registered: agent=%s", agent_name)

        supervisor_fn = create_supervisor(
            model_config=default_model,
            available_agents=list(agent_nodes.keys()),
        )

        self._graph = build_workflow_graph(agent_nodes, supervisor_fn)
        self._agent_nodes = agent_nodes
        self._supervisor_fn = supervisor_fn

        logger.info(
            "DeepOrchestrator graph built: agent_nodes=%d",
            len(agent_nodes),
        )

    # ------------------------------------------------------------------
    # Workflow execution
    # ------------------------------------------------------------------

    def run_workflow(
        self,
        project_input: dict[str, Any],
        project_name: str = "",
    ) -> dict[str, Any]:
        """Run the full SDLC workflow using LangGraph.

        Invokes the compiled graph with an initial state and waits for
        completion (``next_agent == "FINISH"``).

        Args:
            project_input: Seed data for the workflow, e.g.
                ``{"raw_requirements": "Build a REST API ..."}``.
            project_name: Human-readable project name injected into all
                agent task prompts and artifact metadata.

        Returns:
            Dictionary with:

            * ``status``: ``"completed"`` or ``"error"``
            * ``phase_results``: Per-phase completion flags
            * ``artifact_ids``: IDs of artifacts produced
            * ``messages``: Last few assistant messages (for debugging)
            * ``error``: Error message if ``status == "error"``
        """
        if self._graph is None:
            self.build()

        name = project_name or (self.config.project_name if self.config else "")

        initial_state: AgentWorkflowState = {
            "messages": [HumanMessage(content=f"Start SDLC workflow for project: {name}")],
            "project_name": name,
            "project_input": project_input,
            "current_phase": "requirements",
            "phase_results": {},
            "artifact_ids": [],
            "next_agent": PHASE_AGENT_MAP["requirements"],  # Start with product manager
            "error": None,
            "iteration": 0,
        }

        logger.info(
            "DeepOrchestrator workflow starting: project=%s input_keys=%s",
            name,
            sorted(project_input.keys()),
        )

        try:
            final_state = self._graph.invoke(initial_state)

            phase_results = final_state.get("phase_results", {})
            artifact_ids = final_state.get("artifact_ids", [])
            last_messages = [m.content for m in final_state.get("messages", [])[-3:] if hasattr(m, "content")]

            logger.info(
                "DeepOrchestrator workflow completed: project=%s phases=%s artifacts=%d",
                name,
                list(phase_results.keys()),
                len(artifact_ids),
            )

            return {
                "status": "completed",
                "phase_results": phase_results,
                "artifact_ids": artifact_ids,
                "messages": last_messages,
            }

        except Exception as exc:
            logger.error(
                "DeepOrchestrator workflow failed: project=%s error=%s",
                name,
                exc,
            )
            return {
                "status": "error",
                "error": str(exc),
                "phase_results": {},
                "artifact_ids": [],
                "messages": [],
            }

    # ------------------------------------------------------------------
    # Convenience accessors (delegate to wrapped Orchestrator)
    # ------------------------------------------------------------------

    @property
    def artifact_store(self) -> ArtifactStore:
        """Shared artifact store from the underlying AISE Orchestrator."""
        return self.orchestrator.artifact_store

    @property
    def agents(self) -> dict[str, Agent]:
        """All agents registered with the underlying AISE Orchestrator."""
        return self.orchestrator.agents

    def execute_task(
        self,
        agent_name: str,
        skill_name: str,
        input_data: dict[str, Any],
        project_name: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> str:
        """Delegate a single task to the underlying Orchestrator.

        This preserves backward compatibility — callers that use
        ``execute_task`` directly continue to work unchanged.
        """
        return self.orchestrator.execute_task(
            agent_name=agent_name,
            skill_name=skill_name,
            input_data=input_data,
            project_name=project_name,
            parameters=parameters,
        )

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_orchestrator(
        cls,
        orchestrator: Orchestrator,
        config: ProjectConfig | None = None,
    ) -> "DeepOrchestrator":
        """Create a :class:`DeepOrchestrator` wrapping an existing Orchestrator.

        Args:
            orchestrator: A fully configured AISE Orchestrator with agents.
            config: Optional project configuration.

        Returns:
            A new :class:`DeepOrchestrator` instance (graph not yet built).
        """
        return cls(orchestrator=orchestrator, project_config=config)

    def __repr__(self) -> str:
        graph_status = "built" if self._graph else "not built"
        return f"DeepOrchestrator(agents={list(self.agents.keys())}, graph={graph_status})"
