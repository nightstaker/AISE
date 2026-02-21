"""LangChain ReAct agent nodes that wrap AISE agents for LangGraph integration."""

from __future__ import annotations

from typing import Any, Callable

from langchain.agents import create_agent
from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from ..config import ModelConfig
from ..core.skill import SkillContext
from ..utils.logging import get_logger
from .state import AgentWorkflowState
from .tool_adapter import create_agent_tools

logger = get_logger(__name__)


# System prompt templates per agent role.
# Each prompt explains the agent's responsibilities so the LLM can reason
# about which skills to call and in what order.
AGENT_SYSTEM_PROMPTS: dict[str, str] = {
    "product_manager": (
        "You are an expert Product Manager in an AI software development team.\n\n"
        "Responsibilities:\n"
        "- Analyse raw requirements and extract structured functional / non-functional requirements\n"
        "- Produce user stories with clear acceptance criteria\n"
        "- Design product features and write a Product Requirements Document (PRD)\n"
        "- Ensure requirements are complete, unambiguous, and testable\n\n"
        "Use your available tools to execute each task systematically. "
        "Call every skill that is relevant to the current phase."
    ),
    "architect": (
        "You are an expert Software Architect in an AI software development team.\n\n"
        "Responsibilities:\n"
        "- Design the overall system architecture and component breakdown\n"
        "- Define API contracts and inter-service interfaces\n"
        "- Select the appropriate technology stack\n"
        "- Produce architecture requirements for the development team\n"
        "- Document all architectural decisions\n\n"
        "Use your available tools to execute each task systematically. "
        "Call every skill that is relevant to the current phase."
    ),
    "developer": (
        "You are an expert Software Developer in an AI software development team.\n\n"
        "Responsibilities:\n"
        "- Generate production-quality code from architecture design and API contracts\n"
        "- Write unit tests using the TDD (Test-Driven Development) approach\n"
        "- Fix bugs and code quality issues\n"
        "- Perform code reviews to ensure quality and maintainability\n\n"
        "Use your available tools to execute each task systematically. "
        "Call every skill that is relevant to the current phase."
    ),
    "qa_engineer": (
        "You are an expert QA Engineer in an AI software development team.\n\n"
        "Responsibilities:\n"
        "- Design comprehensive test plans covering all system features\n"
        "- Create detailed, executable test cases\n"
        "- Implement test automation using appropriate frameworks\n"
        "- Review and validate test coverage across all requirements\n\n"
        "Use your available tools to execute each task systematically. "
        "Call every skill that is relevant to the current phase."
    ),
    "project_manager": (
        "You are an expert Project Manager in an AI software development team.\n\n"
        "Responsibilities:\n"
        "- Track project progress and report status across all phases\n"
        "- Monitor team health and workload distribution\n"
        "- Distribute requirements to development team members\n"
        "- Generate clear, actionable status reports\n\n"
        "Use your available tools to execute each task systematically."
    ),
    "rd_director": (
        "You are the Research & Development Director overseeing the entire team.\n\n"
        "Responsibilities:\n"
        "- Monitor overall project quality and technical health\n"
        "- Make high-level technical and process decisions\n"
        "- Coordinate between product, architecture, and engineering teams\n"
        "- Ensure quality standards and delivery targets are met\n\n"
        "Use your available tools to execute each task systematically."
    ),
    "reviewer": (
        "You are a Senior Reviewer in an AI software development team.\n\n"
        "Responsibilities:\n"
        "- Review code, architecture, and product decisions\n"
        "- Provide constructive, actionable feedback\n"
        "- Approve or reject work products based on quality criteria\n\n"
        "Use your available tools to execute each task systematically."
    ),
}

_DEFAULT_SYSTEM_PROMPT = (
    "You are an AI agent in a software development team. Use your available tools to complete the requested task."
)


def make_agent_node(
    agent: Any,
    context: SkillContext,
    model_config: ModelConfig | None = None,
) -> Callable[[AgentWorkflowState], dict[str, Any]]:
    """Create a LangGraph node function for an AISE agent.

    The returned callable takes an :class:`AgentWorkflowState` dict and
    returns a partial state update.  Internally it builds a LangChain
    ReAct agent that can invoke any of the agent's registered skills as
    LangChain tools.

    Args:
        agent: An :class:`~aise.core.agent.Agent` instance with skills.
        context: Shared :class:`~aise.core.skill.SkillContext`.
        model_config: Override model config (defaults to agent's config).

    Returns:
        A state-update function suitable for use as a LangGraph node.
    """
    tools = create_agent_tools(agent, context)
    cfg = model_config or agent.model_config
    llm = _build_llm(cfg)

    system_prompt = AGENT_SYSTEM_PROMPTS.get(agent.name, _DEFAULT_SYSTEM_PROMPT)
    react_agent = create_agent(llm, tools, system_prompt=system_prompt)

    _agent_name = agent.name

    def agent_node(state: AgentWorkflowState) -> dict[str, Any]:
        """Execute the agent's work for the current workflow state.

        Constructs a task description from the state, invokes the ReAct
        agent, and returns the resulting messages and phase completion flag.
        """
        phase = state.get("current_phase", "unknown")
        project = state.get("project_name", "")
        project_input = state.get("project_input", {})
        raw_req = str(project_input.get("raw_requirements", ""))[:600]

        logger.info(
            "Agent node invoked: agent=%s phase=%s project=%s",
            _agent_name,
            phase,
            project,
        )

        task_prompt = (
            f"Project: {project}\n"
            f"Current phase: {phase}\n"
            f"Your role in this phase: execute all skills required for the "
            f"'{phase}' phase of the '{_agent_name}' role.\n"
            f"Requirements summary: {raw_req}\n\n"
            f"Please execute the appropriate skills now."
        )

        try:
            result = react_agent.invoke({"messages": [HumanMessage(content=task_prompt)]})

            result_messages = result.get("messages", [])
            final_message = (
                result_messages[-1]
                if result_messages
                else AIMessage(content=f"{_agent_name} completed work for phase '{phase}'.")
            )

            logger.info(
                "Agent node completed: agent=%s phase=%s",
                _agent_name,
                phase,
            )

            return {
                "messages": [final_message],
                "phase_results": {
                    **state.get("phase_results", {}),
                    f"{phase}_{_agent_name}": "completed",
                },
                "error": None,
            }

        except Exception as exc:
            logger.warning(
                "Agent node error: agent=%s phase=%s error=%s",
                _agent_name,
                phase,
                exc,
            )
            return {
                "messages": [AIMessage(content=f"[{_agent_name}] Error: {exc}")],
                "error": str(exc),
            }

    agent_node.__name__ = _agent_name
    return agent_node


def _build_llm(config: ModelConfig) -> ChatOpenAI:
    """Build a ChatOpenAI instance from an AISE :class:`ModelConfig`.

    Uses the model config's provider base URL and API key if set so that
    the agent can work with any OpenAI-compatible backend.
    """
    kwargs: dict[str, Any] = {
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
    if config.api_key:
        kwargs["api_key"] = config.api_key
    if config.base_url:
        kwargs["base_url"] = config.base_url

    return ChatOpenAI(**kwargs)
