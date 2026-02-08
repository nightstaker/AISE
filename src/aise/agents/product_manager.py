"""Product Manager agent."""

from __future__ import annotations

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import MessageBus
from ..skills.pm import (
    ProductDesignSkill,
    ProductReviewSkill,
    RequirementAnalysisSkill,
    UserStoryWritingSkill,
)


class ProductManagerAgent(Agent):
    """Agent responsible for requirements analysis and product design."""

    def __init__(
        self,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        model_config: ModelConfig | None = None,
    ) -> None:
        super().__init__(
            name="product_manager",
            role=AgentRole.PRODUCT_MANAGER,
            message_bus=message_bus,
            artifact_store=artifact_store,
            model_config=model_config,
        )
        self.register_skill(RequirementAnalysisSkill())
        self.register_skill(UserStoryWritingSkill())
        self.register_skill(ProductDesignSkill())
        self.register_skill(ProductReviewSkill())
