"""WhatsApp group chat model and management.

Manages the group chat state including members (agents and humans),
message history, and group metadata. Acts as the central hub that
all participants interact through.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable


class MemberRole(Enum):
    """Role of a group chat member."""

    AGENT = "agent"
    HUMAN_OWNER = "human_owner"
    HUMAN_MEMBER = "human_member"


@dataclass
class GroupMember:
    """A participant in the group chat."""

    name: str
    role: MemberRole
    phone_number: str = ""
    agent_role: str = ""
    is_active: bool = True

    @property
    def display_name(self) -> str:
        if self.agent_role:
            return f"{self.name} ({self.agent_role.replace('_', ' ').title()})"
        return self.name

    @property
    def is_agent(self) -> bool:
        return self.role == MemberRole.AGENT

    @property
    def is_owner(self) -> bool:
        return self.role == MemberRole.HUMAN_OWNER


@dataclass
class GroupMessage:
    """A message in the group chat."""

    sender: str
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    message_type: str = "text"
    metadata: dict[str, Any] = field(default_factory=dict)
    reply_to: str | None = None

    def __repr__(self) -> str:
        preview = self.content[:60] + "..." if len(self.content) > 60 else self.content
        return f"GroupMessage(sender={self.sender!r}, content={preview!r})"


class GroupChat:
    """Manages a WhatsApp-style group chat for the agent team.

    The group chat serves as a shared communication space where:
    - All agents can post updates, discuss decisions, and collaborate
    - Human owners can observe the conversation and inject new requirements
    - Messages are visible to all members (broadcast by default)
    """

    def __init__(
        self,
        name: str = "AISE Dev Team",
        description: str = "Multi-Agent Software Development Team",
    ) -> None:
        self.name = name
        self.description = description
        self.id = uuid.uuid4().hex[:16]
        self.created_at = datetime.now(timezone.utc)
        self._members: dict[str, GroupMember] = {}
        self._messages: list[GroupMessage] = []
        self._message_handlers: list[Callable[[GroupMessage], None]] = []

    # ------------------------------------------------------------------
    # Member management
    # ------------------------------------------------------------------

    def add_member(self, member: GroupMember) -> None:
        """Add a member to the group."""
        self._members[member.name] = member

    def remove_member(self, name: str) -> GroupMember | None:
        """Remove a member from the group."""
        member = self._members.pop(name, None)
        if member:
            self._post_system_message(f"{member.display_name} left the group")
        return member

    def get_member(self, name: str) -> GroupMember | None:
        return self._members.get(name)

    @property
    def members(self) -> dict[str, GroupMember]:
        return dict(self._members)

    @property
    def agent_members(self) -> list[GroupMember]:
        return [m for m in self._members.values() if m.is_agent]

    @property
    def human_members(self) -> list[GroupMember]:
        return [m for m in self._members.values() if not m.is_agent]

    @property
    def owners(self) -> list[GroupMember]:
        return [m for m in self._members.values() if m.is_owner]

    # ------------------------------------------------------------------
    # Messaging
    # ------------------------------------------------------------------

    def post_message(
        self,
        sender: str,
        content: str,
        message_type: str = "text",
        metadata: dict[str, Any] | None = None,
        reply_to: str | None = None,
    ) -> GroupMessage:
        """Post a message to the group chat.

        Args:
            sender: Name of the sender (agent name or human identifier).
            content: Message body text.
            message_type: Type of message (text, requirement, status, etc.).
            metadata: Additional message metadata.
            reply_to: ID of the message being replied to.

        Returns:
            The created GroupMessage.

        Raises:
            ValueError: If sender is not a group member.
        """
        if sender not in self._members and sender != "system":
            raise ValueError(f"'{sender}' is not a member of this group")

        msg = GroupMessage(
            sender=sender,
            content=content,
            message_type=message_type,
            metadata=metadata or {},
            reply_to=reply_to,
        )
        self._messages.append(msg)

        for handler in self._message_handlers:
            try:
                handler(msg)
            except Exception:
                pass

        return msg

    def get_messages(
        self,
        limit: int | None = None,
        sender: str | None = None,
        message_type: str | None = None,
        since: datetime | None = None,
    ) -> list[GroupMessage]:
        """Retrieve messages with optional filtering.

        Args:
            limit: Maximum number of messages to return (most recent).
            sender: Filter by sender name.
            message_type: Filter by message type.
            since: Only messages after this timestamp.

        Returns:
            List of matching GroupMessage objects.
        """
        result = list(self._messages)

        if sender:
            result = [m for m in result if m.sender == sender]
        if message_type:
            result = [m for m in result if m.message_type == message_type]
        if since:
            result = [m for m in result if m.timestamp >= since]
        if limit:
            result = result[-limit:]

        return result

    @property
    def message_count(self) -> int:
        return len(self._messages)

    def on_message(self, handler: Callable[[GroupMessage], None]) -> None:
        """Register a handler called when any message is posted."""
        self._message_handlers.append(handler)

    # ------------------------------------------------------------------
    # Group info
    # ------------------------------------------------------------------

    def get_info(self) -> dict[str, Any]:
        """Get group metadata summary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_at": self.created_at.isoformat(),
            "member_count": len(self._members),
            "agents": [m.display_name for m in self.agent_members],
            "humans": [m.display_name for m in self.human_members],
            "message_count": self.message_count,
        }

    def format_history(self, limit: int = 50) -> str:
        """Format recent message history as readable text.

        Args:
            limit: Maximum number of messages to include.

        Returns:
            Formatted chat history string.
        """
        messages = self.get_messages(limit=limit)
        if not messages:
            return "(No messages yet)"

        lines = []
        for msg in messages:
            ts = msg.timestamp.strftime("%H:%M")
            member = self._members.get(msg.sender)
            display = member.display_name if member else msg.sender
            prefix = f"[{ts}] {display}"
            if msg.message_type == "requirement":
                lines.append(f"{prefix} [NEW REQUIREMENT]: {msg.content}")
            elif msg.message_type == "system":
                lines.append(f"--- {msg.content} ---")
            else:
                lines.append(f"{prefix}: {msg.content}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _post_system_message(self, text: str) -> GroupMessage:
        """Post an internal system message."""
        msg = GroupMessage(
            sender="system",
            content=text,
            message_type="system",
        )
        self._messages.append(msg)
        for handler in self._message_handlers:
            try:
                handler(msg)
            except Exception:
                pass
        return msg
