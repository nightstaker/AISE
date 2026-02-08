"""Base Agent class and role definitions."""

from __future__ import annotations

from enum import Enum
from typing import Any

from ..config import ModelConfig
from .artifact import Artifact, ArtifactStore
from .llm import LLMClient
from .message import Message, MessageBus, MessageType
from .skill import Skill, SkillContext


class AgentRole(Enum):
    """Predefined agent roles in the development team."""

    PRODUCT_MANAGER = "product_manager"
    ARCHITECT = "architect"
    DEVELOPER = "developer"
    QA_ENGINEER = "qa_engineer"
    TEAM_LEAD = "team_lead"


class Agent:
    """Base class for all agents in the development team.

    An agent has a role, a set of skills, and communicates with
    other agents via the message bus.
    """

    def __init__(
        self,
        name: str,
        role: AgentRole,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        model_config: ModelConfig | None = None,
    ) -> None:
        self.name = name
        self.role = role
        self.message_bus = message_bus
        self.artifact_store = artifact_store
        self.model_config = model_config or ModelConfig()
        self.llm_client = LLMClient(self.model_config)
        self._skills: dict[str, Skill] = {}

        self.message_bus.subscribe(self.name, self.handle_message)

    def register_skill(self, skill: Skill) -> None:
        """Register a skill with this agent."""
        self._skills[skill.name] = skill

    def get_skill(self, skill_name: str) -> Skill | None:
        """Get a registered skill by name."""
        return self._skills.get(skill_name)

    @property
    def skills(self) -> dict[str, Skill]:
        """All registered skills."""
        return dict(self._skills)

    @property
    def skill_names(self) -> list[str]:
        """Names of all registered skills."""
        return list(self._skills.keys())

    def execute_skill(
        self,
        skill_name: str,
        input_data: dict[str, Any],
        project_name: str = "",
        parameters: dict[str, Any] | None = None,
    ) -> Artifact:
        """Execute a named skill and store the resulting artifact."""
        skill = self._skills.get(skill_name)
        if skill is None:
            raise ValueError(f"Agent '{self.name}' has no skill '{skill_name}'")

        errors = skill.validate_input(input_data)
        if errors:
            raise ValueError(f"Invalid input for skill '{skill_name}': {errors}")

        context = SkillContext(
            artifact_store=self.artifact_store,
            project_name=project_name,
            parameters=parameters or {},
            model_config=self.model_config,
            llm_client=self.llm_client,
        )

        artifact = skill.execute(input_data, context)
        self.artifact_store.store(artifact)
        return artifact

    def handle_message(self, message: Message) -> Message | None:
        """Handle an incoming message. Override in subclasses for custom behavior."""
        if message.msg_type == MessageType.REQUEST:
            skill_name = message.content.get("skill")
            input_data = message.content.get("input_data", {})
            project_name = message.content.get("project_name", "")

            if skill_name and skill_name in self._skills:
                try:
                    artifact = self.execute_skill(skill_name, input_data, project_name)
                    return message.reply(
                        {"status": "success", "artifact_id": artifact.id},
                        MessageType.RESPONSE,
                    )
                except (ValueError, KeyError) as e:
                    return message.reply(
                        {"status": "error", "error": str(e)},
                        MessageType.RESPONSE,
                    )

        return None

    def send_message(
        self,
        receiver: str,
        msg_type: MessageType,
        content: dict[str, Any],
    ) -> list[Any]:
        """Send a message to another agent."""
        message = Message(
            sender=self.name,
            receiver=receiver,
            msg_type=msg_type,
            content=content,
        )
        return self.message_bus.publish(message)

    def request_skill(
        self,
        target_agent: str,
        skill_name: str,
        input_data: dict[str, Any],
        project_name: str = "",
    ) -> list[Any]:
        """Request another agent to execute a skill."""
        return self.send_message(
            receiver=target_agent,
            msg_type=MessageType.REQUEST,
            content={
                "skill": skill_name,
                "input_data": input_data,
                "project_name": project_name,
            },
        )

    def __repr__(self) -> str:
        return (
            f"Agent(name={self.name!r}, role={self.role.value}, "
            f"skills={self.skill_names}, "
            f"model={self.model_config.provider}/{self.model_config.model})"
        )
