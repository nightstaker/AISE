"""Tests for the Developer agent and skills."""

from aise.agents.architect import ArchitectAgent
from aise.agents.developer import DeveloperAgent
from aise.agents.product_manager import ProductManagerAgent
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus


class TestDeveloperAgent:
    def _setup_with_design(self):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)
        dev = DeveloperAgent(bus, store)

        pm.execute_skill("requirement_analysis", {"raw_requirements": "User login\nDashboard"})
        pm.execute_skill("user_story_writing", {})
        pm.execute_skill("product_design", {})
        arch.execute_skill("system_design", {})
        arch.execute_skill("api_design", {})
        arch.execute_skill("tech_stack_selection", {})

        return dev, store

    def test_has_all_skills(self):
        bus = MessageBus()
        store = ArtifactStore()
        agent = DeveloperAgent(bus, store)
        expected = {"code_generation", "unit_test_writing", "code_review", "bug_fix", "pr_review"}
        assert set(agent.skill_names) == expected

    def test_code_generation(self):
        dev, store = self._setup_with_design()
        artifact = dev.execute_skill("code_generation", {})
        assert "modules" in artifact.content
        assert artifact.content["total_files"] > 0

    def test_unit_test_writing(self):
        dev, store = self._setup_with_design()
        dev.execute_skill("code_generation", {})
        artifact = dev.execute_skill("unit_test_writing", {})
        assert "test_suites" in artifact.content
        assert artifact.content["total_test_cases"] > 0

    def test_code_review(self):
        dev, store = self._setup_with_design()
        dev.execute_skill("code_generation", {})
        dev.execute_skill("unit_test_writing", {})
        artifact = dev.execute_skill("code_review", {})
        assert "approved" in artifact.content
        assert "findings" in artifact.content

    def test_bug_fix(self):
        dev, store = self._setup_with_design()
        artifact = dev.execute_skill(
            "bug_fix",
            {
                "bug_reports": [{"id": "BUG-001", "description": "Login fails"}],
            },
        )
        assert artifact.content["total_bugs"] == 1
