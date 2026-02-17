"""Progress tracking skill - tracks overall project status."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class ProgressTrackingSkill(Skill):
    """Track overall project status and report progress across all phases."""

    @property
    def name(self) -> str:
        return "progress_tracking"

    @property
    def description(self) -> str:
        return "Track and report project progress across all development phases"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        store = context.artifact_store

        # Collect status of all artifact types
        phase_status = {}

        # Requirements phase
        reqs = store.get_latest(ArtifactType.REQUIREMENTS)
        stories = store.get_latest(ArtifactType.USER_STORIES)
        prd = store.get_latest(ArtifactType.PRD)
        phase_status["requirements"] = {
            "artifacts": {
                "requirements": self._artifact_status(reqs),
                "user_stories": self._artifact_status(stories),
                "prd": self._artifact_status(prd),
            },
            "complete": all(
                self._artifact_status(a) in ("approved", "draft", "revised")
                for a in [reqs, stories, prd]
                if a is not None
            )
            and reqs is not None,
        }

        # Design phase
        arch = store.get_latest(ArtifactType.ARCHITECTURE_DESIGN)
        api = store.get_latest(ArtifactType.API_CONTRACT)
        tech = store.get_latest(ArtifactType.TECH_STACK)
        phase_status["design"] = {
            "artifacts": {
                "architecture": self._artifact_status(arch),
                "api_contract": self._artifact_status(api),
                "tech_stack": self._artifact_status(tech),
            },
            "complete": all(
                self._artifact_status(a) in ("approved", "draft", "revised") for a in [arch, api, tech] if a is not None
            )
            and arch is not None,
        }

        # Implementation phase
        code = store.get_latest(ArtifactType.SOURCE_CODE)
        unit_tests = store.get_latest(ArtifactType.UNIT_TESTS)
        phase_status["implementation"] = {
            "artifacts": {
                "source_code": self._artifact_status(code),
                "unit_tests": self._artifact_status(unit_tests),
            },
            "complete": code is not None and unit_tests is not None,
        }

        # Testing phase
        test_plan = store.get_latest(ArtifactType.TEST_PLAN)
        test_cases = store.get_latest(ArtifactType.TEST_CASES)
        auto_tests = store.get_latest(ArtifactType.AUTOMATED_TESTS)
        phase_status["testing"] = {
            "artifacts": {
                "test_plan": self._artifact_status(test_plan),
                "test_cases": self._artifact_status(test_cases),
                "automated_tests": self._artifact_status(auto_tests),
            },
            "complete": all(a is not None for a in [test_plan, test_cases, auto_tests]),
        }

        # Overall progress
        completed_phases = sum(1 for p in phase_status.values() if p["complete"])
        total_phases = len(phase_status)
        total_artifacts = len(store.all())

        # Review feedback summary
        feedbacks = store.get_by_type(ArtifactType.REVIEW_FEEDBACK)
        review_summary = {
            "total_reviews": len(feedbacks),
            "approved": sum(1 for f in feedbacks if f.content.get("approved")),
            "rejected": sum(1 for f in feedbacks if not f.content.get("approved")),
        }

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "phases": phase_status,
                "completed_phases": completed_phases,
                "total_phases": total_phases,
                "progress_percentage": round(completed_phases / total_phases * 100, 1),
                "total_artifacts": total_artifacts,
                "review_summary": review_summary,
                "project_name": context.project_name,
            },
            producer="project_manager",
            metadata={"type": "progress_report", "project_name": context.project_name},
        )

    @staticmethod
    def _artifact_status(artifact: Artifact | None) -> str:
        if artifact is None:
            return "not_started"
        return artifact.status.value
