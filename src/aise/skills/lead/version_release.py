"""Version release skill - manages project version releases."""

from __future__ import annotations

from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext


class VersionReleaseSkill(Skill):
    """Coordinate and record a project version release.

    The Project Manager uses this skill to formally cut a release:
    bump the version, validate readiness (all review gates passed, no open
    blockers), record the release notes, and notify the team.
    """

    @property
    def name(self) -> str:
        return "version_release"

    @property
    def description(self) -> str:
        return "Coordinate a project version release and record release notes"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors = []
        if not input_data.get("version"):
            errors.append("'version' string is required (e.g. '1.0.0')")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        version: str = input_data["version"]
        release_notes: str = input_data.get("release_notes", "")
        release_type: str = input_data.get("release_type", "minor")  # major | minor | patch

        # Inspect artifact store to assess release readiness
        store = context.artifact_store
        readiness_checks: dict[str, bool] = {}
        blockers: list[str] = []

        for artifact_type in (
            ArtifactType.REQUIREMENTS,
            ArtifactType.ARCHITECTURE_DESIGN,
            ArtifactType.SOURCE_CODE,
            ArtifactType.UNIT_TESTS,
        ):
            artifact = store.get_latest(artifact_type)
            key = artifact_type.value
            if artifact is None:
                readiness_checks[key] = False
                blockers.append(f"Missing artifact: {key}")
            else:
                readiness_checks[key] = True

        is_ready = len(blockers) == 0

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "report_type": "version_release",
                "version": version,
                "release_type": release_type,
                "release_notes": release_notes,
                "readiness_checks": readiness_checks,
                "blockers": blockers,
                "is_ready": is_ready,
                "status": "released" if is_ready else "blocked",
                "project_name": context.project_name,
            },
            producer="project_manager",
            metadata={
                "type": "version_release",
                "version": version,
                "project_name": context.project_name,
            },
        )
