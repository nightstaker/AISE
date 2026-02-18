"""Project Manager agent - responsible for project execution and team coordination."""

from __future__ import annotations

from typing import Any

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import Message, MessageBus, MessageType
from ..skills import (
    ConflictResolutionSkill,
    PRMergeSkill,
    ProgressTrackingSkill,
    PRReviewSkill,
    TeamHealthSkill,
    VersionReleaseSkill,
)


class ProjectManagerAgent(Agent):
    """Agent responsible for project execution, progress management, version releases,
    team health, and conflict resolution.

    The Project Manager does **not** decompose or assign tasks — that
    responsibility belongs to the workflow engine and the RD Director's
    initial setup. Instead, the PM focuses on keeping the project on track
    throughout its lifecycle.

    HA handling
    -----------
    The PM listens for ``NOTIFICATION`` messages with ``event`` set to
    ``"agent_crashed"`` or ``"agent_stuck"`` and responds by broadcasting a
    recovery directive to the team.  The underlying detection logic lives in
    :class:`~aise.skills.TeamHealthSkill`.
    """

    def __init__(
        self,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        model_config: ModelConfig | None = None,
    ) -> None:
        super().__init__(
            name="project_manager",
            role=AgentRole.PROJECT_MANAGER,
            message_bus=message_bus,
            artifact_store=artifact_store,
            model_config=model_config,
        )
        self.register_skill(ConflictResolutionSkill())
        self.register_skill(ProgressTrackingSkill())
        self.register_skill(VersionReleaseSkill())
        self.register_skill(TeamHealthSkill())
        self.register_skill(PRReviewSkill(agent_role=AgentRole.PROJECT_MANAGER))
        self.register_skill(PRMergeSkill(agent_role=AgentRole.PROJECT_MANAGER))

    # ------------------------------------------------------------------
    # Message handling
    # ------------------------------------------------------------------

    def handle_message(self, message: Message) -> Message | None:
        """Extend the base handler with HA notification support."""
        if message.msg_type == MessageType.NOTIFICATION:
            event = message.content.get("event", "")
            if event in ("agent_crashed", "agent_stuck"):
                return self._handle_ha_event(message)

        return super().handle_message(message)

    def _handle_ha_event(self, message: Message) -> Message:
        """React to an HA event notification from the bus or orchestrator."""
        event = message.content.get("event", "")
        agent_name = message.content.get("agent", "unknown")
        tasks = message.content.get("tasks", [])

        if event == "agent_crashed":
            action = "restart"
            directive = f"Agent '{agent_name}' has crashed. Initiating restart — tasks will be re-queued."
        else:  # agent_stuck
            action = "interrupt_and_reassign"
            directive = (
                f"Agent '{agent_name}' session is deadlocked "
                f"with {len(tasks)} in-progress task(s). "
                "Interrupting session and reassigning tasks."
            )

        # Broadcast the recovery directive so all agents are aware
        self.send_message(
            receiver="broadcast",
            msg_type=MessageType.NOTIFICATION,
            content={
                "event": "ha_recovery",
                "source_event": event,
                "agent": agent_name,
                "action": action,
                "directive": directive,
                "tasks": tasks,
            },
        )

        return message.reply(
            content={
                "status": "acknowledged",
                "action": action,
                "agent": agent_name,
                "directive": directive,
            },
            msg_type=MessageType.RESPONSE,
        )

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def check_agent_health(
        self,
        agent_registry: dict[str, Any],
        message_history: list[dict[str, Any]],
        task_statuses: list[dict[str, Any]] | None = None,
        stuck_threshold_seconds: int = 300,
        project_name: str = "",
    ) -> dict[str, Any]:
        """Run a full team-health + HA check and return the report content.

        Parameters
        ----------
        agent_registry:
            Mapping of agent name → metadata (any dict; keys are used as
            agent identifiers).
        message_history:
            List of message dicts, each containing at minimum ``sender``,
            ``receiver``, and ``timestamp`` fields.
        task_statuses:
            Optional list of task dicts with ``status``, ``assignee``, and
            ``task_id`` fields.
        stuck_threshold_seconds:
            How long an agent may be silent while holding in-progress tasks
            before it is considered stuck.
        project_name:
            Project identifier forwarded to the skill context.
        """
        artifact = self.execute_skill(
            "team_health",
            {
                "agent_registry": agent_registry,
                "message_history": message_history,
                "task_statuses": task_statuses or [],
                "stuck_threshold_seconds": stuck_threshold_seconds,
            },
            project_name=project_name,
        )
        return artifact.content
