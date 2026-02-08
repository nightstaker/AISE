"""Team Lead agent."""

from __future__ import annotations

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import MessageBus
from ..skills.lead import (
    ConflictResolutionSkill,
    ProgressTrackingSkill,
    TaskAssignmentSkill,
    TaskDecompositionSkill,
)


class TeamLeadAgent(Agent):
    """Agent responsible for workflow coordination, task assignment, and progress tracking."""

    def __init__(
        self,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        model_config: ModelConfig | None = None,
    ) -> None:
        super().__init__(
            name="team_lead",
            role=AgentRole.TEAM_LEAD,
            message_bus=message_bus,
            artifact_store=artifact_store,
            model_config=model_config,
        )
        self.register_skill(TaskDecompositionSkill())
        self.register_skill(TaskAssignmentSkill())
        self.register_skill(ConflictResolutionSkill())
        self.register_skill(ProgressTrackingSkill())
