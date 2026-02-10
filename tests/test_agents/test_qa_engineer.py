"""Tests for the QA Engineer agent and skills."""

from aise.agents.architect import ArchitectAgent
from aise.agents.developer import DeveloperAgent
from aise.agents.product_manager import ProductManagerAgent
from aise.agents.qa_engineer import QAEngineerAgent
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus


class TestQAEngineerAgent:
    def _setup_with_code(self):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)
        dev = DeveloperAgent(bus, store)
        qa = QAEngineerAgent(bus, store)

        pm.execute_skill("requirement_analysis", {"raw_requirements": "User login\nReports"})
        pm.execute_skill("user_story_writing", {})
        pm.execute_skill("product_design", {})
        arch.execute_skill("system_design", {})
        arch.execute_skill("api_design", {})
        arch.execute_skill("tech_stack_selection", {})
        dev.execute_skill("code_generation", {})
        dev.execute_skill("unit_test_writing", {})

        return qa, store

    def test_has_all_skills(self):
        bus = MessageBus()
        store = ArtifactStore()
        agent = QAEngineerAgent(bus, store)
        expected = {
            "test_plan_design",
            "test_case_design",
            "test_automation",
            "test_review",
            "pr_review",
        }
        assert set(agent.skill_names) == expected

    def test_test_plan_design(self):
        qa, store = self._setup_with_code()
        artifact = qa.execute_skill("test_plan_design", {})
        assert "scope" in artifact.content
        assert "strategy" in artifact.content
        assert "risks" in artifact.content

    def test_test_case_design(self):
        qa, store = self._setup_with_code()
        qa.execute_skill("test_plan_design", {})
        artifact = qa.execute_skill("test_case_design", {})
        assert "test_cases" in artifact.content
        assert artifact.content["total_count"] > 0

    def test_test_automation(self):
        qa, store = self._setup_with_code()
        qa.execute_skill("test_plan_design", {})
        qa.execute_skill("test_case_design", {})
        artifact = qa.execute_skill("test_automation", {})
        assert "test_files" in artifact.content
        assert artifact.content["total_scripts"] > 0

    def test_test_review(self):
        qa, store = self._setup_with_code()
        qa.execute_skill("test_plan_design", {})
        qa.execute_skill("test_case_design", {})
        qa.execute_skill("test_automation", {})
        artifact = qa.execute_skill("test_review", {})
        assert "approved" in artifact.content
        assert "metrics" in artifact.content
