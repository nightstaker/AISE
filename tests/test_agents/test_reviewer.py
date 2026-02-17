"""Tests for the Reviewer agent."""

from aise.agents.reviewer import ReviewerAgent
from aise.core.agent import AgentRole
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus


class TestReviewerAgent:
    def test_has_expected_skills(self):
        bus = MessageBus()
        store = ArtifactStore()
        agent = ReviewerAgent(bus, store)
        expected = {"code_review", "pr_review", "pr_merge"}
        assert set(agent.skill_names) == expected

    def test_role_is_reviewer(self):
        bus = MessageBus()
        store = ArtifactStore()
        agent = ReviewerAgent(bus, store)
        assert agent.role == AgentRole.REVIEWER

    def test_name_is_reviewer(self):
        bus = MessageBus()
        store = ArtifactStore()
        agent = ReviewerAgent(bus, store)
        assert agent.name == "reviewer"
