"""Test case design skill - designs detailed test cases."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class TestCaseDesignSkill(Skill):
    """Design detailed test cases (integration, E2E, regression) with expected results."""

    @property
    def name(self) -> str:
        return "test_case_design"

    @property
    def description(self) -> str:
        return "Design detailed integration, E2E, and regression test cases"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        endpoints = store.get_content(ArtifactType.API_CONTRACT, "endpoints", [])
        components = store.get_content(ArtifactType.ARCHITECTURE_DESIGN, "components", [])
        service_components = [c for c in components if c["type"] == "service"]

        test_cases = []

        # API integration test cases
        for ep in endpoints:
            method = ep.get("method", "GET")
            path = ep.get("path", "/unknown")
            resource = path.split("/")[-1].rstrip("s").replace("{id}", "") or "resource"

            # Happy path
            test_cases.append(
                {
                    "id": f"TC-API-{len(test_cases) + 1:03d}",
                    "type": "integration",
                    "name": f"{method} {path} - {resource} success",
                    "preconditions": ["Service is running", "Database is seeded"],
                    "steps": [
                        f"Send {method} request to {path}",
                        "Verify response status code",
                        "Verify response body schema",
                    ],
                    "expected_result": f"Returns "
                    f"{list(ep.get('status_codes', {}).keys())[0] if ep.get('status_codes') else '200'}"
                    f" with valid response",
                    "priority": "high",
                }
            )

            # Error case
            if method in ("POST", "PUT"):
                test_cases.append(
                    {
                        "id": f"TC-API-{len(test_cases) + 1:03d}",
                        "type": "integration",
                        "name": f"{method} {path} - invalid input",
                        "preconditions": ["Service is running"],
                        "steps": [
                            f"Send {method} request with invalid payload",
                            "Verify error response",
                        ],
                        "expected_result": "Returns 400 with error details",
                        "priority": "high",
                    }
                )

            # Auth test
            test_cases.append(
                {
                    "id": f"TC-API-{len(test_cases) + 1:03d}",
                    "type": "integration",
                    "name": f"{method} {path} - unauthorized",
                    "preconditions": ["Service is running", "No auth token"],
                    "steps": [
                        f"Send {method} request without authentication",
                        "Verify 401 response",
                    ],
                    "expected_result": "Returns 401 Unauthorized",
                    "priority": "medium",
                }
            )

        # E2E test cases for complete workflows
        for comp in service_components:
            test_cases.append(
                {
                    "id": f"TC-E2E-{len(test_cases) + 1:03d}",
                    "type": "e2e",
                    "name": f"Complete {comp['name']} CRUD workflow",
                    "preconditions": ["Full system is running"],
                    "steps": [
                        f"Create a new {comp['name']} resource",
                        "Verify it appears in list",
                        "Update the resource",
                        "Verify changes are persisted",
                        "Delete the resource",
                        "Verify it no longer exists",
                    ],
                    "expected_result": "Full CRUD lifecycle completes successfully",
                    "priority": "high",
                }
            )

        # Regression test cases
        test_cases.append(
            {
                "id": f"TC-REG-{len(test_cases) + 1:03d}",
                "type": "regression",
                "name": "Cross-service data consistency",
                "preconditions": ["All services running"],
                "steps": [
                    "Create resources across multiple services",
                    "Verify data consistency between services",
                    "Delete primary resource",
                    "Verify cascading effects",
                ],
                "expected_result": "Data remains consistent across services",
                "priority": "high",
            }
        )

        return Artifact(
            artifact_type=ArtifactType.TEST_CASES,
            content={
                "test_cases": test_cases,
                "total_count": len(test_cases),
                "by_type": {
                    "integration": sum(1 for tc in test_cases if tc["type"] == "integration"),
                    "e2e": sum(1 for tc in test_cases if tc["type"] == "e2e"),
                    "regression": sum(1 for tc in test_cases if tc["type"] == "regression"),
                },
            },
            producer="qa_engineer",
            metadata={"project_name": context.project_name},
        )
