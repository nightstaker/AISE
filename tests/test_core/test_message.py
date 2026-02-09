"""Tests for the message bus and message model."""

from aise.core.message import Message, MessageBus, MessageType


class TestMessage:
    def test_message_creation(self):
        msg = Message(
            sender="a",
            receiver="b",
            msg_type=MessageType.REQUEST,
            content={"key": "val"},
        )
        assert msg.sender == "a"
        assert msg.receiver == "b"
        assert msg.msg_type == MessageType.REQUEST
        assert msg.content == {"key": "val"}
        assert msg.id  # auto-generated
        assert msg.timestamp

    def test_message_reply(self):
        msg = Message(
            sender="a", receiver="b", msg_type=MessageType.REQUEST, content={"x": 1}
        )
        reply = msg.reply({"y": 2})
        assert reply.sender == "b"
        assert reply.receiver == "a"
        assert reply.msg_type == MessageType.RESPONSE
        assert reply.correlation_id == msg.id

    def test_reply_with_custom_type(self):
        msg = Message(
            sender="a", receiver="b", msg_type=MessageType.REQUEST, content={}
        )
        reply = msg.reply({}, MessageType.REVIEW)
        assert reply.msg_type == MessageType.REVIEW


class TestMessageBus:
    def test_subscribe_and_publish(self):
        bus = MessageBus()
        received = []
        bus.subscribe("agent_b", lambda m: received.append(m))

        msg = Message(
            sender="agent_a",
            receiver="agent_b",
            msg_type=MessageType.REQUEST,
            content={},
        )
        bus.publish(msg)

        assert len(received) == 1
        assert received[0].sender == "agent_a"

    def test_broadcast(self):
        bus = MessageBus()
        received_b = []
        received_c = []
        bus.subscribe("b", lambda m: received_b.append(m))
        bus.subscribe("c", lambda m: received_c.append(m))

        msg = Message(
            sender="a",
            receiver="broadcast",
            msg_type=MessageType.NOTIFICATION,
            content={},
        )
        bus.publish(msg)

        assert len(received_b) == 1
        assert len(received_c) == 1

    def test_broadcast_excludes_sender(self):
        bus = MessageBus()
        received = []
        bus.subscribe("a", lambda m: received.append(m))

        msg = Message(
            sender="a",
            receiver="broadcast",
            msg_type=MessageType.NOTIFICATION,
            content={},
        )
        bus.publish(msg)

        assert len(received) == 0

    def test_unsubscribe(self):
        bus = MessageBus()
        bus.subscribe("x", lambda m: None)
        bus.unsubscribe("x")

        msg = Message(
            sender="y", receiver="x", msg_type=MessageType.REQUEST, content={}
        )
        results = bus.publish(msg)
        assert results == []

    def test_history(self):
        bus = MessageBus()
        bus.subscribe("b", lambda m: None)

        msg1 = Message(
            sender="a", receiver="b", msg_type=MessageType.REQUEST, content={}
        )
        msg2 = Message(
            sender="b", receiver="a", msg_type=MessageType.RESPONSE, content={}
        )
        bus.publish(msg1)
        bus.publish(msg2)

        assert len(bus.get_history()) == 2
        assert len(bus.get_history("a")) == 2
        assert len(bus.get_history("c")) == 0

    def test_clear_history(self):
        bus = MessageBus()
        bus.publish(
            Message(sender="a", receiver="b", msg_type=MessageType.REQUEST, content={})
        )
        bus.clear_history()
        assert len(bus.get_history()) == 0
