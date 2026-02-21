"""LangChain ReAct agent nodes that wrap AISE agents for LangGraph integration."""

from __future__ import annotations

from typing import Any, Callable

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from ..config import ModelConfig
from ..core.artifact import ArtifactType
from ..core.skill import SkillContext
from ..utils.logging import get_logger
from .deep_agent_adapter import create_runtime_agent, extract_text_from_runtime_result
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

PHASE_SKILL_PLAYBOOK: dict[str, dict[str, list[str]]] = {
    "product_manager": {
        "requirements": [
            "requirement_analysis",
            "system_feature_analysis",
            "system_requirement_analysis",
            "user_story_writing",
            "product_design",
            "product_review",
            "document_generation",
        ]
    },
    "architect": {
        "design": [
            "system_design",
            "api_design",
            "tech_stack_selection",
            "architecture_requirement_analysis",
            "functional_design",
            "status_tracking",
            "architecture_document_generation",
        ]
    },
    "developer": {
        "implementation": [
            "code_generation",
            "unit_test_writing",
            "tdd_session",
            "code_review",
            "bug_fix",
        ]
    },
    "qa_engineer": {
        "testing": [
            "test_plan_design",
            "test_case_design",
            "test_automation",
            "test_review",
        ]
    },
    "project_manager": {
        "requirements": ["progress_tracking", "team_health", "conflict_resolution"],
        "design": ["progress_tracking", "team_health", "conflict_resolution"],
        "implementation": ["progress_tracking", "team_health", "conflict_resolution"],
        "testing": ["progress_tracking", "team_health", "conflict_resolution", "version_release"],
    },
    "rd_director": {
        "requirements": ["team_formation", "requirement_distribution"],
    },
    "reviewer": {
        "testing": ["code_review", "pr_review", "pr_merge"],
    },
}

SKILL_INPUT_HINTS: dict[str, list[str]] = {
    "requirement_analysis": ["raw_requirements"],
    "system_feature_analysis": ["raw_requirements", "requirements"],
    "system_requirement_analysis": ["system_design"],
    "user_story_writing": ["requirements"],
    "product_design": ["requirements", "user_stories", "review_feedback"],
    "product_review": ["requirements", "prd"],
    "document_generation": ["system_design", "system_requirements", "output_dir"],
    "system_design": ["requirements"],
    "api_design": ["requirements"],
    "tech_stack_selection": ["requirements"],
    "architecture_requirement_analysis": ["requirements"],
    "functional_design": ["requirements"],
    "status_tracking": ["requirements"],
    "architecture_document_generation": ["output_dir"],
    "code_generation": ["requirements", "system_design", "api_contract", "functional_design"],
    "unit_test_writing": ["source_code", "requirements"],
    "tdd_session": ["requirements", "source_code"],
    "code_review": ["source_code", "requirements"],
    "bug_fix": ["source_code", "test_report", "bug_report"],
    "test_plan_design": ["requirements", "system_design"],
    "test_case_design": ["test_plan", "requirements"],
    "test_automation": ["test_cases", "source_code"],
    "test_review": ["test_plan", "test_cases", "automated_tests"],
    "progress_tracking": ["phase_results", "artifact_ids"],
    "team_health": ["agent_registry", "message_history", "task_statuses"],
    "conflict_resolution": ["topic", "options", "constraints"],
    "version_release": ["release_notes", "version"],
    "team_formation": ["roles", "development_mode"],
    "requirement_distribution": ["product_requirements", "architecture_requirements"],
    "pr_review": ["pr_number", "feedback", "event"],
    "pr_merge": ["pr_number", "merge_method", "commit_title"],
}


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
    runtime_agent = create_runtime_agent(llm, tools, system_prompt)

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
        skill_names = list(agent.skills.keys())
        ordered_skills = _suggest_skills_for_phase(_agent_name, phase, skill_names)
        defaults = _build_default_input_data(context, state, phase)

        context.parameters.clear()
        context.parameters.update(
            {
                "phase": phase,
                "agent_name": _agent_name,
                "project_name": project,
                "input_defaults": defaults,
            }
        )

        logger.info(
            "Agent node invoked: agent=%s phase=%s project=%s backend=deepagents",
            _agent_name,
            phase,
            project,
        )

        task_prompt = _build_task_prompt(
            agent_name=_agent_name,
            phase=phase,
            project=project,
            raw_requirements=raw_req,
            available_skills=skill_names,
            ordered_skills=ordered_skills,
            defaults=defaults,
        )

        try:
            result = runtime_agent.invoke({"messages": [HumanMessage(content=task_prompt)]})
            final_message = _to_ai_message(result, _agent_name, phase)

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


def _suggest_skills_for_phase(
    agent_name: str,
    phase: str,
    skill_names: list[str],
) -> list[str]:
    playbook = PHASE_SKILL_PLAYBOOK.get(agent_name, {})
    preferred = playbook.get(phase, [])
    selected = [skill for skill in preferred if skill in skill_names]
    remainder = [skill for skill in skill_names if skill not in selected]
    return selected + remainder


def _build_default_input_data(
    context: SkillContext,
    state: AgentWorkflowState,
    phase: str,
) -> dict[str, Any]:
    project_input = state.get("project_input", {})
    defaults: dict[str, Any] = {}
    if isinstance(project_input, dict):
        defaults.update(project_input)
    defaults["phase_results"] = state.get("phase_results", {})
    defaults["artifact_ids"] = state.get("artifact_ids", [])
    defaults["current_phase"] = phase

    latest_by_type = {
        ArtifactType.REQUIREMENTS: "requirements",
        ArtifactType.USER_STORIES: "user_stories",
        ArtifactType.PRD: "prd",
        ArtifactType.SYSTEM_DESIGN: "system_design",
        ArtifactType.SYSTEM_REQUIREMENTS: "system_requirements",
        ArtifactType.API_CONTRACT: "api_contract",
        ArtifactType.FUNCTIONAL_DESIGN: "functional_design",
        ArtifactType.SOURCE_CODE: "source_code",
        ArtifactType.UNIT_TESTS: "unit_tests",
        ArtifactType.TEST_PLAN: "test_plan",
        ArtifactType.TEST_CASES: "test_cases",
        ArtifactType.AUTOMATED_TESTS: "automated_tests",
        ArtifactType.REVIEW_FEEDBACK: "review_feedback",
        ArtifactType.BUG_REPORT: "bug_report",
    }
    for artifact_type, alias in latest_by_type.items():
        artifact = context.artifact_store.get_latest(artifact_type)
        if artifact is not None:
            defaults.setdefault(alias, artifact.content)

    return defaults


def _build_task_prompt(
    *,
    agent_name: str,
    phase: str,
    project: str,
    raw_requirements: str,
    available_skills: list[str],
    ordered_skills: list[str],
    defaults: dict[str, Any],
) -> str:
    ordered_lines = []
    for idx, skill in enumerate(ordered_skills, start=1):
        hints = ", ".join(SKILL_INPUT_HINTS.get(skill, [])) or "根据上下文自行构造"
        ordered_lines.append(f"{idx}. {skill} (input_data 推荐字段: {hints})")
    ordered_block = "\n".join(ordered_lines)
    default_keys = ", ".join(sorted(defaults.keys()))

    return (
        f"Project: {project}\n"
        f"Current phase: {phase}\n"
        f"Agent: {agent_name}\n"
        f"Requirements summary: {raw_requirements}\n\n"
        f"Available skills: {available_skills}\n"
        f"Recommended execution order (from original agent workflow):\n{ordered_block}\n\n"
        f"Workflow context default keys (auto-merged into input_data): {default_keys}\n\n"
        "Execution rules:\n"
        "1. 必须通过工具调用完成工作，不要只输出分析文本。\n"
        "2. 优先按推荐顺序调用与当前 phase 强相关的 skills。\n"
        '3. 每次调用传入 JSON 参数: {"input_data": {...}, "project_name": "..."}。\n'
        "4. 如果某个 skill 缺失关键字段，先利用已有上下文构造最小可执行输入。\n"
        "5. 完成后给出简洁总结，包含已调用 skills 与产物要点。"
    )


def _to_ai_message(result: Any, agent_name: str, phase: str) -> AIMessage:
    if isinstance(result, dict):
        result_messages = result.get("messages", [])
        if result_messages:
            last = result_messages[-1]
            if isinstance(last, AIMessage):
                return last
            if hasattr(last, "content"):
                return AIMessage(content=str(last.content))
    text = extract_text_from_runtime_result(result)
    if text:
        return AIMessage(content=text)
    return AIMessage(content=f"{agent_name} completed work for phase '{phase}'.")


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
