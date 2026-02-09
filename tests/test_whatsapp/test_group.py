"""Tests for the WhatsApp group chat model."""

import pytest
from aise.whatsapp.group import GroupChat, GroupMember, GroupMessage, MemberRole


class TestGroupMember:
    def test_agent_member(self):
        m = GroupMember(name="architect", role=MemberRole.AGENT, agent_role="architect")
        assert m.is_agent
        assert not m.is_owner
        assert "Architect" in m.display_name

    def test_human_owner(self):
        m = GroupMember(name="Alice", role=MemberRole.HUMAN_OWNER, phone_number="123")
        assert not m.is_agent
        assert m.is_owner
        assert m.display_name == "Alice"

    def test_human_member(self):
        m = GroupMember(name="Bob", role=MemberRole.HUMAN_MEMBER)
        assert not m.is_agent
        assert not m.is_owner


class TestGroupChat:
    def test_create_group(self):
        group = GroupChat(name="Test Group")
        assert group.name == "Test Group"
        assert group.message_count == 0
        assert len(group.members) == 0

    def test_add_members(self):
        group = GroupChat()
        agent = GroupMember(name="dev", role=MemberRole.AGENT, agent_role="developer")
        human = GroupMember(name="Alice", role=MemberRole.HUMAN_OWNER)
        group.add_member(agent)
        group.add_member(human)

        assert len(group.members) == 2
        assert len(group.agent_members) == 1
        assert len(group.human_members) == 1
        assert len(group.owners) == 1

    def test_remove_member(self):
        group = GroupChat()
        member = GroupMember(name="dev", role=MemberRole.AGENT)
        group.add_member(member)
        removed = group.remove_member("dev")
        assert removed is not None
        assert len(group.members) == 0

    def test_remove_nonexistent(self):
        group = GroupChat()
        assert group.remove_member("nobody") is None

    def test_post_message(self):
        group = GroupChat()
        group.add_member(GroupMember(name="dev", role=MemberRole.AGENT))
        msg = group.post_message("dev", "Hello team!")
        assert msg.sender == "dev"
        assert msg.content == "Hello team!"
        assert group.message_count == 1

    def test_post_message_non_member_raises(self):
        group = GroupChat()
        with pytest.raises(ValueError, match="not a member"):
            group.post_message("stranger", "Hi")

    def test_get_messages_with_filters(self):
        group = GroupChat()
        group.add_member(GroupMember(name="a", role=MemberRole.AGENT))
        group.add_member(GroupMember(name="b", role=MemberRole.AGENT))

        group.post_message("a", "msg1")
        group.post_message("b", "msg2")
        group.post_message("a", "msg3", message_type="requirement")

        assert len(group.get_messages()) == 3
        assert len(group.get_messages(sender="a")) == 2
        assert len(group.get_messages(message_type="requirement")) == 1
        assert len(group.get_messages(limit=1)) == 1

    def test_message_handler(self):
        group = GroupChat()
        group.add_member(GroupMember(name="dev", role=MemberRole.AGENT))
        received = []
        group.on_message(lambda m: received.append(m))
        group.post_message("dev", "test")
        assert len(received) == 1

    def test_get_info(self):
        group = GroupChat(name="My Group")
        group.add_member(GroupMember(name="dev", role=MemberRole.AGENT, agent_role="developer"))
        group.add_member(GroupMember(name="Alice", role=MemberRole.HUMAN_OWNER))
        info = group.get_info()
        assert info["name"] == "My Group"
        assert info["member_count"] == 2
        assert len(info["agents"]) == 1
        assert len(info["humans"]) == 1

    def test_format_history(self):
        group = GroupChat()
        group.add_member(GroupMember(name="dev", role=MemberRole.AGENT, agent_role="developer"))
        group.post_message("dev", "Hello!")
        history = group.format_history()
        assert "dev" in history
        assert "Hello!" in history

    def test_format_history_empty(self):
        group = GroupChat()
        assert group.format_history() == "(No messages yet)"

    def test_system_message_on_remove(self):
        group = GroupChat()
        group.add_member(GroupMember(name="dev", role=MemberRole.AGENT))
        group.remove_member("dev")
        messages = group.get_messages(message_type="system")
        assert len(messages) == 1
        assert "left" in messages[0].content
