"""Project Manager agent - responsible for project execution and team coordination."""

from __future__ import annotations

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import Message, MessageBus, MessageType
from ..skills import (
    ConflictResolutionSkill,
    PRMergeSkill,
    ProgressTrackingSkill,
    PRReviewSkill,
)


class ProjectManagerAgent(Agent):
    """Agent responsible for project execution, progress management, and conflict resolution.

    The Project Manager does **not** decompose or assign tasks — that
    responsibility belongs to the workflow engine and the RD Director's
    initial setup. Instead, the PM focuses on keeping the project on track
    throughout its lifecycle.

    HA handling
    -----------
    The PM listens for ``NOTIFICATION`` messages with ``event`` set to
    ``"agent_crashed"`` or ``"agent_stuck"`` and responds by broadcasting a
    recovery directive to the team.
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

