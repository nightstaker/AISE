"""LangGraph StateGraph builder for the multi-agent SDLC workflow."""

from __future__ import annotations

from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from ..utils.logging import get_logger
from .state import AgentWorkflowState

logger = get_logger(__name__)


def _route_from_supervisor(state: AgentWorkflowState) -> str:
    """Conditional edge function: reads ``next_agent`` and maps it to a node.

    Returns ``END`` when the supervisor sets ``next_agent`` to ``"FINISH"``.
    """
    next_agent = state.get("next_agent", "")
    if not next_agent or next_agent == "FINISH":
        return END
    return next_agent


def build_workflow_graph(
    agent_nodes: dict[str, Callable[[AgentWorkflowState], dict[str, Any]]],
    supervisor_fn: Callable[[AgentWorkflowState], dict[str, Any]],
) -> Any:
    """Build and compile the LangGraph :class:`StateGraph` for the SDLC workflow.

    Graph topology
    --------------
    ::

        START → supervisor ─┬─→ product_manager ─┐
                            ├─→ architect        ─┤
                            ├─→ developer        ─┤→ (loop back) → supervisor
                            ├─→ qa_engineer      ─┘
                            ├─→ project_manager ──┘
                            └─→ END  (when next_agent == "FINISH")

    Each agent node reports back to the supervisor so it can decide the
    next step — enabling dynamic re-routing, retries, and phase skipping.

    Args:
        agent_nodes: Mapping of agent name → LangGraph node callable.
        supervisor_fn: Supervisor routing function.

    Returns:
        Compiled LangGraph application (``CompiledStateGraph``).
    """
    graph: StateGraph = StateGraph(AgentWorkflowState)

    # Add supervisor node
    graph.add_node("supervisor", supervisor_fn)

    # Add every agent as a graph node; each loops back to the supervisor
    for agent_name, agent_fn in agent_nodes.items():
        graph.add_node(agent_name, agent_fn)
        graph.add_edge(agent_name, "supervisor")

    # Build conditional routing map: agent names + END sentinel
    route_map: dict[str, str] = {name: name for name in agent_nodes}
    route_map[END] = END

    graph.add_conditional_edges(
        "supervisor",
        _route_from_supervisor,
        route_map,
    )

    # Entry point
    graph.add_edge(START, "supervisor")

    compiled = graph.compile()
    logger.info(
        "Workflow graph compiled: nodes=%d agents=%s",
        len(agent_nodes) + 1,
        sorted(agent_nodes.keys()),
    )
    return compiled
