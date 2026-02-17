"""RD Director agent - establishes the project team and distributes initial requirements."""

from __future__ import annotations

from typing import Any

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import MessageBus, MessageType
from ..skills.manager import RequirementDistributionSkill, TeamFormationSkill


class RDDirectorAgent(Agent):
    """The RD Director is responsible for forming the project team and seeding requirements.

    Responsibilities:
    1. **Team formation** – Define which roles exist, how many agent instances
       each role has, what LLM model backs each role, and whether development
       happens locally or via GitHub.
    2. **Requirement distribution** – Formally hand off the original project
       requirements (product requirements and architecture requirements) to
       the team so every agent starts from an authoritative source.
    """

    def __init__(
        self,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        model_config: ModelConfig | None = None,
    ) -> None:
        super().__init__(
            name="rd_director",
            role=AgentRole.RD_DIRECTOR,
            message_bus=message_bus,
            artifact_store=artifact_store,
            model_config=model_config,
        )
        self.register_skill(TeamFormationSkill())
        self.register_skill(RequirementDistributionSkill())

    # ------------------------------------------------------------------
    # Convenience API
    # ------------------------------------------------------------------

    def form_team(
        self,
        roles: dict[str, dict[str, Any]],
        development_mode: str = "local",
        project_name: str = "",
    ) -> dict[str, Any]:
        """Configure and record the project team composition.

        Args:
            roles: Mapping of role name to config dict with optional keys:
                   ``count`` (int, default 1), ``model`` (str), ``provider`` (str),
                   ``enabled`` (bool, default True).
            development_mode: ``"local"`` or ``"github"``.
            project_name: Current project name.

        Returns:
            Team formation report content dict.
        """
        artifact = self.execute_skill(
            "team_formation",
            {
                "roles": roles,
                "development_mode": development_mode,
                "project_name": project_name,
            },
            project_name,
        )
        report = artifact.content

        # Notify the team about the new composition
        self.send_message(
            receiver="broadcast",
            msg_type=MessageType.NOTIFICATION,
            content={
                "text": (
                    f"RD Director formed the project team: "
                    f"{report['total_roles']} role(s), "
                    f"{report['total_agents']} agent(s), "
                    f"mode={development_mode}"
                ),
                "team_roster": report.get("team_roster", []),
                "development_mode": development_mode,
            },
        )

        return report

    def distribute_requirements(
        self,
        product_requirements: str | list[str],
        architecture_requirements: str | list[str] = "",
        project_name: str = "",
        recipients: list[str] | None = None,
    ) -> dict[str, Any]:
        """Hand off the original project requirements to the team.

        Args:
            product_requirements: Raw product / feature requirements.
            architecture_requirements: Raw architecture / technical constraints.
            project_name: Current project name.
            recipients: Agent names that should receive the requirements.
                        Defaults to the core delivery team.

        Returns:
            Requirement distribution record content dict.
        """
        input_data: dict[str, Any] = {
            "product_requirements": product_requirements,
            "architecture_requirements": architecture_requirements,
            "project_name": project_name,
        }
        if recipients is not None:
            input_data["recipients"] = recipients

        artifact = self.execute_skill("requirement_distribution", input_data, project_name)
        record = artifact.content["distribution"]

        # Notify the team that requirements are available
        self.send_message(
            receiver="broadcast",
            msg_type=MessageType.NOTIFICATION,
            content={
                "text": (
                    f"RD Director distributed requirements for '{project_name}': "
                    f"{record['product_requirement_count']} product requirement(s), "
                    f"{record['architecture_requirement_count']} architecture requirement(s)"
                ),
                "distribution": record,
            },
        )

        return record
