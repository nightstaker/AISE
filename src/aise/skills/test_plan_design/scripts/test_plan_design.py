"""Test plan design skill - creates system/subsystem test plans."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class TestPlanDesignSkill(Skill):
    """Create system/subsystem test plans with scope, strategy, and risk analysis."""

    @property
    def name(self) -> str:
        return "test_plan_design"

    @property
    def description(self) -> str:
        return "Design comprehensive test plans with scope, strategy, and risk analysis"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store
        components = store.get_content(ArtifactType.ARCHITECTURE_DESIGN, "components", [])
        service_components = [c for c in components if c["type"] == "service"]
        endpoints = store.get_content(ArtifactType.API_CONTRACT, "endpoints", [])

        # Test scope
        scope = {
            "in_scope": [
                "API endpoint functional testing",
                "Service component integration testing",
                "Data flow validation",
                "Error handling and edge cases",
                "Authentication and authorization",
            ],
            "out_of_scope": [
                "Performance/load testing (separate plan)",
                "UI/UX testing (no frontend)",
                "Third-party service testing",
            ],
        }

        # Test strategy per level
        strategy = {
            "unit": {
                "description": "Test individual functions and classes in isolation",
                "coverage_target": "80%",
                "tools": ["pytest", "unittest.mock"],
            },
            "integration": {
                "description": "Test component interactions and API contracts",
                "coverage_target": "70%",
                "tools": ["pytest", "httpx", "testcontainers"],
            },
            "system": {
                "description": "End-to-end testing of complete workflows",
                "coverage_target": "60%",
                "tools": ["pytest", "Playwright"],
            },
        }

        # Risk analysis
        risks = []
        if len(service_components) > 3:
            risks.append(
                {
                    "risk": "Complex inter-service communication",
                    "impact": "high",
                    "mitigation": "Contract testing between services",
                }
            )
        if len(endpoints) > 15:
            risks.append(
                {
                    "risk": "Large API surface area",
                    "impact": "medium",
                    "mitigation": "Prioritize critical path testing",
                }
            )
        risks.append(
            {
                "risk": "Data consistency across services",
                "impact": "high",
                "mitigation": "Transaction boundary testing",
            }
        )

        # Subsystem plans
        subsystem_plans = []
        for comp in service_components:
            subsystem_plans.append(
                {
                    "component": comp["name"],
                    "test_levels": ["unit", "integration"],
                    "priority": "high",
                    "estimated_test_count": 10,
                }
            )

        plan = {
            "project_name": context.project_name,
            "scope": scope,
            "strategy": strategy,
            "risks": risks,
            "subsystem_plans": subsystem_plans,
            "total_components": len(service_components),
            "total_endpoints": len(endpoints),
            "environments": ["test", "staging"],
        }

        return Artifact(
            artifact_type=ArtifactType.TEST_PLAN,
            content=plan,
            producer="qa_engineer",
            metadata={"project_name": context.project_name},
        )
