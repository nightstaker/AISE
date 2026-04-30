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


class TestQAEngineerToolchainCheckPrompt:
    """``qa_engineer.md`` must instruct the QA agent to run a
    toolchain availability check BEFORE executing the test suite, and
    must forbid fabricating pass/fail counts when the runner is
    missing. The 2026-04-29 ``project_0-tower`` re-run shipped a
    Flutter project on a host with no ``flutter`` binary; QA wrote
    ``pytest.passed=822`` despite never running anything. Pin the
    prompt language so a future edit can't quietly remove the rule.
    """

    def _md(self) -> str:
        from pathlib import Path

        import aise

        md_path = Path(aise.__file__).resolve().parent / "agents" / "qa_engineer.md"
        return md_path.read_text(encoding="utf-8")

    def test_workflow_step_zero_runs_which(self) -> None:
        body = self._md()
        # The new mandatory step 0 must explicitly mention ``which`` and
        # the ``toolchain_check`` field where its result is recorded.
        assert "Toolchain availability check" in body
        assert "which" in body
        assert "toolchain_check" in body

    def test_forbids_inventing_passed_failed_when_runner_missing(self) -> None:
        body = self._md()
        # The phrase "FORBIDDEN" appears only when the prompt names
        # this exact rule; pin both the gate wording and the
        # cross-reference to the project_0-tower regression.
        assert "FORBIDDEN" in body
        assert "passed" in body and "failed" in body
        assert "project_0-tower" in body

    def test_schema_documents_ran_field(self) -> None:
        body = self._md()
        # ``ran`` must appear inside the ``pytest`` schema block,
        # paired with the requirement to OMIT counts when ran=false.
        assert '"ran":' in body
        assert "OMIT" in body
