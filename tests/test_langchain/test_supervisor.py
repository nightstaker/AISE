"""Tests for the supervisor routing logic (deterministic fast-path only).

LLM-based routing is tested via mock to avoid requiring real API credentials.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from aise.config import ModelConfig
from aise.langchain.state import PHASE_AGENT_MAP, WORKFLOW_PHASES
from aise.langchain.supervisor import (
    MAX_ITERATIONS,
    _agent_to_phase,
    _determine_next_phase,
    _fallback_route,
    create_supervisor,
)

# ---------------------------------------------------------------------------
# Tests: _determine_next_phase
# ---------------------------------------------------------------------------


def test_determine_next_phase_empty_results() -> None:
    """With no completed phases, should return the first phase."""
    result = _determine_next_phase({}, error=None)
    assert result == WORKFLOW_PHASES[0]


def test_determine_next_phase_first_done() -> None:
    """After requirements completes, should return design."""
    completed = {"requirements_product_manager": "completed"}
    result = _determine_next_phase(completed, error=None)
    assert result == "design"


def test_determine_next_phase_all_done() -> None:
    """After all four phases complete, should return FINISH."""
    completed = {
        "requirements_product_manager": "completed",
        "design_architect": "completed",
        "implementation_developer": "completed",
        "testing_qa_engineer": "completed",
    }
    result = _determine_next_phase(completed, error=None)
    assert result == "FINISH"


def test_determine_next_phase_with_error_returns_empty() -> None:
    """When there is an active error, fast-path defers to LLM (returns empty)."""
    result = _determine_next_phase({}, error="some error")
    assert result == ""


def test_determine_next_phase_partial_completion() -> None:
    """Only the first two phases complete → should return implementation."""
    completed = {
        "requirements_product_manager": "completed",
        "design_architect": "completed",
    }
    result = _determine_next_phase(completed, error=None)
    assert result == "implementation"


# ---------------------------------------------------------------------------
# Tests: _fallback_route
# ---------------------------------------------------------------------------


def test_fallback_route_known_phase() -> None:
    agents = list(PHASE_AGENT_MAP.values())
    result = _fallback_route("requirements", agents)
    assert result == "product_manager"


def test_fallback_route_unknown_phase_returns_first_agent() -> None:
    agents = ["product_manager", "architect"]
    result = _fallback_route("unknown_phase", agents)
    assert result == "product_manager"


def test_fallback_route_empty_agents() -> None:
    result = _fallback_route("requirements", [])
    assert result == "product_manager"


# ---------------------------------------------------------------------------
# Tests: _agent_to_phase
# ---------------------------------------------------------------------------


def test_agent_to_phase_known_agents() -> None:
    for phase, agent in PHASE_AGENT_MAP.items():
        result = _agent_to_phase(agent, "requirements")
        assert result == phase


def test_agent_to_phase_unknown_agent_returns_current() -> None:
    result = _agent_to_phase("unknown_agent", "design")
    assert result == "design"


# ---------------------------------------------------------------------------
# Tests: create_supervisor (deterministic fast-path)
# ---------------------------------------------------------------------------


def _make_state(phase: str, phase_results: dict, error=None, iteration: int = 0) -> dict:
    from langchain_core.messages import HumanMessage

    return {
        "messages": [HumanMessage(content="test")],
        "project_name": "TestProject",
        "project_input": {},
        "current_phase": phase,
        "phase_results": phase_results,
        "artifact_ids": [],
        "next_agent": "",
        "error": error,
        "iteration": iteration,
    }


_SDLC_AGENTS = ["product_manager", "architect", "developer", "qa_engineer"]


@pytest.fixture()
def model_config() -> ModelConfig:
    return ModelConfig(provider="openai", model="gpt-4o", api_key="test-key")


@pytest.fixture(autouse=True)
def _patch_runtime_agent() -> None:
    with patch("aise.langchain.supervisor.create_runtime_agent") as mock_runtime:
        router = MagicMock()
        router.invoke.return_value = json.dumps({"next": "product_manager", "reasoning": "retry"})
        mock_runtime.return_value = router
        yield


def test_supervisor_fast_path_no_phases_done(model_config: ModelConfig) -> None:
    """No phases done → supervisor should route to product_manager."""
    supervisor = create_supervisor(model_config, available_agents=_SDLC_AGENTS)
    state = _make_state("requirements", {})
    result = supervisor(state)

    assert result["next_agent"] == "product_manager"
    assert result["current_phase"] == "requirements"


def test_supervisor_fast_path_advances_to_design(model_config: ModelConfig) -> None:
    supervisor = create_supervisor(model_config, available_agents=_SDLC_AGENTS)
    state = _make_state("requirements", {"requirements_product_manager": "completed"})
    result = supervisor(state)

    assert result["next_agent"] == "architect"
    assert result["current_phase"] == "design"


def test_supervisor_fast_path_finish_when_all_done(model_config: ModelConfig) -> None:
    supervisor = create_supervisor(model_config, available_agents=_SDLC_AGENTS)
    state = _make_state(
        "testing",
        {
            "requirements_product_manager": "completed",
            "design_architect": "completed",
            "implementation_developer": "completed",
            "testing_qa_engineer": "completed",
        },
    )
    result = supervisor(state)

    assert result["next_agent"] == "FINISH"
    assert result["current_phase"] == "complete"


def test_supervisor_max_iterations_terminates(model_config: ModelConfig) -> None:
    """Supervisor must terminate after MAX_ITERATIONS to prevent infinite loops."""
    supervisor = create_supervisor(model_config, available_agents=["product_manager"])
    state = _make_state("requirements", {}, iteration=MAX_ITERATIONS)
    result = supervisor(state)

    assert result["next_agent"] == "FINISH"


def test_supervisor_iteration_increments(model_config: ModelConfig) -> None:
    supervisor = create_supervisor(model_config, available_agents=_SDLC_AGENTS)
    state = _make_state("requirements", {}, iteration=3)
    result = supervisor(state)

    assert result["iteration"] == 4


def test_supervisor_error_falls_back_to_llm(model_config: ModelConfig) -> None:
    """When there is an error, supervisor should still return a valid next_agent."""
    supervisor2 = create_supervisor(model_config, available_agents=["product_manager"])
    state = _make_state("requirements", {}, error="something went wrong")
    result = supervisor2(state)

    assert "next_agent" in result
