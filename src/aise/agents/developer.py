"""Developer agent."""

from __future__ import annotations

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import MessageBus
from ..skills.developer import (
    BugFixSkill,
    CodeGenerationSkill,
    CodeReviewSkill,
    UnitTestWritingSkill,
)


class DeveloperAgent(Agent):
    """Agent responsible for code implementation, testing, and bug fixing."""

    def __init__(
        self,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        model_config: ModelConfig | None = None,
    ) -> None:
        super().__init__(
            name="developer",
            role=AgentRole.DEVELOPER,
            message_bus=message_bus,
            artifact_store=artifact_store,
            model_config=model_config,
        )
        self.register_skill(CodeGenerationSkill())
        self.register_skill(UnitTestWritingSkill())
        self.register_skill(CodeReviewSkill())
        self.register_skill(BugFixSkill())
