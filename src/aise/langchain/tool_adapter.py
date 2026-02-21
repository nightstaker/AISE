"""Adapts AISE Skills to LangChain StructuredTools for use by agent nodes."""

from __future__ import annotations

import json
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from ..core.skill import Skill, SkillContext
from ..utils.logging import get_logger

logger = get_logger(__name__)


class SkillInputSchema(BaseModel):
    """Generic input schema for AISE skill tools.

    All skill tools accept a free-form ``input_data`` dictionary so that
    each skill can declare its own expected keys without requiring a
    separate Pydantic model per skill.
    """

    input_data: dict[str, Any] = Field(
        default_factory=dict,
        description="Key/value input payload for the skill (e.g. {'raw_requirements': '...'}).",
    )
    project_name: str = Field(
        default="",
        description="Name of the project being developed.",
    )


def create_skill_tool(
    skill: Skill,
    agent_name: str,
    context: SkillContext,
) -> StructuredTool:
    """Wrap a single AISE :class:`~aise.core.skill.Skill` as a LangChain
    :class:`~langchain_core.tools.StructuredTool`.

    The returned tool can be attached to a LangChain agent so it can
    invoke the skill through the standard ``tool_calls`` interface.

    Args:
        skill: The AISE skill to wrap.
        agent_name: Name of the owning agent (used for tool name namespacing).
        context: Runtime skill context (artifact store, model config, etc.).

    Returns:
        A ``StructuredTool`` with a sanitised name and the skill's description.
    """

    # Capture loop variable for the closure
    _skill = skill
    _context = context
    _agent_name = agent_name

    def execute_skill(
        input_data: dict[str, Any] | None = None,
        project_name: str = "",
    ) -> str:
        """Execute the wrapped AISE skill and return a JSON result string."""
        data = input_data or {}

        # Create a context override with the requested project name
        ctx = SkillContext(
            artifact_store=_context.artifact_store,
            project_name=project_name or _context.project_name,
            parameters=_context.parameters,
            model_config=_context.model_config,
            llm_client=_context.llm_client,
        )

        errors = _skill.validate_input(data)
        if errors:
            return json.dumps({"status": "error", "errors": errors})

        try:
            artifact = _skill.execute(data, ctx)
            # Store in the shared artifact store
            ctx.artifact_store.store(artifact)

            logger.info(
                "Skill tool executed: agent=%s skill=%s artifact_id=%s",
                _agent_name,
                _skill.name,
                artifact.id,
            )
            return json.dumps(
                {
                    "status": "success",
                    "artifact_id": artifact.id,
                    "artifact_type": artifact.artifact_type.value,
                    "content_keys": sorted(artifact.content.keys()),
                }
            )
        except Exception as exc:
            logger.warning(
                "Skill tool failed: agent=%s skill=%s error=%s",
                _agent_name,
                _skill.name,
                exc,
            )
            return json.dumps({"status": "error", "error": str(exc)})

    # Sanitise name: LangChain tool names must be alphanumeric + underscore
    tool_name = f"{_agent_name}__{_skill.name}".replace("-", "_")

    return StructuredTool.from_function(
        func=execute_skill,
        name=tool_name,
        description=f"[{_agent_name}] {_skill.description}",
        args_schema=SkillInputSchema,
    )


def create_agent_tools(
    agent: Any,
    context: SkillContext,
) -> list[StructuredTool]:
    """Create LangChain tools for every skill registered with an AISE agent.

    Args:
        agent: An :class:`~aise.core.agent.Agent` instance.
        context: Shared runtime context injected into each tool.

    Returns:
        List of :class:`~langchain_core.tools.StructuredTool` instances,
        one per registered skill.
    """
    tools = [create_skill_tool(skill, agent.name, context) for skill in agent.skills.values()]
    logger.debug(
        "Agent tools created: agent=%s count=%d names=%s",
        agent.name,
        len(tools),
        [t.name for t in tools],
    )
    return tools
