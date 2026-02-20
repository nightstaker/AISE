"""Tests for the AgentWorkflowState TypedDict and constants."""

from __future__ import annotations

from aise.langchain.state import (
    PHASE_AGENT_MAP,
    WORKFLOW_PHASES,
    AgentWorkflowState,
)


def test_workflow_phases_order() -> None:
    """Workflow phases must follow the SDLC order."""
    assert WORKFLOW_PHASES == ["requirements", "design", "implementation", "testing"]


def test_phase_agent_map_keys_match_phases() -> None:
    """Every workflow phase must have a mapped agent."""
    for phase in WORKFLOW_PHASES:
        assert phase in PHASE_AGENT_MAP, f"Phase '{phase}' missing from PHASE_AGENT_MAP"


def test_phase_agent_map_values() -> None:
    """Validate the expected default agent assignments."""
    assert PHASE_AGENT_MAP["requirements"] == "product_manager"
    assert PHASE_AGENT_MAP["design"] == "architect"
    assert PHASE_AGENT_MAP["implementation"] == "developer"
    assert PHASE_AGENT_MAP["testing"] == "qa_engineer"


def test_agent_workflow_state_is_typed_dict() -> None:
    """AgentWorkflowState must be instantiable as a plain dict."""
    from langchain_core.messages import HumanMessage

    state: AgentWorkflowState = {
        "messages": [HumanMessage(content="hello")],
        "project_name": "TestProject",
        "project_input": {"raw_requirements": "Build something"},
        "current_phase": "requirements",
        "phase_results": {},
        "artifact_ids": [],
        "next_agent": "product_manager",
        "error": None,
        "iteration": 0,
    }

    assert state["project_name"] == "TestProject"
    assert state["current_phase"] == "requirements"
    assert state["next_agent"] == "product_manager"
    assert state["iteration"] == 0
    assert state["error"] is None


def test_phase_agent_map_no_duplicate_agents() -> None:
    """Each phase should have a unique primary agent (no two phases share one)."""
    agents = list(PHASE_AGENT_MAP.values())
    assert len(agents) == len(set(agents)), "Duplicate primary agents in PHASE_AGENT_MAP"
