"""Data models for the agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentState(Enum):
    """Lifecycle states of an agent runtime."""

    CREATED = "created"
    ACTIVE = "active"
    STOPPED = "stopped"


@dataclass
class SkillInfo:
    """Metadata describing a single agent skill."""

    id: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


@dataclass
class ProviderInfo:
    """Organization that provides the agent."""

    organization: str = ""
    url: str = ""


@dataclass
class AgentDefinition:
    """Parsed agent definition from an agent.md file."""

    name: str
    description: str
    version: str = "1.0.0"
    system_prompt: str = ""
    skills: list[SkillInfo] = field(default_factory=list)
    capabilities: dict[str, bool] = field(default_factory=dict)
    provider: ProviderInfo = field(default_factory=ProviderInfo)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentCard:
    """A2A protocol-compliant agent card.

    Follows the Google Agent-to-Agent (A2A) protocol specification
    for agent discovery and capability advertisement.
    """

    name: str
    description: str
    url: str = ""
    version: str = "1.0.0"
    provider: ProviderInfo = field(default_factory=ProviderInfo)
    capabilities: dict[str, bool] = field(
        default_factory=lambda: {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        }
    )
    skills: list[SkillInfo] = field(default_factory=list)
    default_input_modes: list[str] = field(default_factory=lambda: ["text"])
    default_output_modes: list[str] = field(default_factory=lambda: ["text"])

    def to_dict(self) -> dict[str, Any]:
        """Serialize to A2A-compliant JSON-compatible dict."""
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "provider": {
                "organization": self.provider.organization,
                "url": self.provider.url,
            },
            "capabilities": dict(self.capabilities),
            "skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "tags": s.tags,
                    "examples": s.examples,
                }
                for s in self.skills
            ],
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
        }
