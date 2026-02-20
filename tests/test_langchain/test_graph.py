"""Tests for the LangGraph StateGraph builder."""

from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, HumanMessage

from aise.langchain.graph import _route_from_supervisor, build_workflow_graph
from aise.langchain.state import AgentWorkflowState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_state(next_agent: str = "") -> AgentWorkflowState:
    return {
        "messages": [HumanMessage(content="test")],
        "project_name": "TestProject",
        "project_input": {},
        "current_phase": "requirements",
        "phase_results": {},
        "artifact_ids": [],
        "next_agent": next_agent,
        "error": None,
        "iteration": 0,
    }


# ---------------------------------------------------------------------------
# Tests: _route_from_supervisor
# ---------------------------------------------------------------------------


def test_route_from_supervisor_returns_agent_name() -> None:

    state = _make_state(next_agent="product_manager")
    result = _route_from_supervisor(state)
    assert result == "product_manager"


def test_route_from_supervisor_finish_returns_end() -> None:
    from langgraph.graph import END

    state = _make_state(next_agent="FINISH")
    result = _route_from_supervisor(state)
    assert result is END


def test_route_from_supervisor_empty_returns_end() -> None:
    from langgraph.graph import END

    state = _make_state(next_agent="")
    result = _route_from_supervisor(state)
    assert result is END


# ---------------------------------------------------------------------------
# Tests: build_workflow_graph
# ---------------------------------------------------------------------------


def test_build_workflow_graph_compiles_successfully() -> None:
    """Graph builds without error when given valid agent nodes and supervisor."""

    def dummy_agent(state: AgentWorkflowState) -> dict[str, Any]:
        return {"messages": [AIMessage(content="done")], "phase_results": {"requirements_product_manager": "completed"}}

    def dummy_supervisor(state: AgentWorkflowState) -> dict[str, Any]:
        return {"next_agent": "FINISH", "current_phase": "complete", "iteration": 1}

    graph = build_workflow_graph(
        agent_nodes={"product_manager": dummy_agent},
        supervisor_fn=dummy_supervisor,
    )
    assert graph is not None


def test_build_workflow_graph_is_invocable() -> None:
    """The compiled graph should be invocable and return a final state."""
    call_log: list[str] = []

    def dummy_pm(state: AgentWorkflowState) -> dict[str, Any]:
        call_log.append("pm")
        return {
            "messages": [AIMessage(content="PM done")],
            "phase_results": {"requirements_product_manager": "completed"},
            "error": None,
        }

    iteration_count = 0

    def dummy_supervisor(state: AgentWorkflowState) -> dict[str, Any]:
        nonlocal iteration_count
        iteration_count += 1
        # First call: send to PM; subsequent: FINISH
        if state.get("phase_results", {}).get("requirements_product_manager") == "completed":
            return {"next_agent": "FINISH", "current_phase": "complete", "iteration": iteration_count}
        return {"next_agent": "product_manager", "current_phase": "requirements", "iteration": iteration_count}

    graph = build_workflow_graph(
        agent_nodes={"product_manager": dummy_pm},
        supervisor_fn=dummy_supervisor,
    )

    initial_state: AgentWorkflowState = {
        "messages": [HumanMessage(content="start")],
        "project_name": "Test",
        "project_input": {"raw_requirements": "build something"},
        "current_phase": "requirements",
        "phase_results": {},
        "artifact_ids": [],
        "next_agent": "product_manager",
        "error": None,
        "iteration": 0,
    }

    final_state = graph.invoke(initial_state)

    assert "pm" in call_log  # PM node was invoked
    assert final_state["phase_results"].get("requirements_product_manager") == "completed"


def test_build_workflow_graph_multiple_agents() -> None:
    """Graph with multiple agents compiles and routes correctly."""

    outcomes: list[str] = []

    def make_agent(name: str):
        def agent_fn(state: AgentWorkflowState) -> dict[str, Any]:
            outcomes.append(name)
            phase = state["current_phase"]
            return {
                "messages": [AIMessage(content=f"{name} done")],
                "phase_results": {**state.get("phase_results", {}), f"{phase}_{name}": "completed"},
                "error": None,
            }

        agent_fn.__name__ = name
        return agent_fn

    agents = {
        "product_manager": make_agent("product_manager"),
        "architect": make_agent("architect"),
    }

    phase_map = {"requirements": "product_manager", "design": "architect"}

    sup_calls = 0

    def supervisor(state: AgentWorkflowState) -> dict[str, Any]:
        nonlocal sup_calls
        sup_calls += 1
        results = state.get("phase_results", {})
        for phase, agent in phase_map.items():
            if f"{phase}_{agent}" not in results:
                return {"next_agent": agent, "current_phase": phase, "iteration": sup_calls}
        return {"next_agent": "FINISH", "current_phase": "complete", "iteration": sup_calls}

    graph = build_workflow_graph(agent_nodes=agents, supervisor_fn=supervisor)

    initial: AgentWorkflowState = {
        "messages": [HumanMessage(content="start")],
        "project_name": "Test",
        "project_input": {},
        "current_phase": "requirements",
        "phase_results": {},
        "artifact_ids": [],
        "next_agent": "product_manager",
        "error": None,
        "iteration": 0,
    }

    final = graph.invoke(initial)

    assert "product_manager" in outcomes
    assert "architect" in outcomes
    assert "requirements_product_manager" in final["phase_results"]
    assert "design_architect" in final["phase_results"]
