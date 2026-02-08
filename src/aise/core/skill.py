"""Base Skill interface for agent capabilities."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .artifact import Artifact, ArtifactStore

if TYPE_CHECKING:
    from ..config import ModelConfig
    from .llm import LLMClient


@dataclass
class SkillContext:
    """Runtime context provided to a skill during execution."""

    artifact_store: ArtifactStore
    project_name: str = ""
    parameters: dict[str, Any] = field(default_factory=dict)
    model_config: ModelConfig | None = None
    llm_client: LLMClient | None = None


class Skill(ABC):
    """Base class for all agent skills.

    A skill is a discrete capability that an agent can execute.
    Skills are stateless: they take input artifacts and context,
    and produce output artifacts.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique skill identifier."""

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description of what this skill does."""

    @property
    def required_artifact_types(self) -> list[str]:
        """Artifact types this skill requires as input. Empty = no input needed."""
        return []

    @abstractmethod
    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        """Execute the skill and produce an artifact.

        Args:
            input_data: Input payload (e.g., raw requirements text, code to review).
            context: Runtime context with access to artifact store, config, and LLM client.

        Returns:
            The produced artifact.
        """

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        """Validate input data. Returns list of error messages (empty = valid)."""
        return []
