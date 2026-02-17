"""TDD session skill -- write tests first, then code, run tests, lint."""

from __future__ import annotations

import subprocess
from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class TDDSessionSkill(Skill):
    """Execute a TDD development cycle for a single component or AR.

    Steps:
    1. Generate unit tests for the element (test-first)
    2. Generate implementation code
    3. Run tests locally (pytest)
    4. Run linting (ruff check)
    5. Report results

    The skill produces a SOURCE_CODE artifact containing the generated
    tests, code, and verification results.
    """

    @property
    def name(self) -> str:
        return "tdd_session"

    @property
    def description(self) -> str:
        return "Execute a TDD development cycle: tests first, then code, then verify"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors: list[str] = []
        if "element_id" not in input_data:
            errors.append("'element_id' is required")
        if "description" not in input_data:
            errors.append("'description' is required")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        element_id: str = input_data["element_id"]
        element_type: str = input_data.get("element_type", "architecture_requirement")
        description: str = input_data["description"]
        working_dir: str = input_data.get("working_dir", ".")

        # Step 1: Generate tests (TDD - tests first)
        test_result = self._generate_tests(element_id, description, element_type, context)

        # Step 2: Generate implementation code
        code_result = self._generate_code(element_id, description, element_type, context)

        # Step 3: Run tests
        test_run = self._run_tests(working_dir)

        # Step 4: Run linting
        lint_run = self._run_linting(working_dir)

        all_passed = test_run["passed"] and lint_run["passed"]

        return Artifact(
            artifact_type=ArtifactType.SOURCE_CODE,
            content={
                "element_id": element_id,
                "element_type": element_type,
                "description": description,
                "tests": test_result,
                "code": code_result,
                "test_run": test_run,
                "lint_run": lint_run,
                "all_passed": all_passed,
            },
            producer="developer",
            metadata={
                "element_id": element_id,
                "tdd_session": True,
                "project_name": context.project_name,
            },
        )

    @staticmethod
    def _generate_tests(
        element_id: str,
        description: str,
        element_type: str,
        context: SkillContext,
    ) -> dict[str, Any]:
        """Generate test cases for the element.

        Uses the existing unit test artifacts or generates stubs
        based on the element description.
        """
        module_name = element_id.lower().replace("-", "_")
        class_name = module_name.title().replace("_", "")

        test_file = f"tests/test_{module_name}.py"
        test_code = (
            f'"""Tests for {element_id}: {description}."""\n\n'
            f"import pytest\n\n\n"
            f"class Test{class_name}:\n"
            f"    def test_creation(self):\n"
            f'        """Test that {element_id} can be instantiated."""\n'
            f"        assert True  # Placeholder for LLM-generated test\n\n"
            f"    def test_basic_functionality(self):\n"
            f'        """Test basic functionality of {description}."""\n'
            f"        assert True  # Placeholder for LLM-generated test\n"
        )

        return {
            "test_file": test_file,
            "test_code": test_code,
            "test_count": 2,
        }

    @staticmethod
    def _generate_code(
        element_id: str,
        description: str,
        element_type: str,
        context: SkillContext,
    ) -> dict[str, Any]:
        """Generate implementation code for the element."""
        module_name = element_id.lower().replace("-", "_")
        class_name = module_name.title().replace("_", "")

        source_file = f"src/{module_name}.py"
        source_code = (
            f'"""{description}."""\n\n'
            f"from __future__ import annotations\n\n\n"
            f"class {class_name}:\n"
            f'    """{description}."""\n\n'
            f"    def __init__(self) -> None:\n"
            f"        pass\n"
        )

        return {
            "source_file": source_file,
            "source_code": source_code,
        }

    @staticmethod
    def _run_tests(working_dir: str) -> dict[str, Any]:
        """Run pytest in the working directory."""
        try:
            result = subprocess.run(
                ["python3", "-m", "pytest", "--tb=short", "-q"],
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=300,
            )
            return {
                "passed": result.returncode == 0,
                "output": result.stdout,
                "errors": result.stderr,
            }
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return {
                "passed": False,
                "output": "",
                "errors": str(exc),
            }

    @staticmethod
    def _run_linting(working_dir: str) -> dict[str, Any]:
        """Run ruff check in the working directory."""
        try:
            result = subprocess.run(
                ["python3", "-m", "ruff", "check", "."],
                cwd=working_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            return {
                "passed": result.returncode == 0,
                "output": result.stdout,
                "errors": result.stderr,
            }
        except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
            return {
                "passed": False,
                "output": "",
                "errors": str(exc),
            }
