"""Unit test writing skill - generates test cases for source code."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class UnitTestWritingSkill(Skill):
    """Generate unit tests with edge-case coverage for implemented code."""

    @property
    def name(self) -> str:
        return "unit_test_writing"

    @property
    def description(self) -> str:
        return "Generate unit tests for source code modules with edge-case coverage"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        modules = store.get_content(ArtifactType.SOURCE_CODE, "modules", [])
        language = store.get_content(ArtifactType.SOURCE_CODE, "language", "Python")

        test_suites = []

        for module in modules:
            if module["name"] == "app":
                continue

            test_suite = {
                "module": module["name"],
                "test_file": f"tests/test_{module['name']}.py",
                "test_cases": self._generate_test_cases(module, language),
            }
            test_suites.append(test_suite)

        return Artifact(
            artifact_type=ArtifactType.UNIT_TESTS,
            content={
                "test_suites": test_suites,
                "language": language,
                "framework": "pytest",
                "total_test_cases": sum(len(s["test_cases"]) for s in test_suites),
            },
            producer="developer",
            metadata={"project_name": context.project_name},
        )

    def _generate_test_cases(self, module: dict, language: str) -> list[dict]:
        """Generate test cases for a module."""
        module_name = module["name"]
        class_name = module_name.title().replace("_", "")
        tests = [
            {
                "name": f"test_{module_name}_get_returns_list",
                "description": f"Test that GET {module_name} returns a list",
                "type": "positive",
                "code": (
                    f"def test_{module_name}_get_returns_list():\n"
                    f"    service = {class_name}Service()\n"
                    f"    result = service.get()\n"
                    f"    assert isinstance(result, list)\n"
                ),
            },
            {
                "name": f"test_{module_name}_post_returns_dict",
                "description": f"Test that POST {module_name} returns a dict",
                "type": "positive",
                "code": (
                    f"def test_{module_name}_post_returns_dict():\n"
                    f"    service = {class_name}Service()\n"
                    f"    result = service.post()\n"
                    f"    assert isinstance(result, dict)\n"
                ),
            },
            {
                "name": f"test_{module_name}_delete_returns_none",
                "description": f"Test that DELETE {module_name} returns None",
                "type": "positive",
                "code": (
                    f"def test_{module_name}_delete_returns_none():\n"
                    f"    service = {class_name}Service()\n"
                    f"    result = service.delete()\n"
                    f"    assert result is None\n"
                ),
            },
            {
                "name": f"test_{module_name}_model_has_id",
                "description": f"Test that {module_name} model has id field",
                "type": "unit",
                "code": (
                    f"def test_{module_name}_model_has_id():\n"
                    f"    model = {class_name}()\n"
                    f"    assert hasattr(model, 'id')\n"
                ),
            },
        ]
        return tests
