"""LangChain ReAct agent nodes that wrap AISE agents for LangGraph integration."""

from __future__ import annotations

import os
from typing import Any, Callable
from urllib.parse import urlparse

from langchain_core.messages import AIMessage, HumanMessage
from langchain_openai import ChatOpenAI

from ..config import ModelConfig
from ..core.artifact import ArtifactStore, ArtifactType
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
        "- Run a deep paired workflow with Product Designer and Product Reviewer subagents\n"
        "- Expand raw requirements with user memory into clarified intent\n"
        "- Produce and review system-design.md with SF list for at least two rounds\n"
        "- Produce and review system-requirements.md with SR list for at least two rounds\n"
        "- Preserve revision history and traceability in generated docs\n\n"
        "Use your available tools to execute each task systematically. "
        "Call every skill that is relevant to the current phase."
    ),
    "architect": (
        "You are an expert Software Architect in an AI software development team.\n\n"
        "Responsibilities:\n"
        "- Run a deep architecture workflow with Architecture Designer / Reviewer / Subsystem Architect subagents\n"
        "- Produce and review system-architecture.md for at least two rounds\n"
        "- Allocate all SR items into subsystems and define API contracts\n"
        "- Generate subsystem detail design docs with SR->FN decomposition for at least two rounds each\n"
        "- Initialize project source tree and subsystem API code skeletons\n\n"
        "Use your available tools to execute each task systematically. "
        "Call every skill that is relevant to the current phase."
    ),
    "developer": (
        "You are an expert Software Developer in an AI software development team.\n\n"
        "Responsibilities:\n"
        "- Run deep implementation workflow with Programmer and Code Reviewer subagents\n"
        "- Split implementation by subsystem and assign multi-instance pairs\n"
        "- Implement each FN with test-first iterations and review-driven refinement\n"
        "- Ensure static checks and unit tests pass before merge-ready output\n"
        "- Preserve revision history in subsystem directories for traceability\n\n"
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
            "deep_product_workflow",
        ]
    },
    "architect": {
        "design": [
            "deep_architecture_workflow",
        ]
    },
    "developer": {
        "implementation": [
            "deep_developer_workflow",
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
    "deep_product_workflow": ["raw_requirements", "user_memory", "output_dir"],
    "system_feature_analysis": ["raw_requirements", "requirements"],
    "system_requirement_analysis": ["system_design"],
    "user_story_writing": ["requirements"],
    "product_design": ["requirements", "user_stories", "review_feedback"],
    "product_review": ["requirements", "prd"],
    "document_generation": ["system_design", "system_requirements", "output_dir"],
    "system_design": ["requirements"],
    "deep_architecture_workflow": ["output_dir", "source_dir", "requirements"],
    "deep_developer_workflow": ["source_dir", "tests_dir"],
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
        phase_playbook_skills = _select_playbook_skills(_agent_name, phase, skill_names)
        defaults = _build_default_input_data(context, state, phase)
        base_parameters = dict(context.parameters) if isinstance(context.parameters, dict) else {}

        context.parameters.clear()
        context.parameters.update(
            {
                **base_parameters,
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

        if phase_playbook_skills:
            try:
                summary, produced_artifact_ids = _execute_playbook_skills(
                    agent=agent,
                    project_name=project,
                    phase=phase,
                    defaults=defaults,
                    base_parameters=base_parameters,
                    skill_names=phase_playbook_skills,
                )
                logger.info(
                    "Agent node completed (direct playbook): agent=%s phase=%s skills=%s",
                    _agent_name,
                    phase,
                    phase_playbook_skills,
                )
                return {
                    "messages": [AIMessage(content=summary)],
                    "phase_results": {
                        **state.get("phase_results", {}),
                        f"{phase}_{_agent_name}": "completed",
                    },
                    "artifact_ids": [*state.get("artifact_ids", []), *produced_artifact_ids],
                    "error": None,
                }
            except Exception as exc:
                logger.warning(
                    "Agent node direct-playbook error: agent=%s phase=%s error=%s",
                    _agent_name,
                    phase,
                    exc,
                )
                return {
                    "messages": [AIMessage(content=f"[{_agent_name}] Error: {exc}")],
                    "error": str(exc),
                }

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
    if agent_name == "product_manager" and phase == "requirements" and selected:
        return selected
    if agent_name == "architect" and phase == "design" and selected:
        return selected
    if agent_name == "developer" and phase == "implementation" and selected:
        return selected
    remainder = [skill for skill in skill_names if skill not in selected]
    return selected + remainder


def _select_playbook_skills(agent_name: str, phase: str, skill_names: list[str]) -> list[str]:
    playbook = PHASE_SKILL_PLAYBOOK.get(agent_name, {})
    preferred = playbook.get(phase, [])
    return [skill for skill in preferred if skill in skill_names]


def _execute_playbook_skills(
    *,
    agent: Any,
    project_name: str,
    phase: str,
    defaults: dict[str, Any],
    base_parameters: dict[str, Any],
    skill_names: list[str],
) -> tuple[str, list[str]]:
    produced_artifact_ids: list[str] = []
    executed: list[str] = []
    recorder = defaults.get("_task_memory_recorder")
    run_id = str(defaults.get("_run_id", ""))
    project_id = str(defaults.get("_project_id", ""))
    for skill_name in skill_names:
        input_data = _build_skill_input(skill_name, defaults)
        task_key = f"{agent.name}.{skill_name}"
        attempt_no = 0
        if hasattr(recorder, "record_task_attempt_start"):
            started = recorder.record_task_attempt_start(
                phase_key=phase,
                task_key=task_key,
                display_name=skill_name,
                kind="initial",
                mode="current",
                executor={
                    "agent": agent.name,
                    "skill": skill_name,
                    "task_key": task_key,
                    "execution_scope": "full_skill",
                },
            )
            attempt = started.get("attempt", {}) if isinstance(started, dict) else {}
            attempt_no = int((attempt or {}).get("attempt_no", 0) or 0)
            if hasattr(recorder, "record_task_attempt_context"):
                recorder.record_task_attempt_context(
                    phase_key=phase,
                    task_key=task_key,
                    attempt_no=attempt_no,
                    context={
                        "input_hints": list(SKILL_INPUT_HINTS.get(skill_name, [])),
                        "input_keys": sorted(input_data.keys()),
                        "notes": [f"run_id:{run_id}"] if run_id else [],
                        "project_id": project_id,
                    },
                )
        try:
            artifact = agent.execute_skill(
                skill_name=skill_name,
                input_data=input_data,
                project_name=project_name,
                parameters={
                    **base_parameters,
                    "phase": phase,
                    "agent_name": agent.name,
                    "project_name": project_name,
                    "input_defaults": defaults,
                    "task_memory_recorder": recorder,
                    "phase_key": phase,
                    "run_id": run_id,
                },
            )
        except Exception as exc:
            if hasattr(recorder, "record_task_attempt_end") and attempt_no:
                recorder.record_task_attempt_end(
                    phase_key=phase,
                    task_key=task_key,
                    attempt_no=attempt_no,
                    status="failed",
                    error=str(exc),
                )
            raise
        produced_artifact_ids.append(artifact.id)
        executed.append(skill_name)
        if hasattr(recorder, "record_task_attempt_output") and attempt_no:
            recorder.record_task_attempt_output(
                phase_key=phase,
                task_key=task_key,
                attempt_no=attempt_no,
                outputs={"artifact_ids": [artifact.id]},
            )
        if hasattr(recorder, "record_task_attempt_end") and attempt_no:
            recorder.record_task_attempt_end(
                phase_key=phase,
                task_key=task_key,
                attempt_no=attempt_no,
                status="completed",
                error="",
            )
    summary = (
        f"{agent.name} completed phase '{phase}' via direct playbook execution. "
        f"skills={executed} artifacts={len(produced_artifact_ids)}"
    )
    return summary, produced_artifact_ids


def _build_skill_input(skill_name: str, defaults: dict[str, Any]) -> dict[str, Any]:
    hints = SKILL_INPUT_HINTS.get(skill_name, [])
    if not hints:
        return dict(defaults)

    payload: dict[str, Any] = {key: defaults[key] for key in hints if key in defaults}
    if "raw_requirements" in defaults:
        payload.setdefault("raw_requirements", defaults["raw_requirements"])
    return payload


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


def build_retry_skill_input(
    *,
    artifact_store: ArtifactStore,
    skill_name: str,
    project_input: dict[str, Any],
    phase: str,
    phase_results: dict[str, Any] | None = None,
    artifact_ids: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build retry input payload and defaults using the same artifact-derived context as agent nodes."""
    context = SkillContext(artifact_store=artifact_store)
    state: AgentWorkflowState = {
        "messages": [],
        "project_name": str(project_input.get("project_name", "")) if isinstance(project_input, dict) else "",
        "project_input": dict(project_input) if isinstance(project_input, dict) else {},
        "current_phase": phase,
        "phase_results": dict(phase_results or {}),
        "artifact_ids": list(artifact_ids or []),
        "next_agent": "",
        "error": None,
        "iteration": 0,
    }
    defaults = _build_default_input_data(context, state, phase)
    payload = _build_skill_input(skill_name, defaults)
    return payload, defaults


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
        "2. 严格按推荐顺序执行，除非上一步成功，否则不要跳到后续 skill。\n"
        '3. 每次调用传入 JSON 参数: {"input_data": {...}, "project_name": "..."}。\n'
        "4. 如果某个 skill 返回依赖不足/缺少产物，先补齐前置 skill，再重试该 skill。\n"
        "5. 如果某个 skill 缺失关键字段，先利用已有上下文构造最小可执行输入。\n"
        "6. 完成后给出简洁总结，包含已调用 skills 与产物要点。"
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
        "timeout": _resolve_timeout_seconds(),
        "max_retries": 1,
    }
    api_key = _resolve_api_key(config)
    if api_key:
        kwargs["api_key"] = api_key
    if config.base_url:
        kwargs["base_url"] = config.base_url

    return ChatOpenAI(**kwargs)


def _resolve_api_key(config: ModelConfig) -> str:
    key = config.api_key or os.environ.get("OPENAI_API_KEY", "")
    if key:
        return key
    provider = (config.provider or "").strip().lower()
    is_local_model = bool(config.extra.get("is_local_model"))
    if provider == "local" or is_local_model or _is_local_base_url(config.base_url):
        return os.environ.get("AISE_LOCAL_OPENAI_API_KEY", "local-no-key-required")
    return ""


def _is_local_base_url(base_url: str) -> bool:
    value = (base_url or "").strip()
    if not value:
        return False
    try:
        parsed = urlparse(value)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


def _resolve_timeout_seconds() -> float:
    raw = os.environ.get("AISE_LLM_TIMEOUT_SECONDS", "").strip()
    if not raw:
        return 45.0
    try:
        value = float(raw)
        return value if value > 0 else 45.0
    except ValueError:
        return 45.0
