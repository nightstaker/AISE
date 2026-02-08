"""QA Engineer agent."""

from __future__ import annotations

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import MessageBus
from ..skills.qa import (
    TestAutomationSkill,
    TestCaseDesignSkill,
    TestPlanDesignSkill,
    TestReviewSkill,
)


class QAEngineerAgent(Agent):
    """Agent responsible for test planning, design, and automation."""

    def __init__(
        self,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        model_config: ModelConfig | None = None,
    ) -> None:
        super().__init__(
            name="qa_engineer",
            role=AgentRole.QA_ENGINEER,
            message_bus=message_bus,
            artifact_store=artifact_store,
            model_config=model_config,
        )
        self.register_skill(TestPlanDesignSkill())
        self.register_skill(TestCaseDesignSkill())
        self.register_skill(TestAutomationSkill())
        self.register_skill(TestReviewSkill())
