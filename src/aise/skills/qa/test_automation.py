"""Test automation skill - implements automated test scripts."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class TestAutomationSkill(Skill):
    """Implement automated test scripts from test case designs."""

    @property
    def name(self) -> str:
        return "test_automation"

    @property
    def description(self) -> str:
        return "Generate automated test scripts from test case designs"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        cases = store.get_content(ArtifactType.TEST_CASES, "test_cases", [])
        testing = store.get_content(ArtifactType.TECH_STACK, "testing", {})
        framework = testing.get("integration", "pytest")

        test_files = {}

        for tc in cases:
            tc_type = tc.get("type", "integration")
            file_key = f"tests/{tc_type}/test_{tc_type}_{tc['id'].lower().replace('-', '_')}.py"

            if tc_type not in test_files:
                test_files[tc_type] = {
                    "path": f"tests/{tc_type}/",
                    "scripts": [],
                }

            script = self._generate_test_script(tc, framework)
            test_files[tc_type]["scripts"].append(
                {
                    "file": file_key,
                    "test_case_id": tc["id"],
                    "content": script,
                }
            )

        # Generate conftest.py
        conftest = self._generate_conftest(framework)

        # Generate pytest configuration
        pytest_ini = (
            "[pytest]\n"
            "testpaths = tests\n"
            "markers =\n"
            "    integration: Integration tests\n"
            "    e2e: End-to-end tests\n"
            "    regression: Regression tests\n"
        )

        return Artifact(
            artifact_type=ArtifactType.AUTOMATED_TESTS,
            content={
                "test_files": test_files,
                "conftest": conftest,
                "pytest_ini": pytest_ini,
                "framework": framework,
                "total_scripts": sum(len(tf["scripts"]) for tf in test_files.values()),
            },
            producer="qa_engineer",
            metadata={"project_name": context.project_name},
        )

    @staticmethod
    def _generate_test_script(test_case: dict, framework: str) -> str:
        """Generate a pytest test script from a test case."""
        tc_id = test_case["id"]
        tc_name = test_case["name"].lower().replace(" ", "_").replace("-", "_").replace("/", "_")
        tc_type = test_case["type"]
        steps = test_case.get("steps", [])
        expected = test_case.get("expected_result", "")

        steps_comments = "\n".join(f"    # Step: {step}" for step in steps)

        # Generate assertion based on expected result
        assertion = '    pytest.fail("Test not yet implemented — expected: ' + expected.replace('"', '\\"') + '")\n'

        return (
            f'"""Automated test for {tc_id}: {test_case["name"]}"""\n\n'
            f"import pytest\n\n\n"
            f"@pytest.mark.{tc_type}\n"
            f"def test_{tc_name}():\n"
            f'    """{test_case["name"]}\n\n'
            f"    Expected: {expected}\n"
            f'    """\n'
            f"{steps_comments}\n"
            f"{assertion}"
        )

    @staticmethod
    def _generate_conftest(framework: str) -> str:
        """Generate a conftest.py with common fixtures."""
        return (
            '"""Common test fixtures and configuration."""\n\n'
            "import os\n\n"
            "import pytest\n\n\n"
            "@pytest.fixture\n"
            "def base_url():\n"
            '    """Base URL for API testing."""\n'
            '    return os.environ.get("TEST_BASE_URL", "http://localhost:8000/api/v1")\n\n\n'
            "@pytest.fixture\n"
            "def auth_headers():\n"
            '    """Authentication headers for API testing.\n\n'
            "    Set the TEST_AUTH_TOKEN environment variable to provide a real token.\n"
            "    Never hardcode credentials in test code.\n"
            '    """\n'
            '    token = os.environ.get("TEST_AUTH_TOKEN", "")\n'
            "    return {\n"
            '        "Authorization": f"Bearer {token}",\n'
            '        "Content-Type": "application/json",\n'
            "    }\n\n\n"
            "@pytest.fixture\n"
            "def test_client():\n"
            '    """HTTP client for API testing."""\n'
            "    # TODO: initialize with app factory\n"
            "    return None\n"
        )
