"""Test review skill - reviews test coverage and quality."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactStatus, ArtifactType
from ...core.skill import Skill, SkillContext


class TestReviewSkill(Skill):
    """Review test coverage and quality; identify gaps."""

    @property
    def name(self) -> str:
        return "test_review"

    @property
    def description(self) -> str:
        return "Review test coverage, quality, and identify testing gaps"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        test_plan = context.artifact_store.get_latest(ArtifactType.TEST_PLAN)
        test_cases = context.artifact_store.get_latest(ArtifactType.TEST_CASES)
        automated = context.artifact_store.get_latest(ArtifactType.AUTOMATED_TESTS)
        unit_tests = context.artifact_store.get_latest(ArtifactType.UNIT_TESTS)
        api = context.artifact_store.get_latest(ArtifactType.API_CONTRACT)

        issues = []
        metrics = {}

        # Check test plan coverage
        if test_plan:
            subsystems = test_plan.content.get("subsystem_plans", [])
            metrics["planned_subsystems"] = len(subsystems)
        else:
            issues.append(
                {
                    "type": "missing_artifact",
                    "severity": "high",
                    "description": "No test plan found",
                }
            )

        # Check test case coverage against API endpoints
        if test_cases and api:
            endpoints = api.content.get("endpoints", [])
            cases = test_cases.content.get("test_cases", [])
            tested_paths = set()
            for tc in cases:
                name = tc.get("name", "")
                for ep in endpoints:
                    if ep["path"] in name or ep["method"] in name:
                        tested_paths.add(f"{ep['method']} {ep['path']}")

            total_endpoints = len(endpoints)
            covered = len(tested_paths)
            metrics["endpoint_coverage"] = round(covered / total_endpoints * 100, 1) if total_endpoints > 0 else 0
            metrics["total_endpoints"] = total_endpoints
            metrics["covered_endpoints"] = covered

            if metrics["endpoint_coverage"] < 70:
                issues.append(
                    {
                        "type": "low_coverage",
                        "severity": "medium",
                        "description": f"Endpoint test coverage is {metrics['endpoint_coverage']}% (target: 70%)",
                    }
                )

        # Check automation coverage
        if automated and test_cases:
            total_cases = test_cases.content.get("total_count", 0)
            total_scripts = automated.content.get("total_scripts", 0)
            metrics["automation_rate"] = round(total_scripts / total_cases * 100, 1) if total_cases > 0 else 0
            metrics["total_test_cases"] = total_cases
            metrics["automated_scripts"] = total_scripts

            if metrics["automation_rate"] < 60:
                issues.append(
                    {
                        "type": "low_automation",
                        "severity": "medium",
                        "description": f"Test automation rate is {metrics['automation_rate']}% (target: 60%)",
                    }
                )

        # Check unit test coverage
        if unit_tests:
            metrics["unit_test_count"] = unit_tests.content.get("total_test_cases", 0)
        else:
            issues.append(
                {
                    "type": "missing_artifact",
                    "severity": "high",
                    "description": "No unit tests found",
                }
            )

        # Check for test types balance
        if test_cases:
            by_type = test_cases.content.get("by_type", {})
            if by_type.get("e2e", 0) == 0:
                issues.append(
                    {
                        "type": "missing_test_type",
                        "severity": "medium",
                        "description": "No E2E test cases defined",
                    }
                )
            if by_type.get("regression", 0) == 0:
                issues.append(
                    {
                        "type": "missing_test_type",
                        "severity": "low",
                        "description": "No regression test cases defined",
                    }
                )

        approved = all(i["severity"] not in ("critical", "high") for i in issues) if issues else True

        if automated:
            new_status = ArtifactStatus.APPROVED if approved else ArtifactStatus.REJECTED
            context.artifact_store.update_status(automated.id, new_status)

        return Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content={
                "approved": approved,
                "metrics": metrics,
                "issues": issues,
                "summary": f"Test review: {'Approved' if approved else 'Needs revision'}, {len(issues)} issues found.",
            },
            producer="qa_engineer",
            metadata={"review_target": "testing", "project_name": context.project_name},
        )
