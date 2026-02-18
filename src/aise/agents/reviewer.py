"""Reviewer agent for GitHub PR review and merge."""

from __future__ import annotations

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import MessageBus
from ..skills import CodeReviewSkill, PRMergeSkill, PRReviewSkill


class ReviewerAgent(Agent):
    """Agent responsible for reviewing PRs, posting feedback, and merging.

    This agent is used exclusively in GitHub development mode.  It
    reviews code changes submitted by developer sessions and merges
    pull requests once CI passes and all comments are resolved.
    """

    def __init__(
        self,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        model_config: ModelConfig | None = None,
    ) -> None:
        super().__init__(
            name="reviewer",
            role=AgentRole.REVIEWER,
            message_bus=message_bus,
            artifact_store=artifact_store,
            model_config=model_config,
        )
        self.register_skill(CodeReviewSkill())
        self.register_skill(PRReviewSkill(agent_role=AgentRole.REVIEWER))
        self.register_skill(PRMergeSkill(agent_role=AgentRole.REVIEWER))
