"""Bug fix skill - triages bugs from test failures or error reports."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class BugFixSkill(Skill):
    """Triage and analyze bugs given failing tests or error reports.

    Note: this skill produces root-cause analysis and triage metadata,
    not runnable code patches. Bugs are marked as 'triaged' until an
    LLM-backed code-generation step produces an actual fix.
    """

    @property
    def name(self) -> str:
        return "bug_fix"

    @property
    def description(self) -> str:
        return "Triage bug reports or failing tests and produce analysis"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors = []
        if not input_data.get("bug_reports") and not input_data.get("failing_tests"):
            errors.append("Either 'bug_reports' or 'failing_tests' is required")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        bug_reports = input_data.get("bug_reports", [])
        failing_tests = input_data.get("failing_tests", [])
        code = context.artifact_store.get_latest(ArtifactType.SOURCE_CODE)

        fixes = []

        for bug in bug_reports:
            fix = {
                "bug_id": bug.get("id", "unknown"),
                "description": bug.get("description", ""),
                "root_cause": f"Analysis of: {bug.get('description', 'unknown issue')[:80]}",
                "fix_description": f"Triage analysis for: {bug.get('description', 'unknown')[:60]}",
                "files_changed": [],
                "status": "triaged",
            }

            # Identify affected module from bug description
            if code:
                for module in code.content.get("modules", []):
                    module_name = module["name"]
                    if module_name in bug.get("description", "").lower():
                        fix["files_changed"].append(f"app/{module_name}/service.py")
                        break

            if not fix["files_changed"]:
                fix["files_changed"].append("app/unknown/service.py")
                fix["status"] = "needs_investigation"

            fixes.append(fix)

        for test in failing_tests:
            fix = {
                "test_name": test.get("name", "unknown"),
                "error": test.get("error", ""),
                "root_cause": f"Test failure analysis: {test.get('error', 'unknown')[:80]}",
                "fix_description": f"Triage analysis for failing test: {test.get('name', 'unknown')[:60]}",
                "files_changed": [test.get("file", "unknown")],
                "status": "triaged",
            }
            fixes.append(fix)

        return Artifact(
            artifact_type=ArtifactType.BUG_REPORT,
            content={
                "fixes": fixes,
                "total_bugs": len(bug_reports) + len(failing_tests),
                "triaged_count": sum(1 for f in fixes if f["status"] == "triaged"),
                "needs_investigation": sum(1 for f in fixes if f["status"] == "needs_investigation"),
            },
            producer="developer",
            metadata={"project_name": context.project_name},
        )
