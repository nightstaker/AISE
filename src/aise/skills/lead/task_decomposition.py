"""Task decomposition skill - breaks goals into assignable tasks."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class TaskDecompositionSkill(Skill):
    """Break high-level goals into assignable tasks for agents."""

    @property
    def name(self) -> str:
        return "task_decomposition"

    @property
    def description(self) -> str:
        return "Decompose high-level project goals into agent-assignable tasks"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        if not input_data.get("raw_requirements") and not input_data.get("goals"):
            return ["Either 'raw_requirements' or 'goals' is required"]
        return []

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        goals = input_data.get("goals", [])
        raw = input_data.get("raw_requirements", "")

        if not goals and raw:
            if isinstance(raw, str):
                goals = [line.strip() for line in raw.split("\n") if line.strip()]
            elif isinstance(raw, list):
                goals = raw

        tasks = []
        task_id = 1

        for goal in goals:
            # Phase 1 tasks: Requirements
            tasks.append(
                {
                    "id": f"TASK-{task_id:03d}",
                    "phase": "requirements",
                    "agent": "product_manager",
                    "skill": "requirement_analysis",
                    "description": f"Analyze requirements for: {goal[:60]}",
                    "input": {"raw_requirements": goal},
                    "dependencies": [],
                }
            )
            task_id += 1

        # Phase 1 continuation
        tasks.extend(
            [
                {
                    "id": f"TASK-{task_id}",
                    "phase": "requirements",
                    "agent": "product_manager",
                    "skill": "user_story_writing",
                    "description": "Write user stories",
                    "dependencies": [f"TASK-{i:03d}" for i in range(1, task_id)],
                },
                {
                    "id": f"TASK-{task_id + 1}",
                    "phase": "requirements",
                    "agent": "product_manager",
                    "skill": "product_design",
                    "description": "Create PRD",
                    "dependencies": [f"TASK-{task_id}"],
                },
                {
                    "id": f"TASK-{task_id + 2}",
                    "phase": "requirements",
                    "agent": "product_manager",
                    "skill": "product_review",
                    "description": "Review PRD",
                    "dependencies": [f"TASK-{task_id + 1}"],
                },
            ]
        )
        task_id += 3

        # Phase 2: Design
        design_start = task_id
        tasks.extend(
            [
                {
                    "id": f"TASK-{task_id}",
                    "phase": "design",
                    "agent": "architect",
                    "skill": "system_design",
                    "description": "Design system architecture",
                    "dependencies": [f"TASK-{design_start - 1}"],
                },
                {
                    "id": f"TASK-{task_id + 1}",
                    "phase": "design",
                    "agent": "architect",
                    "skill": "api_design",
                    "description": "Design API contracts",
                    "dependencies": [f"TASK-{task_id}"],
                },
                {
                    "id": f"TASK-{task_id + 2}",
                    "phase": "design",
                    "agent": "architect",
                    "skill": "tech_stack_selection",
                    "description": "Select technology stack",
                    "dependencies": [f"TASK-{task_id}"],
                },
                {
                    "id": f"TASK-{task_id + 3}",
                    "phase": "design",
                    "agent": "architect",
                    "skill": "architecture_review",
                    "description": "Review architecture",
                    "dependencies": [f"TASK-{task_id + 1}", f"TASK-{task_id + 2}"],
                },
            ]
        )
        task_id += 4

        # Phase 3: Implementation
        impl_start = task_id
        tasks.extend(
            [
                {
                    "id": f"TASK-{task_id}",
                    "phase": "implementation",
                    "agent": "developer",
                    "skill": "code_generation",
                    "description": "Generate source code",
                    "dependencies": [f"TASK-{impl_start - 1}"],
                },
                {
                    "id": f"TASK-{task_id + 1}",
                    "phase": "implementation",
                    "agent": "developer",
                    "skill": "unit_test_writing",
                    "description": "Write unit tests",
                    "dependencies": [f"TASK-{task_id}"],
                },
                {
                    "id": f"TASK-{task_id + 2}",
                    "phase": "implementation",
                    "agent": "developer",
                    "skill": "code_review",
                    "description": "Review code",
                    "dependencies": [f"TASK-{task_id + 1}"],
                },
            ]
        )
        task_id += 3

        # Phase 4: Testing
        tasks.extend(
            [
                {
                    "id": f"TASK-{task_id}",
                    "phase": "testing",
                    "agent": "qa_engineer",
                    "skill": "test_plan_design",
                    "description": "Design test plan",
                    "dependencies": [f"TASK-{task_id - 1}"],
                },
                {
                    "id": f"TASK-{task_id + 1}",
                    "phase": "testing",
                    "agent": "qa_engineer",
                    "skill": "test_case_design",
                    "description": "Design test cases",
                    "dependencies": [f"TASK-{task_id}"],
                },
                {
                    "id": f"TASK-{task_id + 2}",
                    "phase": "testing",
                    "agent": "qa_engineer",
                    "skill": "test_automation",
                    "description": "Implement automated tests",
                    "dependencies": [f"TASK-{task_id + 1}"],
                },
                {
                    "id": f"TASK-{task_id + 3}",
                    "phase": "testing",
                    "agent": "qa_engineer",
                    "skill": "test_review",
                    "description": "Review test quality",
                    "dependencies": [f"TASK-{task_id + 2}"],
                },
            ]
        )

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "tasks": tasks,
                "total_tasks": len(tasks),
                "phases": ["requirements", "design", "implementation", "testing"],
                "goals": goals,
            },
            producer="team_lead",
            metadata={
                "type": "task_decomposition",
                "project_name": context.project_name,
            },
        )
