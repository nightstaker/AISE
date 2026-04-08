"""Generate A2A protocol-compliant agent cards from agent definitions."""

from __future__ import annotations

import json
from typing import Any

from .models import AgentCard, AgentDefinition, ProviderInfo, SkillInfo


def build_agent_card(
    definition: AgentDefinition,
    *,
    url: str = "",
    extra_skills: list[SkillInfo] | None = None,
) -> AgentCard:
    """Build an A2A-compliant agent card from an AgentDefinition.

    Args:
        definition: The parsed agent definition.
        url: The agent's service endpoint URL.
        extra_skills: Additional skills discovered at runtime (e.g. from skill_loader).

    Returns:
        An AgentCard ready for serialization and advertisement.
    """
    all_skills = list(definition.skills)
    if extra_skills:
        existing_ids = {s.id for s in all_skills}
        for skill in extra_skills:
            if skill.id not in existing_ids:
                all_skills.append(skill)

    # Merge default capabilities with definition overrides
    capabilities = {
        "streaming": False,
        "pushNotifications": False,
        "stateTransitionHistory": False,
    }
    capabilities.update(definition.capabilities)

    return AgentCard(
        name=definition.name,
        description=definition.description,
        url=url,
        version=definition.version,
        provider=definition.provider or ProviderInfo(),
        capabilities=capabilities,
        skills=all_skills,
        default_input_modes=["text"],
        default_output_modes=["text"],
    )


def agent_card_to_json(card: AgentCard, *, indent: int = 2) -> str:
    """Serialize an agent card to JSON string.

    Args:
        card: The agent card to serialize.
        indent: JSON indentation level.

    Returns:
        JSON string following the A2A agent card schema.
    """
    return json.dumps(card.to_dict(), indent=indent, ensure_ascii=False)


def agent_card_from_dict(data: dict[str, Any]) -> AgentCard:
    """Deserialize an agent card from a dict (e.g. parsed JSON).

    Args:
        data: Dict following the A2A agent card schema.

    Returns:
        Reconstructed AgentCard instance.
    """
    provider_data = data.get("provider", {})
    provider = ProviderInfo(
        organization=provider_data.get("organization", ""),
        url=provider_data.get("url", ""),
    )

    skills = [
        SkillInfo(
            id=s.get("id", ""),
            name=s.get("name", ""),
            description=s.get("description", ""),
            tags=s.get("tags", []),
            examples=s.get("examples", []),
        )
        for s in data.get("skills", [])
    ]

    return AgentCard(
        name=data.get("name", ""),
        description=data.get("description", ""),
        url=data.get("url", ""),
        version=data.get("version", "1.0.0"),
        provider=provider,
        capabilities=data.get("capabilities", {}),
        skills=skills,
        default_input_modes=data.get("defaultInputModes", ["text"]),
        default_output_modes=data.get("defaultOutputModes", ["text"]),
    )
