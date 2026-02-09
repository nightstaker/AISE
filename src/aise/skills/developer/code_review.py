"""Code review skill - reviews code for quality and correctness."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactStatus, ArtifactType
from ...core.skill import Skill, SkillContext


class CodeReviewSkill(Skill):
    """Review code for correctness, style, security, and performance."""

    @property
    def name(self) -> str:
        return "code_review"

    @property
    def description(self) -> str:
        return "Review source code for correctness, style, security, and performance issues"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        code = context.artifact_store.get_latest(ArtifactType.SOURCE_CODE)
        tests = context.artifact_store.get_latest(ArtifactType.UNIT_TESTS)

        findings = []
        categories = {"correctness": [], "style": [], "security": [], "performance": []}

        if code:
            modules = code.content.get("modules", [])

            for module in modules:
                for file_info in module.get("files", []):
                    content = file_info.get("content", "")

                    # Security checks
                    if "eval(" in content or "exec(" in content:
                        categories["security"].append(
                            {
                                "file": file_info["path"],
                                "issue": "Use of eval/exec detected - potential code injection",
                                "severity": "critical",
                            }
                        )

                    if (
                        "password" in content.lower()
                        and "hardcoded" not in content.lower()
                    ):
                        categories["security"].append(
                            {
                                "file": file_info["path"],
                                "issue": "Potential hardcoded credential",
                                "severity": "high",
                            }
                        )

                    # Style checks
                    lines = content.split("\n")
                    for i, line in enumerate(lines, 1):
                        if len(line) > 120:
                            categories["style"].append(
                                {
                                    "file": file_info["path"],
                                    "line": i,
                                    "issue": "Line exceeds 120 characters",
                                    "severity": "low",
                                }
                            )

                    # Correctness: check for empty except blocks
                    if "except:" in content and "pass" in content:
                        categories["correctness"].append(
                            {
                                "file": file_info["path"],
                                "issue": "Bare except with pass - errors may be silently swallowed",
                                "severity": "medium",
                            }
                        )

            # Check test coverage
            if tests:
                test_suites = tests.content.get("test_suites", [])
                tested_modules = {s["module"] for s in test_suites}
                for module in modules:
                    if module["name"] != "app" and module["name"] not in tested_modules:
                        categories["correctness"].append(
                            {
                                "file": f"app/{module['name']}/",
                                "issue": f"Module '{module['name']}' has no unit tests",
                                "severity": "high",
                            }
                        )

        for category, items in categories.items():
            for item in items:
                item["category"] = category
                findings.append(item)

        critical_or_high = [
            f for f in findings if f["severity"] in ("critical", "high")
        ]
        approved = len(critical_or_high) == 0

        if code:
            code.status = (
                ArtifactStatus.APPROVED if approved else ArtifactStatus.REJECTED
            )

        return Artifact(
            artifact_type=ArtifactType.REVIEW_FEEDBACK,
            content={
                "approved": approved,
                "total_findings": len(findings),
                "findings_by_category": {k: len(v) for k, v in categories.items()},
                "findings": findings,
                "summary": f"Code review: {'Approved' if approved else 'Needs revision'}, "
                f"{len(findings)} findings ({len(critical_or_high)} critical/high).",
            },
            producer="developer",
            metadata={
                "review_target": "source_code",
                "project_name": context.project_name,
            },
        )
