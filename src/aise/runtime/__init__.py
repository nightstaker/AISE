"""Agent runtime built on the deepagents framework.

Provides:
- ``AgentRuntime``: Core runtime that takes an agent.md, skills directory,
  and model to create an operational agent with A2A agent card support.
- ``AgentCard``, ``AgentDefinition``, ``AgentState``: Data models.
- ``parse_agent_md``: Parser for agent.md definitions.
- ``build_agent_card``: A2A agent card builder.
"""

from .agent_card import agent_card_from_dict, agent_card_to_json, build_agent_card
from .agent_md_parser import parse_agent_md
from .agent_runtime import AgentRuntime
from .manager import RuntimeManager
from .models import AgentCard, AgentDefinition, AgentState, ProviderInfo, SkillInfo
from .project_session import ProjectSession
from .skill_loader import load_skills_from_directory

__all__ = [
    "AgentCard",
    "AgentDefinition",
    "AgentRuntime",
    "AgentState",
    "ProjectSession",
    "ProviderInfo",
    "RuntimeManager",
    "SkillInfo",
    "agent_card_from_dict",
    "agent_card_to_json",
    "build_agent_card",
    "load_skills_from_directory",
    "parse_agent_md",
]
