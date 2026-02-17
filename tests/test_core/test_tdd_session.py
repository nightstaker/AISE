"""Tests for the TDD session skill."""

from unittest.mock import MagicMock, patch

from aise.core.artifact import ArtifactStore, ArtifactType
from aise.core.skill import SkillContext
from aise.skills.developer.tdd_session import TDDSessionSkill


class TestTDDSessionSkill:
    def _make_context(self) -> SkillContext:
        return SkillContext(
            artifact_store=ArtifactStore(),
            project_name="test-project",
        )

    def test_name_and_description(self):
        skill = TDDSessionSkill()
        assert skill.name == "tdd_session"
        assert "TDD" in skill.description

    def test_validate_input_missing_fields(self):
        skill = TDDSessionSkill()
        errors = skill.validate_input({})
        assert len(errors) == 2
        assert any("element_id" in e for e in errors)
        assert any("description" in e for e in errors)

    def test_validate_input_valid(self):
        skill = TDDSessionSkill()
        errors = skill.validate_input({"element_id": "AR-0001", "description": "Auth"})
        assert errors == []

    @patch.object(TDDSessionSkill, "_run_linting")
    @patch.object(TDDSessionSkill, "_run_tests")
    def test_execute_produces_source_code_artifact(self, mock_tests, mock_lint):
        mock_tests.return_value = {"passed": True, "output": "ok", "errors": ""}
        mock_lint.return_value = {"passed": True, "output": "", "errors": ""}

        skill = TDDSessionSkill()
        context = self._make_context()

        artifact = skill.execute(
            {
                "element_id": "AR-0001",
                "description": "Authentication module",
                "working_dir": "/tmp/fake",
            },
            context,
        )

        assert artifact.artifact_type == ArtifactType.SOURCE_CODE
        assert artifact.content["element_id"] == "AR-0001"
        assert artifact.content["all_passed"] is True
        assert artifact.content["tests"]["test_count"] == 2
        assert "test_code" in artifact.content["tests"]
        assert "source_code" in artifact.content["code"]
        assert artifact.metadata["tdd_session"] is True

    @patch.object(TDDSessionSkill, "_run_linting")
    @patch.object(TDDSessionSkill, "_run_tests")
    def test_execute_reports_test_failure(self, mock_tests, mock_lint):
        mock_tests.return_value = {"passed": False, "output": "", "errors": "FAILED"}
        mock_lint.return_value = {"passed": True, "output": "", "errors": ""}

        skill = TDDSessionSkill()
        context = self._make_context()

        artifact = skill.execute(
            {
                "element_id": "AR-0001",
                "description": "Test",
                "working_dir": "/tmp/fake",
            },
            context,
        )

        assert artifact.content["all_passed"] is False
        assert artifact.content["test_run"]["passed"] is False

    @patch.object(TDDSessionSkill, "_run_linting")
    @patch.object(TDDSessionSkill, "_run_tests")
    def test_execute_reports_lint_failure(self, mock_tests, mock_lint):
        mock_tests.return_value = {"passed": True, "output": "ok", "errors": ""}
        mock_lint.return_value = {"passed": False, "output": "E501", "errors": ""}

        skill = TDDSessionSkill()
        context = self._make_context()

        artifact = skill.execute(
            {
                "element_id": "FN-001",
                "element_type": "function",
                "description": "Login function",
                "working_dir": "/tmp/fake",
            },
            context,
        )

        assert artifact.content["all_passed"] is False
        assert artifact.content["lint_run"]["passed"] is False
        assert artifact.content["element_type"] == "function"

    def test_generate_tests_output(self):
        result = TDDSessionSkill._generate_tests("AR-0001", "Auth module", "architecture_requirement", None)
        assert result["test_file"] == "tests/test_ar_0001.py"
        assert result["test_count"] == 2
        assert "AR-0001" in result["test_code"]

    def test_generate_code_output(self):
        result = TDDSessionSkill._generate_code("AR-0001", "Auth module", "architecture_requirement", None)
        assert result["source_file"] == "src/ar_0001.py"
        assert "Auth module" in result["source_code"]

    @patch("aise.skills.developer.tdd_session.subprocess.run")
    def test_run_tests_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="3 passed", stderr="")
        result = TDDSessionSkill._run_tests("/tmp")
        assert result["passed"] is True
        assert "3 passed" in result["output"]

    @patch("aise.skills.developer.tdd_session.subprocess.run")
    def test_run_tests_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="1 failed", stderr="")
        result = TDDSessionSkill._run_tests("/tmp")
        assert result["passed"] is False

    @patch("aise.skills.developer.tdd_session.subprocess.run")
    def test_run_tests_timeout(self, mock_run):
        import subprocess

        mock_run.side_effect = subprocess.TimeoutExpired(cmd="pytest", timeout=300)
        result = TDDSessionSkill._run_tests("/tmp")
        assert result["passed"] is False
        assert "timed out" in result["errors"]

    @patch("aise.skills.developer.tdd_session.subprocess.run")
    def test_run_linting_success(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = TDDSessionSkill._run_linting("/tmp")
        assert result["passed"] is True

    @patch("aise.skills.developer.tdd_session.subprocess.run")
    def test_run_linting_failure(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stdout="E501 line too long", stderr="")
        result = TDDSessionSkill._run_linting("/tmp")
        assert result["passed"] is False
