"""Task assignment skill - routes tasks to appropriate agents."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


# Mapping of skills to agent roles
SKILL_TO_AGENT = {
    "requirement_analysis": "product_manager",
    "user_story_writing": "product_manager",
    "product_design": "product_manager",
    "product_review": "product_manager",
    "system_design": "architect",
    "api_design": "architect",
    "architecture_review": "architect",
    "tech_stack_selection": "architect",
    "code_generation": "developer",
    "unit_test_writing": "developer",
    "code_review": "developer",
    "bug_fix": "developer",
    "test_plan_design": "qa_engineer",
    "test_case_design": "qa_engineer",
    "test_automation": "qa_engineer",
    "test_review": "qa_engineer",
}


class TaskAssignmentSkill(Skill):
    """Route tasks to the appropriate agent based on skill requirements."""

    @property
    def name(self) -> str:
        return "task_assignment"

    @property
    def description(self) -> str:
        return "Assign tasks to appropriate agents based on required skills"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        tasks = input_data.get("tasks", [])

        assignments = []
        for task in tasks:
            skill = task.get("skill", "")
            agent = task.get("agent") or SKILL_TO_AGENT.get(skill, "team_lead")

            assignments.append(
                {
                    "task_id": task.get("id", "unknown"),
                    "skill": skill,
                    "assigned_to": agent,
                    "phase": task.get("phase", "unknown"),
                    "description": task.get("description", ""),
                    "dependencies": task.get("dependencies", []),
                    "status": "assigned",
                }
            )

        # Group by agent
        by_agent = {}
        for a in assignments:
            by_agent.setdefault(a["assigned_to"], []).append(a["task_id"])

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "assignments": assignments,
                "by_agent": by_agent,
                "total_assigned": len(assignments),
            },
            producer="team_lead",
            metadata={"type": "task_assignment", "project_name": context.project_name},
        )
