"""Bridge between the internal MessageBus and the WhatsApp group chat.

The bridge performs bidirectional translation:
- Internal agent messages on the MessageBus are forwarded to the WhatsApp group
- Incoming WhatsApp messages from humans are routed to the MessageBus
  (and processed by the appropriate agent)
"""

from __future__ import annotations

import logging
from typing import Any

from ..core.message import Message, MessageBus, MessageType
from .client import WhatsAppClient
from .group import GroupChat, GroupMember, GroupMessage, MemberRole

logger = logging.getLogger(__name__)


# Agent-role-specific prefixes for WhatsApp messages
_ROLE_EMOJI: dict[str, str] = {
    "product_manager": "[PM]",
    "architect": "[Arch]",
    "developer": "[Dev]",
    "qa_engineer": "[QA]",
    "project_manager": "[PM]",
}


class WhatsAppBridge:
    """Bridges the AISE internal MessageBus with a WhatsApp group chat.

    This bridge:
    1. Subscribes to the internal MessageBus to capture agent-to-agent messages
    2. Formats and posts them to the WhatsApp group chat
    3. Listens for incoming WhatsApp messages from human members
    4. Converts human messages into MessageBus events for agent processing
    """

    def __init__(
        self,
        message_bus: MessageBus,
        group_chat: GroupChat,
        whatsapp_client: WhatsAppClient | None = None,
        *,
        forward_all_internal: bool = True,
        human_message_handler: Any = None,
    ) -> None:
        """Initialize the bridge.

        Args:
            message_bus: The internal AISE message bus.
            group_chat: The group chat instance.
            whatsapp_client: Optional WhatsApp API client for sending
                messages to actual WhatsApp. If None, messages are only
                stored in the GroupChat locally (useful for testing or
                CLI-based simulation).
            forward_all_internal: Whether to forward all internal bus
                messages to the group chat.
            human_message_handler: Optional callback for processing
                human messages before routing.
        """
        self.message_bus = message_bus
        self.group_chat = group_chat
        self.whatsapp_client = whatsapp_client
        self.forward_all_internal = forward_all_internal
        self._human_message_handler = human_message_handler
        self._original_publish = message_bus.publish
        self._active = False
        self._human_phone_map: dict[str, str] = {}

    def start(self) -> None:
        """Activate the bridge, connecting MessageBus to WhatsApp group."""
        if self._active:
            return
        self._active = True

        # Intercept MessageBus.publish to also forward to group
        original = self._original_publish

        def intercepted_publish(message: Message) -> list[Any]:
            results = original(message)
            if self.forward_all_internal:
                self._forward_to_group(message)
            return results

        self.message_bus.publish = intercepted_publish  # type: ignore[assignment]

        # Listen for group chat messages from humans
        self.group_chat.on_message(self._handle_group_message)

        # Post startup message
        self.group_chat._post_system_message(
            "WhatsApp bridge activated. All agent communication "
            "will appear here. Human owners can send new requirements."
        )
        logger.info("WhatsApp bridge started")

    def stop(self) -> None:
        """Deactivate the bridge and restore original MessageBus."""
        if not self._active:
            return
        self._active = False
        self.message_bus.publish = self._original_publish  # type: ignore[assignment]
        self.group_chat._post_system_message("WhatsApp bridge deactivated.")
        logger.info("WhatsApp bridge stopped")

    @property
    def is_active(self) -> bool:
        return self._active

    # ------------------------------------------------------------------
    # Internal → WhatsApp
    # ------------------------------------------------------------------

    def _forward_to_group(self, message: Message) -> None:
        """Forward an internal MessageBus message to the WhatsApp group."""
        sender = message.sender
        content = self._format_internal_message(message)
        if not content:
            return

        msg_type = "text"
        metadata: dict[str, Any] = {
            "internal_msg_type": message.msg_type.value,
            "internal_receiver": message.receiver,
            "internal_msg_id": message.id,
        }

        # Post to local group chat
        try:
            self.group_chat.post_message(
                sender=sender,
                content=content,
                message_type=msg_type,
                metadata=metadata,
            )
        except ValueError:
            # Sender not a group member; skip
            logger.debug("Skipping message from non-member: %s", sender)
            return

        # Also send via WhatsApp API if configured
        if self.whatsapp_client and self.whatsapp_client.config.is_configured:
            role_tag = _ROLE_EMOJI.get(sender, "")
            wa_text = f"{role_tag} {sender}:\n{content}" if role_tag else f"{sender}:\n{content}"
            for member in self.group_chat.human_members:
                if member.phone_number:
                    self.whatsapp_client.send_text_message(member.phone_number, wa_text)

    def _format_internal_message(self, message: Message) -> str:
        """Format an internal message for display in the group chat."""
        msg_type = message.msg_type
        content = message.content

        if msg_type == MessageType.REQUEST:
            skill = content.get("skill", "unknown")
            return f"Requesting skill '{skill}' from {message.receiver}"

        if msg_type == MessageType.RESPONSE:
            status = content.get("status", "unknown")
            artifact_id = content.get("artifact_id", "")
            text = f"Completed: {status}"
            if artifact_id:
                text += f" (artifact: {artifact_id})"
            error = content.get("error")
            if error:
                text += f"\nError: {error}"
            return text

        if msg_type == MessageType.REVIEW:
            approved = content.get("approved", False)
            feedback = content.get("feedback", "")
            verdict = "APPROVED" if approved else "NEEDS REVISION"
            text = f"Review: {verdict}"
            if feedback:
                text += f"\n{feedback}"
            return text

        if msg_type == MessageType.NOTIFICATION:
            return content.get("text", str(content))

        if msg_type == MessageType.REVISION:
            return f"Revision submitted: {content.get('description', str(content))}"

        if msg_type == MessageType.USER_INPUT:
            return content.get("text", str(content))

        return str(content)

    # ------------------------------------------------------------------
    # WhatsApp → Internal
    # ------------------------------------------------------------------

    def _handle_group_message(self, message: GroupMessage) -> None:
        """Handle a message posted in the group chat.

        Only processes messages from human members, forwarding them
        as USER_INPUT on the internal MessageBus.
        """
        if not self._active:
            return

        # Ignore messages from agents and system
        member = self.group_chat.get_member(message.sender)
        if member is None or member.is_agent or message.sender == "system":
            return

        # Process human message
        self._route_human_message(message, member)

    def _route_human_message(self, message: GroupMessage, member: GroupMember) -> None:
        """Route a human's group message to the appropriate agent(s).

        Supports command prefixes for directing messages:
        - "@pm ..." → send to product_manager
        - "@dev ..." → send to developer
        - "@arch ..." → send to architect
        - "@qa ..." → send to qa_engineer
        - "@projmgr ..." → send to project_manager
        - No prefix → broadcast as new requirement to all
        """
        text = message.content.strip()
        if not text:
            return

        # Custom handler gets first shot
        if self._human_message_handler:
            handled = self._human_message_handler(message, member)
            if handled:
                return

        # Check for @mention routing
        target, body = self._parse_mention(text)

        if target:
            # Direct message to a specific agent
            bus_message = Message(
                sender="user",
                receiver=target,
                msg_type=MessageType.USER_INPUT,
                content={
                    "text": body,
                    "source": "whatsapp",
                    "sender_name": member.display_name,
                    "sender_phone": member.phone_number,
                },
            )
            self.message_bus.publish(bus_message)
        else:
            # Broadcast as a new requirement
            bus_message = Message(
                sender="user",
                receiver="broadcast",
                msg_type=MessageType.USER_INPUT,
                content={
                    "text": text,
                    "source": "whatsapp",
                    "sender_name": member.display_name,
                    "sender_phone": member.phone_number,
                    "is_requirement": True,
                },
            )
            self.message_bus.publish(bus_message)

    def _parse_mention(self, text: str) -> tuple[str, str]:
        """Parse @mention prefix to route to a specific agent.

        Returns:
            Tuple of (agent_name, remaining_text). agent_name is empty
            if no valid mention was found.
        """
        mention_map = {
            "@pm": "product_manager",
            "@product_manager": "product_manager",
            "@arch": "architect",
            "@architect": "architect",
            "@dev": "developer",
            "@developer": "developer",
            "@qa": "qa_engineer",
            "@qa_engineer": "qa_engineer",
            "@projmgr": "project_manager",
            "@project_manager": "project_manager",
        }

        lower = text.lower()
        for prefix, agent_name in mention_map.items():
            if lower.startswith(prefix + " ") or lower.startswith(prefix + "\n"):
                body = text[len(prefix) :].strip()
                return agent_name, body
            if lower == prefix:
                return agent_name, ""

        return "", text

    # ------------------------------------------------------------------
    # Convenience: register a human phone number
    # ------------------------------------------------------------------

    def register_human(
        self,
        name: str,
        phone_number: str,
        is_owner: bool = True,
    ) -> GroupMember:
        """Register a human participant in the group chat.

        Args:
            name: Display name for the human.
            phone_number: WhatsApp phone number.
            is_owner: Whether this human is a group owner.

        Returns:
            The created GroupMember.
        """
        role = MemberRole.HUMAN_OWNER if is_owner else MemberRole.HUMAN_MEMBER
        member = GroupMember(
            name=name,
            role=role,
            phone_number=phone_number,
        )
        self.group_chat.add_member(member)
        self._human_phone_map[phone_number] = name
        self.group_chat._post_system_message(f"{member.display_name} joined the group")
        return member

    def handle_incoming_whatsapp(self, sender_phone: str, body: str, raw: dict | None = None) -> None:
        """Process an incoming WhatsApp message from a human.

        This is called by the webhook server when a real WhatsApp message
        arrives. It maps the phone number to a group member and posts the
        message to the group chat.

        Args:
            sender_phone: The sender's WhatsApp phone number.
            body: The message body text.
            raw: Optional raw webhook payload for the message.
        """
        member_name = self._human_phone_map.get(sender_phone)
        if member_name is None:
            logger.warning("Message from unregistered phone %s ignored", sender_phone)
            return

        self.group_chat.post_message(
            sender=member_name,
            content=body,
            message_type="requirement" if not body.startswith("@") else "text",
            metadata={"phone": sender_phone, "raw": raw or {}},
        )
