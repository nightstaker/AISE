"""Tests for the Architect agent and skills."""

from aise.agents.architect import ArchitectAgent
from aise.agents.product_manager import ProductManagerAgent
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus


class TestArchitectAgent:
    def _setup_with_requirements(self):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)

        pm.execute_skill("requirement_analysis", {"raw_requirements": "User auth\nData export"})
        pm.execute_skill("user_story_writing", {})
        pm.execute_skill("product_design", {})

        return arch, store

    def test_has_all_skills(self):
        bus = MessageBus()
        store = ArtifactStore()
        agent = ArchitectAgent(bus, store)
        expected = {
            "system_design",
            "api_design",
            "architecture_review",
            "tech_stack_selection",
            "pr_review",
        }
        assert set(agent.skill_names) == expected

    def test_system_design(self):
        arch, store = self._setup_with_requirements()
        artifact = arch.execute_skill("system_design", {})
        assert "components" in artifact.content
        assert "data_flows" in artifact.content

    def test_api_design(self):
        arch, store = self._setup_with_requirements()
        arch.execute_skill("system_design", {})
        artifact = arch.execute_skill("api_design", {})
        assert "endpoints" in artifact.content
        assert "schemas" in artifact.content

    def test_tech_stack_selection(self):
        arch, store = self._setup_with_requirements()
        arch.execute_skill("system_design", {})
        artifact = arch.execute_skill("tech_stack_selection", {})
        assert "backend" in artifact.content
        assert "database" in artifact.content

    def test_architecture_review(self):
        arch, store = self._setup_with_requirements()
        arch.execute_skill("system_design", {})
        arch.execute_skill("api_design", {})
        artifact = arch.execute_skill("architecture_review", {})
        assert "approved" in artifact.content
        assert "checks" in artifact.content
