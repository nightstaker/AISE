"""Tests for the on-demand interactive session."""

from __future__ import annotations

from typing import Any


from aise.core.session import OnDemandSession, UserCommand, parse_command
from aise.core.orchestrator import Orchestrator
from aise.core.agent import Agent, AgentRole
from aise.core.artifact import Artifact, ArtifactType
from aise.core.skill import Skill, SkillContext
from aise.main import create_team


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class EchoRequirementSkill(Skill):
    @property
    def name(self) -> str:
        return "requirement_analysis"

    @property
    def description(self) -> str:
        return "Echo requirement analysis"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        raw = input_data.get("raw_requirements", "")
        return Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={
                "functional_requirements": [{"id": "FR-001", "description": raw}],
                "non_functional_requirements": [],
                "constraints": [],
                "raw_input": raw,
            },
            producer="product_manager",
        )


class EchoUserStorySkill(Skill):
    @property
    def name(self) -> str:
        return "user_story_writing"

    @property
    def description(self) -> str:
        return "Echo user story"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=ArtifactType.USER_STORIES,
            content={"stories": []},
            producer="product_manager",
        )


class EchoBugFixSkill(Skill):
    @property
    def name(self) -> str:
        return "bug_fix"

    @property
    def description(self) -> str:
        return "Echo bug fix"

    def validate_input(self, input_data: dict[str, Any]) -> list[str]:
        if not input_data.get("bug_reports") and not input_data.get("failing_tests"):
            return ["Either 'bug_reports' or 'failing_tests' is required"]
        return []

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=ArtifactType.BUG_REPORT,
            content={
                "fixes": [],
                "total_bugs": 1,
                "fixed_count": 1,
                "needs_investigation": 0,
            },
            producer="developer",
        )


class EchoTaskDecompSkill(Skill):
    @property
    def name(self) -> str:
        return "task_decomposition"

    @property
    def description(self) -> str:
        return "Echo task decomposition"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "tasks": [
                    {
                        "id": "TASK-001",
                        "agent": "developer",
                        "description": "Sample task",
                    },
                ],
                "total_tasks": 1,
            },
            producer="team_lead",
        )


def _make_session() -> OnDemandSession:
    """Create a session with minimal stub agents for testing."""
    orch = Orchestrator()
    bus = orch.message_bus
    store = orch.artifact_store

    pm = Agent("product_manager", AgentRole.PRODUCT_MANAGER, bus, store)
    pm.register_skill(EchoRequirementSkill())
    pm.register_skill(EchoUserStorySkill())
    orch.register_agent(pm)

    dev = Agent("developer", AgentRole.DEVELOPER, bus, store)
    dev.register_skill(EchoBugFixSkill())
    orch.register_agent(dev)

    lead = Agent("team_lead", AgentRole.TEAM_LEAD, bus, store)
    lead.register_skill(EchoTaskDecompSkill())
    orch.register_agent(lead)

    return OnDemandSession(orch, project_name="TestProject")


# ---------------------------------------------------------------------------
# parse_command tests
# ---------------------------------------------------------------------------


class TestParseCommand:
    def test_add_command(self):
        cmd, text = parse_command("add Build a REST API")
        assert cmd == UserCommand.ADD_REQUIREMENT
        assert text == "Build a REST API"

    def test_req_alias(self):
        cmd, text = parse_command("req some feature")
        assert cmd == UserCommand.ADD_REQUIREMENT
        assert text == "some feature"

    def test_bug_command(self):
        cmd, text = parse_command("bug Login is broken")
        assert cmd == UserCommand.BUG
        assert text == "Login is broken"

    def test_fix_alias(self):
        cmd, text = parse_command("fix crash on startup")
        assert cmd == UserCommand.BUG
        assert text == "crash on startup"

    def test_status(self):
        cmd, text = parse_command("status")
        assert cmd == UserCommand.STATUS
        assert text == ""

    def test_artifacts(self):
        cmd, text = parse_command("artifacts requirements")
        assert cmd == UserCommand.ARTIFACTS
        assert text == "requirements"

    def test_phase(self):
        cmd, text = parse_command("phase design")
        assert cmd == UserCommand.RUN_PHASE
        assert text == "design"

    def test_workflow(self):
        cmd, text = parse_command("workflow")
        assert cmd == UserCommand.RUN_WORKFLOW

    def test_run_alias(self):
        cmd, text = parse_command("run")
        assert cmd == UserCommand.RUN_WORKFLOW

    def test_ask(self):
        cmd, text = parse_command("ask How should I structure the auth module?")
        assert cmd == UserCommand.ASK
        assert "auth module" in text

    def test_help(self):
        cmd, text = parse_command("help")
        assert cmd == UserCommand.HELP

    def test_quit(self):
        cmd, text = parse_command("quit")
        assert cmd == UserCommand.QUIT

    def test_exit_alias(self):
        cmd, text = parse_command("exit")
        assert cmd == UserCommand.QUIT

    def test_q_alias(self):
        cmd, text = parse_command("q")
        assert cmd == UserCommand.QUIT

    def test_empty_input_returns_help(self):
        cmd, text = parse_command("")
        assert cmd == UserCommand.HELP

    def test_unknown_input_treated_as_requirement(self):
        cmd, text = parse_command("Build me a dashboard")
        assert cmd == UserCommand.ADD_REQUIREMENT
        assert text == "Build me a dashboard"

    def test_case_insensitive(self):
        cmd, _ = parse_command("BUG something")
        assert cmd == UserCommand.BUG


# ---------------------------------------------------------------------------
# OnDemandSession tests
# ---------------------------------------------------------------------------


class TestOnDemandSession:
    def test_add_requirement(self):
        session = _make_session()
        result = session.handle_input("add Build a REST API for user management")
        assert result["status"] == "ok"
        assert "artifact_id" in result
        assert "Requirement added" in result["output"]

    def test_add_requirement_empty(self):
        session = _make_session()
        result = session.handle_input("add")
        assert result["status"] == "error"
        assert "provide" in result["output"].lower()

    def test_bug_report(self):
        session = _make_session()
        result = session.handle_input("bug Login page crashes on submit")
        assert result["status"] == "ok"
        assert "Bug report processed" in result["output"]

    def test_bug_report_empty(self):
        session = _make_session()
        result = session.handle_input("bug")
        assert result["status"] == "error"

    def test_status(self):
        session = _make_session()
        result = session.handle_input("status")
        assert result["status"] == "ok"
        assert "TestProject" in result["output"]
        assert "Agents registered" in result["output"]

    def test_artifacts_empty(self):
        session = _make_session()
        result = session.handle_input("artifacts")
        assert result["status"] == "ok"
        assert "No artifacts" in result["output"]

    def test_artifacts_after_add(self):
        session = _make_session()
        session.handle_input("add Some feature")
        result = session.handle_input("artifacts")
        assert result["status"] == "ok"
        assert "requirements" in result["output"]

    def test_artifacts_filter(self):
        session = _make_session()
        session.handle_input("add Some feature")
        result = session.handle_input("artifacts requirements")
        assert result["status"] == "ok"
        assert "requirements" in result["output"]

    def test_ask_command(self):
        session = _make_session()
        result = session.handle_input("ask How should I structure the auth module?")
        assert result["status"] == "ok"
        assert "tasks" in result["output"].lower()

    def test_ask_empty(self):
        session = _make_session()
        result = session.handle_input("ask")
        assert result["status"] == "error"

    def test_help_command(self):
        session = _make_session()
        result = session.handle_input("help")
        assert result["status"] == "ok"
        assert "add" in result["output"]
        assert "bug" in result["output"]
        assert "quit" in result["output"]

    def test_quit_command(self):
        session = _make_session()
        result = session.handle_input("quit")
        assert result["status"] == "ok"
        assert not session.is_running

    def test_history_tracking(self):
        session = _make_session()
        session.handle_input("help")
        session.handle_input("status")
        assert len(session.history) == 2
        assert session.history[0]["command"] == "help"
        assert session.history[1]["command"] == "status"

    def test_unknown_command_adds_requirement(self):
        session = _make_session()
        result = session.handle_input("Build me a dashboard")
        assert result["status"] == "ok"
        assert result["command"] == "add"

    def test_phase_missing_name(self):
        session = _make_session()
        result = session.handle_input("phase")
        assert result["status"] == "error"
        assert "specify" in result["output"].lower()

    def test_phase_unknown_name(self):
        session = _make_session()
        result = session.handle_input("phase nonexistent")
        assert result["status"] == "error"
        assert "Unknown phase" in result["output"]

    def test_workflow_no_requirements(self):
        session = _make_session()
        result = session.handle_input("workflow")
        assert result["status"] == "error"
        assert "No requirements" in result["output"]

    def test_start_and_quit_via_input_fn(self):
        session = _make_session()
        outputs: list[str] = []
        commands = iter(["status", "quit"])
        session = OnDemandSession(
            session.orchestrator,
            project_name="TestProject",
            output=outputs.append,
        )
        session.start(input_fn=lambda: next(commands))
        assert any("TestProject" in o for o in outputs)
        assert any("Goodbye" in o for o in outputs)

    def test_start_handles_eof(self):
        session = _make_session()
        outputs: list[str] = []

        def raise_eof():
            raise EOFError

        session = OnDemandSession(
            session.orchestrator,
            project_name="TestProject",
            output=outputs.append,
        )
        session.start(input_fn=raise_eof)
        assert any("ended" in o.lower() for o in outputs)

    def test_start_handles_keyboard_interrupt(self):
        session = _make_session()
        outputs: list[str] = []

        def raise_interrupt():
            raise KeyboardInterrupt

        session = OnDemandSession(
            session.orchestrator,
            project_name="TestProject",
            output=outputs.append,
        )
        session.start(input_fn=raise_interrupt)
        assert not session.is_running


class TestOnDemandSessionWithFullTeam:
    """Tests using the real create_team() with all agents and skills."""

    def test_full_team_add_requirement(self):
        orch = create_team()
        session = OnDemandSession(orch, project_name="FullTeamTest")
        result = session.handle_input("add Build a REST API for user management")
        assert result["status"] == "ok"

    def test_full_team_bug_report(self):
        orch = create_team()
        session = OnDemandSession(orch, project_name="FullTeamTest")
        result = session.handle_input("bug Login page returns 500 on empty password")
        assert result["status"] == "ok"

    def test_full_team_status(self):
        orch = create_team()
        session = OnDemandSession(orch, project_name="FullTeamTest")
        result = session.handle_input("status")
        assert result["status"] == "ok"
        assert "5" in result["output"]  # 5 agents

    def test_full_team_ask(self):
        orch = create_team()
        session = OnDemandSession(orch, project_name="FullTeamTest")
        result = session.handle_input("ask Build a chat feature")
        assert result["status"] == "ok"
