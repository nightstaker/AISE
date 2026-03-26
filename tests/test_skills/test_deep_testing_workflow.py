"""Tests for deep testing workflow skill."""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.aise.core.artifact import ArtifactType
from src.aise.core.skill import SkillContext
from src.aise.skills.deep_testing_workflow.scripts.deep_testing_workflow import (
    DeepTestingWorkflowSkill,
)


class TestDeepTestingWorkflowSkill:
    """Tests for DeepTestingWorkflowSkill."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.skill = DeepTestingWorkflowSkill()
        self.temp_dir = tempfile.mkdtemp()
        self.tests_dir = Path(self.temp_dir) / "tests"
        self.tests_dir.mkdir()

    def test_skill_name_and_description(self) -> None:
        """Test skill metadata."""
        assert self.skill.name == "deep_testing_workflow"
        assert "test" in self.skill.description.lower()

    def test_validate_input_missing_project_name(self) -> None:
        """Test validation when project name is missing."""
        errors = self.skill.validate_input({})
        assert any("project_name" in e.lower() for e in errors)

    def test_validate_input_valid(self) -> None:
        """Test validation with valid input."""
        errors = self.skill.validate_input(
            {
                "project_name": "TestProject",
            }
        )
        assert len(errors) == 0

    @patch(
        "src.aise.skills.deep_testing_workflow.scripts.deep_testing_workflow.DeepTestingWorkflowSkill._load_architecture_design"
    )
    @patch(
        "src.aise.skills.deep_testing_workflow.scripts.deep_testing_workflow.DeepTestingWorkflowSkill._load_user_stories"
    )
    def test_execute_basic_workflow(
        self,
        mock_load_stories: MagicMock,
        mock_load_arch: MagicMock,
    ) -> None:
        """Test basic execution of the deep testing workflow."""
        # Mock architecture
        mock_load_arch.return_value = {
            "subsystems": [
                {
                    "id": "auth",
                    "name": "Authentication",
                    "english_name": "auth",
                    "description": "Authentication subsystem",
                }
            ],
        }

        # Mock user stories
        mock_load_stories.return_value = [
            {
                "id": "US-001",
                "title": "User login",
                "description": "Allow users to login with username and password",
            }
        ]

        # Create context
        mock_artifact_store = MagicMock()
        mock_artifact_store.get_by_type = MagicMock(return_value=[])

        context = SkillContext(
            artifact_store=mock_artifact_store,
            project_name="TestProject",
            parameters={
                "phase_key": "testing",
                "phase": "testing",
                "workspace_dir": self.temp_dir,
            },
        )

        # Execute
        input_data = {
            "project_name": "TestProject",
            "tests_dir": str(self.tests_dir),
            "coverage_threshold": 50,  # Low threshold for test
        }

        artifact = self.skill.execute(input_data, context)

        # Verify output
        assert artifact.artifact_type == ArtifactType.TEST_PLAN
        assert isinstance(artifact.content, dict)
        assert "test_plan" in artifact.content
        assert "subsystems" in artifact.content["test_plan"]

    def test_parse_test_requirements_from_architecture(self) -> None:
        """Test parsing test requirements from architecture."""
        architecture = {
            "subsystems": [
                {
                    "id": "auth",
                    "name": "Authentication",
                    "description": "Handles user authentication",
                    "components": [
                        {"name": "login", "type": "api"},
                        {"name": "logout", "type": "api"},
                        {"name": "token_validation", "type": "service"},
                    ],
                }
            ],
        }

        requirements = self.skill._parse_test_requirements_from_architecture(architecture)  # type: ignore[attr-defined]

        assert "auth" in requirements
        assert len(requirements["auth"]) > 0

    def test_generate_test_plan(self) -> None:
        """Test generating test plan from requirements."""
        test_requirements = {
            "auth": [
                {"component": "login", "type": "api"},
                {"component": "logout", "type": "api"},
            ]
        }

        test_plan = self.skill._generate_test_plan("auth", test_requirements["auth"])  # type: ignore[attr-defined]

        assert "auth" in test_plan["subsystem_id"]
        assert "test_modules" in test_plan
        assert len(test_plan["test_modules"]) > 0

    def test_design_test_cases(self) -> None:
        """Test designing test cases."""
        test_module = {
            "name": "login",
            "type": "api",
            "description": "User login API",
        }

        test_cases = self.skill._design_test_cases(test_module)  # type: ignore[attr-defined]

        assert len(test_cases) > 0
        # Should include positive, negative, and edge cases
        case_types = [tc.get("type", "") for tc in test_cases]
        assert any("positive" in t.lower() for t in case_types)
        assert any("negative" in t.lower() for t in case_types)

    def test_organize_test_cases_by_priority(self) -> None:
        """Test organizing test cases by priority."""
        test_cases = [
            {"id": "TC-001", "priority": "high", "type": "positive"},
            {"id": "TC-002", "priority": "low", "type": "positive"},
            {"id": "TC-003", "priority": "high", "type": "negative"},
            {"id": "TC-004", "priority": "medium", "type": "edge"},
        ]

        organized = self.skill._organize_test_cases_by_priority(test_cases)  # type: ignore[attr-defined]

        assert "high" in organized
        assert "medium" in organized
        assert "low" in organized
        assert len(organized["high"]) == 2

    def test_generate_python_test_template(self) -> None:
        """Test generating Python test template."""
        test_case = {
            "id": "TC-001",
            "title": "Test valid login",
            "type": "positive",
            "priority": "high",
            "steps": [
                "Send POST /login with valid credentials",
                "Verify 200 OK response",
                "Verify access token in response",
            ],
            "expected_result": "User logged in successfully with valid token",
        }

        template = self.skill._generate_python_test_template(test_case)  # type: ignore[attr-defined]

        assert "def test_" in template
        assert "TC-001" in template
        assert "valid login" in template.lower()

    def test_run_coverage_analysis(self) -> None:
        """Test running coverage analysis."""
        # Create a dummy test file
        test_file = self.tests_dir / "test_dummy.py"
        test_file.write_text("def test_dummy():\n    pass\n")

        coverage_result = self.skill._run_coverage_analysis(str(self.tests_dir))  # type: ignore[attr-defined]

        assert "coverage" in coverage_result
        assert isinstance(coverage_result["coverage"], (int, float))

    def test_identify_coverage_gaps(self) -> None:
        """Test identifying coverage gaps."""
        coverage_report = {
            "files": {
                "auth.py": {"covered_lines": [1, 2, 3], "missing_lines": [4, 5, 6]},
                "user.py": {"covered_lines": [1, 2], "missing_lines": []},
            }
        }

        gaps = self.skill._identify_coverage_gaps(coverage_report)  # type: ignore[attr-defined]

        assert len(gaps) > 0
        assert any("auth.py" in g.get("file", "") for g in gaps)

    def test_generate_improvement_recommendations(self) -> None:
        """Test generating improvement recommendations."""
        coverage_gaps = [
            {
                "file": "auth.py",
                "missing_lines": [4, 5, 6],
            }
        ]

        recommendations = self.skill._generate_improvement_recommendations(coverage_gaps)  # type: ignore[attr-defined]

        assert len(recommendations) > 0
        assert any("auth.py" in r.get("recommendation", "") for r in recommendations)
        assert any("medium" == r.get("priority") for r in recommendations)  # 3 lines is medium (<10)
