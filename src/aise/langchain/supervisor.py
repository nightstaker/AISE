"""Supervisor agent that routes tasks between AISE agents in the LangGraph workflow."""

from __future__ import annotations

import json
from typing import Any, Callable

from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from ..config import ModelConfig
from ..utils.logging import get_logger
from .deep_agent_adapter import create_runtime_agent, extract_text_from_runtime_result
from .state import PHASE_AGENT_MAP, WORKFLOW_PHASES, AgentWorkflowState

logger = get_logger(__name__)

# Maximum supervisor iterations before forcing termination
MAX_ITERATIONS = 20


class RoutingDecision(BaseModel):
    """Structured output produced by the supervisor LLM."""

    next: str = Field(
        description=(
            "Name of the next agent to activate, or 'FINISH' when all phases are complete. "
            "Must be one of the registered agent names or 'FINISH'."
        )
    )
    reasoning: str = Field(description="One-sentence explanation of why this agent was chosen.")


SUPERVISOR_SYSTEM_TEMPLATE = """\
You are the orchestrator of an AI software development team.

Team members available:
{agent_list}

Workflow phases (execute in this exact order):
1. requirements  → product_manager   (requirement analysis, user stories, PRD)
2. design        → architect         (system design, API design, tech stack)
3. implementation → developer        (code generation, unit tests, bug fixes)
4. testing       → qa_engineer       (test plans, test cases, test automation)

Additional agents (call only when needed for cross-cutting concerns):
- project_manager : progress tracking, status updates
- rd_director     : high-level oversight, critical decisions

Rules:
- Always advance through the workflow phases in order (1 → 2 → 3 → 4).
- A phase is complete when `phase_results` contains a key like "<phase>_<agent>": "completed".
- If an error occurred, route to the same agent to retry before moving on.
- If iteration exceeds {max_iter}, respond with FINISH to prevent infinite loops.
- Once all four phases are complete, respond with FINISH.

Respond ONLY with the structured JSON defined by the schema.
"""


def create_supervisor(
    model_config: ModelConfig,
    available_agents: list[str] | None = None,
) -> Callable[[AgentWorkflowState], dict[str, Any]]:
    """Create a supervisor function for routing tasks in the LangGraph workflow.

    The supervisor uses two strategies:
    1. **Deterministic fast-path**: When the next phase is unambiguous the
       supervisor routes without calling the LLM, keeping latency low.
    2. **LLM-based routing**: When there is ambiguity (errors, skip logic,
       custom agents) the supervisor uses a structured-output LLM call.

    Args:
        model_config: Model configuration for the supervisor LLM.
        available_agents: Explicit list of agent names available in this
            workflow.  Defaults to the four primary SDLC agents.

    Returns:
        A callable that takes an :class:`AgentWorkflowState` and returns
        a partial state update dict with ``next_agent`` and
        ``current_phase`` keys.
    """
    agents = available_agents or list(PHASE_AGENT_MAP.values())
    routing_options = agents + ["FINISH"]

    llm = _build_supervisor_llm(model_config)

    agent_list_str = "\n".join(f"  - {a}" for a in agents)
    system_prompt = SUPERVISOR_SYSTEM_TEMPLATE.format(
        agent_list=agent_list_str,
        max_iter=MAX_ITERATIONS,
    )
    router_agent = create_runtime_agent(llm, [], system_prompt)

    def supervisor(state: AgentWorkflowState) -> dict[str, Any]:
        """Decide which agent should act next and update the routing state."""
        phase = state.get("current_phase", "requirements")
        phase_results = state.get("phase_results", {})
        error = state.get("error")
        iteration = state.get("iteration", 0)

        logger.info(
            "Supervisor routing: phase=%s completed=%s error=%s iteration=%d",
            phase,
            list(phase_results.keys()),
            error,
            iteration,
        )

        # Safety valve: avoid infinite loops
        if iteration >= MAX_ITERATIONS:
            logger.warning("Supervisor: max iterations reached, finishing")
            return {"next_agent": "FINISH", "current_phase": "complete", "iteration": iteration + 1}

        # --- Deterministic fast-path ---
        phase_agent_pairs = _phase_agent_pairs_from_state(state, agents)
        next_phase = _determine_next_phase(phase_results, error, phase_agent_pairs=phase_agent_pairs)

        if next_phase == "FINISH":
            logger.info("Supervisor fast-path: all phases complete")
            return {"next_agent": "FINISH", "current_phase": "complete", "iteration": iteration + 1}

        if not error and next_phase:
            phase_to_agent = {phase_name: agent_name for phase_name, agent_name in phase_agent_pairs}
            next_agent = phase_to_agent.get(next_phase, PHASE_AGENT_MAP.get(next_phase, "product_manager"))
            if next_agent in agents:
                logger.info(
                    "Supervisor fast-path: phase=%s agent=%s",
                    next_phase,
                    next_agent,
                )
                return {
                    "next_agent": next_agent,
                    "current_phase": next_phase,
                    "iteration": iteration + 1,
                }

        # --- LLM-based routing ---
        context_summary = (
            f"Current phase: {phase}\n"
            f"Completed work: {list(phase_results.keys())}\n"
            f"Error: {error or 'none'}\n"
            f"Iteration: {iteration}"
        )

        try:
            decision = _route_with_runtime(
                router_agent=router_agent,
                context_summary=context_summary,
                routing_options=routing_options,
            )
            next_agent = decision.next if decision.next in routing_options else _fallback_route(phase, agents)
            logger.info(
                "Supervisor routing decision: next=%s reason=%s backend=deepagents",
                next_agent,
                decision.reasoning,
            )
        except Exception as exc:
            logger.warning("Supervisor LLM failed, using fallback: error=%s", exc)
            next_agent = _fallback_route(phase, agents)

        if next_agent == "FINISH":
            return {"next_agent": "FINISH", "current_phase": "complete", "iteration": iteration + 1}

        # Update current_phase to match the chosen agent's primary phase
        new_phase = _agent_to_phase(next_agent, phase, phase_agent_pairs=phase_agent_pairs)
        return {
            "next_agent": next_agent,
            "current_phase": new_phase,
            "iteration": iteration + 1,
            "error": None,  # Clear error after re-routing
        }

    return supervisor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _determine_next_phase(
    phase_results: dict[str, Any],
    error: str | None,
    phase_agent_pairs: list[tuple[str, str]] | None = None,
) -> str:
    """Return the next workflow phase that still needs work.

    Iterates through ``WORKFLOW_PHASES`` in order and returns the first
    phase whose completion key is absent from ``phase_results``.
    Returns ``"FINISH"`` when all phases are done.
    """
    if error:
        # Let LLM handle the retry logic
        return ""

    pairs = phase_agent_pairs or [(phase_name, PHASE_AGENT_MAP[phase_name]) for phase_name in WORKFLOW_PHASES]
    for phase, agent in pairs:
        completion_key = f"{phase}_{agent}"
        if completion_key not in phase_results:
            return phase

    return "FINISH"


def _fallback_route(current_phase: str, agents: list[str]) -> str:
    """Deterministic fallback routing when the LLM call fails."""
    agent = PHASE_AGENT_MAP.get(current_phase)
    if agent and agent in agents:
        return agent
    return agents[0] if agents else "product_manager"


def _agent_to_phase(
    agent_name: str,
    current_phase: str,
    phase_agent_pairs: list[tuple[str, str]] | None = None,
) -> str:
    """Map an agent name back to its primary workflow phase."""
    pairs = phase_agent_pairs or list(PHASE_AGENT_MAP.items())
    for phase, agent in pairs:
        if agent == agent_name:
            return phase
    return current_phase  # Keep current phase for cross-cutting agents


def _phase_agent_pairs_from_state(
    state: AgentWorkflowState,
    available_agents: list[str],
) -> list[tuple[str, str]]:
    """Read workflow plan from state, falling back to static phase mapping."""
    project_input = state.get("project_input", {})
    plan_data = project_input.get("_workflow_plan", []) if isinstance(project_input, dict) else []
    fallback = [(phase_name, PHASE_AGENT_MAP[phase_name]) for phase_name in WORKFLOW_PHASES]

    if not isinstance(plan_data, list):
        return fallback

    parsed: list[tuple[str, str]] = []
    for item in plan_data:
        if not isinstance(item, dict):
            continue
        phase = str(item.get("phase", "")).strip()
        agent = str(item.get("agent", "")).strip()
        if not phase or not agent:
            continue
        if agent not in available_agents:
            continue
        parsed.append((phase, agent))

    return parsed or fallback


def _route_with_runtime(
    *,
    router_agent: Any,
    context_summary: str,
    routing_options: list[str],
) -> RoutingDecision:
    """Route via deep agent runtime and return normalized decision."""
    prompt = (
        "Current state:\n"
        f"{context_summary}\n\n"
        f"Allowed next values: {routing_options}\n"
        'Return STRICT JSON: {"next":"...", "reasoning":"..."}'
    )
    raw = router_agent.invoke({"messages": [HumanMessage(content=prompt)]})
    text = extract_text_from_runtime_result(raw)
    payload = json.loads(text)
    return RoutingDecision.model_validate(payload)


def _build_supervisor_llm(config: ModelConfig) -> ChatOpenAI:
    """Build the supervisor ChatOpenAI LLM with low temperature for determinism."""
    kwargs: dict[str, Any] = {
        "model": config.model,
        "temperature": 0.0,  # Deterministic routing
        "max_tokens": 256,  # Routing decisions are short
    }
    if config.api_key:
        kwargs["api_key"] = config.api_key
    if config.base_url:
        kwargs["base_url"] = config.base_url

    return ChatOpenAI(**kwargs)
