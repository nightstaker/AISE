"""Tests for the Product Manager agent and skills."""

from aise.agents.product_manager import ProductManagerAgent
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus


class TestProductManagerAgent:
    def _make_agent(self):
        bus = MessageBus()
        store = ArtifactStore()
        return ProductManagerAgent(bus, store), store

    def test_has_all_skills(self):
        agent, _ = self._make_agent()
        expected = {
            "requirement_analysis",
            "user_story_writing",
            "product_design",
            "product_review",
            "pr_review",
            "pr_merge",
        }
        assert set(agent.skill_names) == expected

    def test_requirement_analysis(self):
        agent, store = self._make_agent()
        artifact = agent.execute_skill(
            "requirement_analysis",
            {
                "raw_requirements": "User login\nUser registration\nPerformance must be under 200ms",
            },
        )
        content = artifact.content
        assert len(content["functional_requirements"]) == 2
        assert len(content["non_functional_requirements"]) == 1

    def test_user_story_writing(self):
        agent, store = self._make_agent()
        # First create requirements
        agent.execute_skill(
            "requirement_analysis",
            {
                "raw_requirements": "User login\nUser registration",
            },
        )
        artifact = agent.execute_skill("user_story_writing", {})
        stories = artifact.content["user_stories"]
        assert len(stories) == 2
        assert all("acceptance_criteria" in s for s in stories)

    def test_product_design(self):
        agent, store = self._make_agent()
        agent.execute_skill("requirement_analysis", {"raw_requirements": "Feature A\nFeature B"})
        agent.execute_skill("user_story_writing", {})
        artifact = agent.execute_skill("product_design", {})
        assert "features" in artifact.content
        assert "user_flows" in artifact.content

    def test_product_review(self):
        agent, store = self._make_agent()
        agent.execute_skill("requirement_analysis", {"raw_requirements": "Feature A"})
        agent.execute_skill("user_story_writing", {})
        agent.execute_skill("product_design", {})
        artifact = agent.execute_skill("product_review", {})
        assert "approved" in artifact.content
        assert "coverage_percentage" in artifact.content
