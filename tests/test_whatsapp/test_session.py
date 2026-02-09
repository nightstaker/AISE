"""Tests for the WhatsApp group session."""

from aise.config import ProjectConfig
from aise.main import create_team
from aise.whatsapp.session import WhatsAppGroupSession


def _make_session() -> WhatsAppGroupSession:
    """Create a test session with the full agent team."""
    config = ProjectConfig(project_name="Test Project")
    orchestrator = create_team(config)
    return WhatsAppGroupSession(
        orchestrator=orchestrator,
        project_name="Test Project",
    )


class TestWhatsAppGroupSession:
    def test_session_creation(self):
        session = _make_session()
        assert session.project_name == "Test Project"
        assert not session.is_running
        assert len(session.group_chat.agent_members) == 5

    def test_agents_registered_in_group(self):
        session = _make_session()
        agent_names = {m.name for m in session.group_chat.agent_members}
        assert "product_manager" in agent_names
        assert "architect" in agent_names
        assert "developer" in agent_names
        assert "qa_engineer" in agent_names
        assert "team_lead" in agent_names

    def test_add_human_owner(self):
        session = _make_session()
        member = session.add_human("Alice", "123", is_owner=True)
        assert member.is_owner
        assert member.name == "Alice"
        assert len(session.group_chat.human_members) == 1

    def test_add_human_member(self):
        session = _make_session()
        member = session.add_human("Bob", "456", is_owner=False)
        assert not member.is_owner

    def test_send_requirement(self):
        session = _make_session()
        session.add_human("Alice", "123")
        result = session.send_requirement("Alice", "Build a REST API")
        assert result["status"] in ("ok", "error")
        # The requirement message should be in the group
        messages = session.group_chat.get_messages(sender="Alice")
        assert len(messages) >= 1
        assert any("REST API" in m.content for m in messages)

    def test_group_info(self):
        session = _make_session()
        session.add_human("Alice", "123")
        info = session.group_chat.get_info()
        assert info["member_count"] == 6  # 5 agents + 1 human
        assert len(info["agents"]) == 5
        assert len(info["humans"]) == 1

    def test_slash_command_members(self):
        session = _make_session()
        session.add_human("Alice", "123")

        output_lines = []
        session._print = lambda text: output_lines.append(text)
        session._handle_slash_command("/members")

        combined = "\n".join(output_lines)
        assert "Alice" in combined
        assert "product_manager" in combined or "Product Manager" in combined

    def test_slash_command_history(self):
        session = _make_session()
        session.add_human("Alice", "123")
        session.group_chat.post_message("Alice", "Hello team!")

        output_lines = []
        session._print = lambda text: output_lines.append(text)
        session._handle_slash_command("/history")

        combined = "\n".join(output_lines)
        assert "Hello team!" in combined

    def test_slash_command_quit(self):
        session = _make_session()
        session._running = True
        session._handle_slash_command("/quit")
        assert not session._running

    def test_slash_command_unknown(self):
        session = _make_session()
        output_lines = []
        session._print = lambda text: output_lines.append(text)
        session._handle_slash_command("/foobar")
        assert any("Unknown" in line for line in output_lines)

    def test_process_input_auto_joins(self):
        session = _make_session()
        output_lines = []
        session._print = lambda text: output_lines.append(text)

        # Bridge must be started for message routing
        session.bridge.start()

        # Sending input without joining should auto-join as "Owner"
        session._process_input("Build a login page")
        assert session.group_chat.get_member("Owner") is not None

        session.bridge.stop()

    def test_process_input_at_mention(self):
        session = _make_session()
        session.add_human("Alice", "123")
        session.bridge.start()

        session._process_input("@dev fix the bug")

        messages = session.group_chat.get_messages(sender="Alice")
        assert len(messages) >= 1

        session.bridge.stop()

    def test_bridge_activation(self):
        session = _make_session()
        assert not session.bridge.is_active

        session.bridge.start()
        assert session.bridge.is_active

        session.bridge.stop()
        assert not session.bridge.is_active

    def test_start_stop_lifecycle(self):
        session = _make_session()

        # Simulate a quick session that quits immediately
        inputs = iter(["/quit"])
        output_lines = []
        session._print = lambda text: output_lines.append(text)
        session.start(input_fn=lambda: next(inputs))

        assert not session.is_running

    def test_join_command(self):
        session = _make_session()
        output_lines = []
        session._print = lambda text: output_lines.append(text)

        session._handle_slash_command("/join TestUser 5551234567")
        member = session.group_chat.get_member("TestUser")
        assert member is not None
        assert member.phone_number == "5551234567"

    def test_invite_command(self):
        session = _make_session()
        output_lines = []
        session._print = lambda text: output_lines.append(text)

        session._handle_slash_command("/invite Bob 5559876543")
        member = session.group_chat.get_member("Bob")
        assert member is not None
        assert not member.is_owner

    def test_invite_missing_args(self):
        session = _make_session()
        output_lines = []
        session._print = lambda text: output_lines.append(text)

        session._handle_slash_command("/invite")
        assert any("Usage" in line for line in output_lines)
