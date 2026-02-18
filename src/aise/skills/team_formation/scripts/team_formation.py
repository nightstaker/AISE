"""Team formation skill - establishes project team configuration."""

from __future__ import annotations

from typing import Any

from ....core.artifact import Artifact, ArtifactType
from ....core.skill import Skill, SkillContext


class TeamFormationSkill(Skill):
    """Configure the project team: roles, agent counts, model assignments, and development mode.

    The RD Director uses this skill to formally establish the team composition
    before the project begins. The output captures which roles are active,
    how many agent instances each role has, and what LLM model each role uses.
    """

    @property
    def name(self) -> str:
        return "team_formation"

    @property
    def description(self) -> str:
        return "Establish project team with roles, agent counts, model assignments, and development mode"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        errors = []
        if not input_data.get("roles"):
            errors.append("'roles' dict is required (maps role name to config)")
        dev_mode = input_data.get("development_mode", "local")
        if dev_mode not in ("local", "github"):
            errors.append("'development_mode' must be 'local' or 'github'")
        return errors

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        roles: dict[str, Any] = input_data.get("roles", {})
        development_mode: str = input_data.get("development_mode", "local")
        project_name: str = input_data.get("project_name", context.project_name)

        team_roster: list[dict[str, Any]] = []
        total_agents = 0

        for role_name, role_config in roles.items():
            count = role_config.get("count", 1)
            model = role_config.get("model", context.model_config.model)
            provider = role_config.get("provider", context.model_config.provider)
            enabled = role_config.get("enabled", True)

            if not enabled:
                continue

            team_roster.append(
                {
                    "role": role_name,
                    "count": count,
                    "model": model,
                    "provider": provider,
                    "agent_names": ([role_name] if count == 1 else [f"{role_name}_{i}" for i in range(1, count + 1)]),
                }
            )
            total_agents += count

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "report_type": "team_formation",
                "project_name": project_name,
                "development_mode": development_mode,
                "team_roster": team_roster,
                "total_roles": len(team_roster),
                "total_agents": total_agents,
            },
            producer="rd_director",
            metadata={
                "type": "team_formation",
                "project_name": project_name,
                "development_mode": development_mode,
            },
        )
