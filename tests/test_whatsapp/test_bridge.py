"""Tests for the MessageBus-to-WhatsApp bridge."""

from aise.core.message import Message, MessageBus, MessageType
from aise.whatsapp.bridge import WhatsAppBridge
from aise.whatsapp.group import GroupChat, GroupMember, MemberRole


def _make_group_with_agents() -> tuple[GroupChat, MessageBus]:
    """Helper: create a group with agents and a message bus."""
    bus = MessageBus()
    group = GroupChat(name="Test Group")

    for name, role in [
        ("product_manager", "product_manager"),
        ("architect", "architect"),
        ("developer", "developer"),
    ]:
        group.add_member(GroupMember(name=name, role=MemberRole.AGENT, agent_role=role))

    return group, bus


class TestWhatsAppBridge:
    def test_start_stop(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)

        assert not bridge.is_active
        bridge.start()
        assert bridge.is_active
        bridge.stop()
        assert not bridge.is_active

    def test_forward_internal_messages(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)
        bridge.start()

        # Simulate an internal message
        msg = Message(
            sender="product_manager",
            receiver="developer",
            msg_type=MessageType.REQUEST,
            content={"skill": "code_generation"},
        )
        bus.publish(msg)

        # Should appear in group chat
        messages = group.get_messages(sender="product_manager")
        assert len(messages) >= 1
        assert "code_generation" in messages[-1].content

        bridge.stop()

    def test_forward_notification(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)
        bridge.start()

        msg = Message(
            sender="architect",
            receiver="broadcast",
            msg_type=MessageType.NOTIFICATION,
            content={"text": "Design is ready"},
        )
        bus.publish(msg)

        messages = group.get_messages(sender="architect")
        assert any("Design is ready" in m.content for m in messages)

        bridge.stop()

    def test_forward_response(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)
        bridge.start()

        msg = Message(
            sender="developer",
            receiver="product_manager",
            msg_type=MessageType.RESPONSE,
            content={"status": "success", "artifact_id": "art_123"},
        )
        bus.publish(msg)

        messages = group.get_messages(sender="developer")
        assert any("success" in m.content for m in messages)

        bridge.stop()

    def test_human_message_broadcast(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)

        # Register a human
        bridge.register_human("Alice", "1234567890", is_owner=True)

        bridge.start()

        # Bridge already intercepts publish, so we track history
        group.post_message("Alice", "Add a login page")

        # The human message handler should route it
        # Check that the message appeared in group
        messages = group.get_messages(sender="Alice")
        assert len(messages) >= 1

        bridge.stop()

    def test_register_human(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)

        member = bridge.register_human("Alice", "123", is_owner=True)
        assert member.name == "Alice"
        assert member.is_owner
        assert member.phone_number == "123"
        assert group.get_member("Alice") is not None

    def test_register_non_owner_human(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)

        member = bridge.register_human("Bob", "456", is_owner=False)
        assert not member.is_owner

    def test_parse_mention(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)

        agent, body = bridge._parse_mention("@dev fix the login bug")
        assert agent == "developer"
        assert body == "fix the login bug"

    def test_parse_mention_pm(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)

        agent, body = bridge._parse_mention("@pm add payment feature")
        assert agent == "product_manager"
        assert body == "add payment feature"

    def test_parse_mention_none(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)

        agent, body = bridge._parse_mention("just a normal message")
        assert agent == ""
        assert body == "just a normal message"

    def test_handle_incoming_whatsapp_registered(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)
        bridge.register_human("Alice", "123")

        bridge.handle_incoming_whatsapp("123", "New feature request")
        messages = group.get_messages(sender="Alice")
        assert len(messages) >= 1

    def test_handle_incoming_whatsapp_unregistered(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)

        # Should not raise, just log warning
        bridge.handle_incoming_whatsapp("unknown_phone", "Hello")
        # No message should be added
        assert group.message_count == 0

    def test_forward_review_message(self):
        group, bus = _make_group_with_agents()
        bridge = WhatsAppBridge(bus, group)
        bridge.start()

        msg = Message(
            sender="architect",
            receiver="product_manager",
            msg_type=MessageType.REVIEW,
            content={"approved": True, "feedback": "Looks good"},
        )
        bus.publish(msg)

        messages = group.get_messages(sender="architect")
        assert any("APPROVED" in m.content for m in messages)

        bridge.stop()

    def test_no_forward_when_inactive(self):
        group, bus = _make_group_with_agents()
        WhatsAppBridge(bus, group, forward_all_internal=True)
        # Don't start bridge

        initial_count = group.message_count
        msg = Message(
            sender="developer",
            receiver="architect",
            msg_type=MessageType.REQUEST,
            content={"skill": "architecture_review"},
        )
        bus.publish(msg)

        # Messages should not be forwarded since bridge is not active
        assert group.message_count == initial_count
