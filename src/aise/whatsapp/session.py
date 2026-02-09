"""WhatsApp-based interactive session for the AISE agent team.

Extends the on-demand session concept to work over WhatsApp group chat.
Agents form a group, discuss amongst themselves, and human owners can
send new requirements or commands directly in the group.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from ..core.message import Message, MessageBus, MessageType
from ..core.orchestrator import Orchestrator
from ..core.session import OnDemandSession
from .bridge import WhatsAppBridge
from .client import WhatsAppClient, WhatsAppConfig
from .group import GroupChat, GroupMember, GroupMessage, MemberRole
from .webhook import WebhookServer

logger = logging.getLogger(__name__)


class WhatsAppGroupSession:
    """Interactive session where agents collaborate in a WhatsApp group.

    This session:
    1. Creates a WhatsApp group with all registered agents
    2. Bridges the internal MessageBus so agent chatter appears in the group
    3. Allows human owners to join and send requirements/commands
    4. Routes human messages to the appropriate agents for processing
    5. Optionally runs a webhook server for real WhatsApp integration

    Can also operate in local-only mode (no WhatsApp API) for testing
    and CLI-based simulation.
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        project_name: str = "My Project",
        whatsapp_config: WhatsAppConfig | None = None,
        *,
        output: Callable[[str], None] | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.project_name = project_name
        self._print = output or print
        self._running = False

        # Create the group chat
        self.group_chat = GroupChat(
            name=f"AISE: {project_name}",
            description=f"Development team for {project_name}",
        )

        # Register all agents as group members
        for name, agent in orchestrator.agents.items():
            member = GroupMember(
                name=name,
                role=MemberRole.AGENT,
                agent_role=agent.role.value,
            )
            self.group_chat.add_member(member)

        # Set up WhatsApp client if configured
        self.whatsapp_config = whatsapp_config or WhatsAppConfig()
        self.whatsapp_client: WhatsAppClient | None = None
        if self.whatsapp_config.is_configured:
            self.whatsapp_client = WhatsAppClient(self.whatsapp_config)

        # Create the bridge
        self.bridge = WhatsAppBridge(
            message_bus=orchestrator.message_bus,
            group_chat=self.group_chat,
            whatsapp_client=self.whatsapp_client,
            human_message_handler=self._handle_human_command,
        )

        # Underlying on-demand session for command execution
        self._session = OnDemandSession(
            orchestrator,
            project_name,
            output=self._group_output,
        )

        # Webhook server (optional, for real WhatsApp)
        self._webhook_server: WebhookServer | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        *,
        start_webhook: bool = False,
        input_fn: Callable[[], str] | None = None,
    ) -> None:
        """Start the WhatsApp group session.

        Args:
            start_webhook: Whether to start the HTTP webhook server
                for receiving real WhatsApp messages.
            input_fn: Optional input function for CLI simulation mode.
        """
        self._running = True
        self.bridge.start()

        # Start webhook server if requested and configured
        if start_webhook and self.whatsapp_client:
            self._webhook_server = WebhookServer(
                self.whatsapp_client,
                port=self.whatsapp_config.webhook_port,
                webhook_path=self.whatsapp_config.webhook_path,
                message_callback=self.bridge.handle_incoming_whatsapp,
            )
            self._webhook_server.start()
            self._print(
                f"Webhook server running on port {self.whatsapp_config.webhook_port}"
            )

        # Print group info
        self._print(_WA_BANNER)
        self._print(f"Group: {self.group_chat.name}")
        self._print(f"Project: {self.project_name}")
        self._print(f"Agents in group: {len(self.group_chat.agent_members)}")
        for m in self.group_chat.agent_members:
            self._print(f"  {m.display_name}")
        self._print(f"Humans in group: {len(self.group_chat.human_members)}")
        for m in self.group_chat.human_members:
            self._print(f"  {m.display_name}")
        self._print("\nType messages to send to the group. Commands:")
        self._print("  /join <name> [phone]  - Add yourself to the group")
        self._print("  /invite <name> <phone> - Invite a human member")
        self._print("  /members              - List group members")
        self._print("  /history [N]          - Show last N messages")
        self._print("  /status               - Show project status")
        self._print("  /workflow             - Run full SDLC workflow")
        self._print("  /phase <name>         - Run a specific phase")
        self._print("  @agent <message>      - Direct message an agent")
        self._print("  /quit                 - Exit the session")
        self._print("")

        # Enter the interactive loop
        read_input = input_fn or (lambda: input("You> "))

        while self._running:
            try:
                raw = read_input()
            except (EOFError, KeyboardInterrupt):
                self._print("\nSession ended.")
                break

            self._process_input(raw)

        self.stop()

    def stop(self) -> None:
        """Stop the session and clean up."""
        self._running = False
        self.bridge.stop()
        if self._webhook_server:
            self._webhook_server.stop()
            self._webhook_server = None

    @property
    def is_running(self) -> bool:
        return self._running

    # ------------------------------------------------------------------
    # Human interaction
    # ------------------------------------------------------------------

    def add_human(
        self,
        name: str,
        phone_number: str = "",
        is_owner: bool = True,
    ) -> GroupMember:
        """Add a human participant to the group.

        Args:
            name: Display name.
            phone_number: WhatsApp phone number (optional for CLI mode).
            is_owner: Whether this person is a project owner.

        Returns:
            The created GroupMember.
        """
        return self.bridge.register_human(name, phone_number, is_owner)

    def send_requirement(self, sender: str, requirement: str) -> dict[str, Any]:
        """Send a new requirement from a human to the group.

        The requirement is posted to the group chat and processed
        by the product manager agent.

        Args:
            sender: Name of the human sender.
            requirement: The requirement text.

        Returns:
            Result dict from requirement processing.
        """
        # Post to group chat
        self.group_chat.post_message(
            sender=sender,
            content=requirement,
            message_type="requirement",
        )

        # Process via the on-demand session
        result = self._session.handle_input(f"add {requirement}")

        # Post the result back to the group
        output = result.get("output", "")
        if output:
            self.group_chat.post_message(
                sender="product_manager",
                content=output,
                message_type="text",
                metadata={"processed_requirement": True},
            )

        return result

    # ------------------------------------------------------------------
    # Input processing
    # ------------------------------------------------------------------

    def _process_input(self, raw: str) -> None:
        """Process a line of input from the CLI."""
        stripped = raw.strip()
        if not stripped:
            return

        # Handle slash commands
        if stripped.startswith("/"):
            self._handle_slash_command(stripped)
            return

        # Regular message: find the "current user" or use default
        current_humans = self.group_chat.human_members
        if current_humans:
            sender = current_humans[0].name
        else:
            # Auto-join as "Owner" if no humans yet
            self.add_human("Owner")
            sender = "Owner"

        # Check if it's an @mention (direct to agent)
        if stripped.startswith("@"):
            self.group_chat.post_message(
                sender=sender,
                content=stripped,
                message_type="text",
            )
        else:
            # Treat as a new requirement
            self.send_requirement(sender, stripped)

    def _handle_slash_command(self, command: str) -> None:
        """Handle a /command."""
        parts = command.split(None, 2)
        cmd = parts[0].lower()

        if cmd == "/join":
            name = parts[1] if len(parts) > 1 else "Owner"
            phone = parts[2] if len(parts) > 2 else ""
            member = self.add_human(name, phone, is_owner=True)
            self._print(f"Joined as: {member.display_name}")

        elif cmd == "/invite":
            if len(parts) < 3:
                self._print("Usage: /invite <name> <phone>")
                return
            name, phone = parts[1], parts[2]
            member = self.add_human(name, phone, is_owner=False)
            self._print(f"Invited: {member.display_name}")

        elif cmd == "/members":
            info = self.group_chat.get_info()
            self._print(f"Group: {info['name']}")
            self._print(f"Agents ({len(info['agents'])}):")
            for a in info["agents"]:
                self._print(f"  {a}")
            self._print(f"Humans ({len(info['humans'])}):")
            for h in info["humans"]:
                self._print(f"  {h}")

        elif cmd == "/history":
            limit = 50
            if len(parts) > 1:
                try:
                    limit = int(parts[1])
                except ValueError:
                    pass
            history = self.group_chat.format_history(limit=limit)
            self._print(history)

        elif cmd == "/status":
            result = self._session.handle_input("status")
            output = result.get("output", "")
            if output:
                self._print(output)

        elif cmd == "/workflow":
            self._print("Starting full SDLC workflow...")
            result = self._session.handle_input("workflow")
            output = result.get("output", "")
            if output:
                self._print(output)

        elif cmd == "/phase":
            if len(parts) < 2:
                self._print("Usage: /phase <requirements|design|implementation|testing>")
                return
            phase_name = parts[1]
            result = self._session.handle_input(f"phase {phase_name}")
            output = result.get("output", "")
            if output:
                self._print(output)

        elif cmd == "/quit":
            self._running = False
            self._print("Goodbye!")

        else:
            self._print(f"Unknown command: {cmd}")
            self._print("Available: /join /invite /members /history /status /workflow /phase /quit")

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _handle_human_command(
        self, message: GroupMessage, member: GroupMember
    ) -> bool:
        """Custom handler for human messages in the bridge.

        Returns True if the message was handled as a command,
        False to let the bridge handle it normally.
        """
        text = message.content.strip()

        # If the message is a requirement (no @ prefix), process it
        if not text.startswith("@"):
            result = self._session.handle_input(f"add {text}")
            output = result.get("output", "")
            if output:
                self.group_chat.post_message(
                    sender="product_manager",
                    content=output,
                    message_type="text",
                    metadata={"processed_requirement": True},
                )
            return True

        # Let the bridge handle @mentions normally
        return False

    def _group_output(self, text: str) -> None:
        """Output handler that posts to both console and group chat."""
        self._print(text)


# ------------------------------------------------------------------
# Banner
# ------------------------------------------------------------------

_WA_BANNER = r"""
 ___  ___  ___  ___
|   ||   ||__ ||   |  Multi-Agent Development Team
|___||___| __|||___|  WhatsApp Group Chat Mode
"""
