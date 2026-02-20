"""Shared workflow state for the LangGraph-based multi-agent system."""

from __future__ import annotations

from typing import Annotated, Any

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


class AgentWorkflowState(TypedDict):
    """Shared state flowing through the LangGraph agent workflow.

    This TypedDict is the single source of truth for all information
    passed between nodes in the LangGraph StateGraph.

    The ``messages`` field uses LangGraph's built-in ``add_messages``
    reducer so that each node's messages are appended to (not replaced)
    the conversation history.
    """

    # Conversation history (reduced by add_messages across all nodes)
    messages: Annotated[list[BaseMessage], add_messages]

    # Project context injected at workflow start
    project_name: str
    project_input: dict[str, Any]  # {"raw_requirements": "...", ...}

    # Workflow phase tracking
    current_phase: str  # "requirements" | "design" | "implementation" | "testing" | "complete"
    phase_results: dict[str, Any]  # e.g. {"requirements_product_manager": "completed"}
    artifact_ids: list[str]  # IDs of AISE artifacts produced during the workflow

    # Supervisor routing: set by supervisor node, consumed by conditional edge
    next_agent: str

    # Error propagation – cleared once the error is handled
    error: str | None

    # Iteration counter to prevent infinite supervisor loops
    iteration: int


# Workflow phase ordering
WORKFLOW_PHASES: list[str] = [
    "requirements",
    "design",
    "implementation",
    "testing",
]

# Default phase → primary responsible agent
PHASE_AGENT_MAP: dict[str, str] = {
    "requirements": "product_manager",
    "design": "architect",
    "implementation": "developer",
    "testing": "qa_engineer",
}
