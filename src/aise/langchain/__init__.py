"""LangChain Deep Agent integration for AISE multi-agent orchestration.

This package redesigns the AISE multi-agent management and scheduling
system using LangChain's agent framework and LangGraph's StateGraph:

Modules
-------
state
    Shared :class:`AgentWorkflowState` TypedDict and workflow constants.
tool_adapter
    Adapts AISE :class:`~aise.core.skill.Skill` objects to LangChain
    :class:`~langchain_core.tools.StructuredTool` instances.
agent_node
    LangChain ReAct agent node factories for each AISE agent role.
supervisor
    Supervisor routing agent that decides which agent acts next.
graph
    LangGraph :class:`~langgraph.graph.StateGraph` builder for the
    full SDLC workflow.
deep_orchestrator
    High-level :class:`DeepOrchestrator` that ties everything together
    and exposes a drop-in interface for the existing Orchestrator.
"""

from .deep_orchestrator import DeepOrchestrator
from .graph import build_workflow_graph
from .state import PHASE_AGENT_MAP, WORKFLOW_PHASES, AgentWorkflowState
from .supervisor import create_supervisor
from .tool_adapter import create_agent_tools, create_skill_tool

__all__ = [
    "AgentWorkflowState",
    "DeepOrchestrator",
    "PHASE_AGENT_MAP",
    "WORKFLOW_PHASES",
    "build_workflow_graph",
    "create_agent_tools",
    "create_skill_tool",
    "create_supervisor",
]
