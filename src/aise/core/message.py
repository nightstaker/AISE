"""Message passing infrastructure for inter-agent communication."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class MessageType(Enum):
    """Types of messages exchanged between agents."""

    REQUEST = "request"
    RESPONSE = "response"
    REVIEW = "review"
    NOTIFICATION = "notification"
    REVISION = "revision"
    USER_INPUT = "user_input"


@dataclass
class Message:
    """A structured message exchanged between agents."""

    sender: str
    receiver: str
    msg_type: MessageType
    content: dict[str, Any]
    correlation_id: str | None = None
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def reply(self, content: dict[str, Any], msg_type: MessageType | None = None) -> Message:
        """Create a reply to this message."""
        return Message(
            sender=self.receiver,
            receiver=self.sender,
            msg_type=msg_type or MessageType.RESPONSE,
            content=content,
            correlation_id=self.id,
        )


class MessageBus:
    """Central message bus for routing messages between agents."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list] = {}
        self._history: list[Message] = []

    def subscribe(self, agent_name: str, handler) -> None:
        """Subscribe an agent to receive messages."""
        self._subscribers.setdefault(agent_name, []).append(handler)

    def unsubscribe(self, agent_name: str) -> None:
        """Remove all subscriptions for an agent."""
        self._subscribers.pop(agent_name, None)

    def publish(self, message: Message) -> list[Any]:
        """Publish a message and return responses from handlers."""
        self._history.append(message)
        results = []
        target = message.receiver

        if target == "broadcast":
            for name, handlers in self._subscribers.items():
                if name != message.sender:
                    for handler in handlers:
                        results.append(handler(message))
        elif target in self._subscribers:
            for handler in self._subscribers[target]:
                results.append(handler(message))

        return results

    def get_history(self, agent_name: str | None = None) -> list[Message]:
        """Get message history, optionally filtered by agent."""
        if agent_name is None:
            return list(self._history)
        return [
            m
            for m in self._history
            if m.sender == agent_name or m.receiver == agent_name
        ]

    def clear_history(self) -> None:
        """Clear all message history."""
        self._history.clear()
