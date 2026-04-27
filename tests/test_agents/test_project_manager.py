"""Tests for the Project Manager agent and skills."""

from aise.agents.product_manager import ProductManagerAgent
from aise.agents.project_manager import ProjectManagerAgent
from aise.core.agent import AgentRole
from aise.core.artifact import ArtifactStore
from aise.core.message import Message, MessageBus, MessageType


class TestProjectManagerAgent:
    def _make_agent(self):
        bus = MessageBus()
        store = ArtifactStore()
        return ProjectManagerAgent(bus, store), store

    def test_has_all_skills(self):
        agent, _ = self._make_agent()
        expected = {
            "conflict_resolution",
            "progress_tracking",
            "pr_review",
            "pr_merge",
        }
        assert set(agent.skill_names) == expected

    def test_role_is_project_manager(self):
        agent, _ = self._make_agent()
        assert agent.role == AgentRole.PROJECT_MANAGER
        assert agent.name == "project_manager"

    def test_no_task_decomposition_skill(self):
        agent, _ = self._make_agent()
        assert "task_decomposition" not in agent.skill_names

    def test_no_task_assignment_skill(self):
        agent, _ = self._make_agent()
        assert "task_assignment" not in agent.skill_names

    def test_conflict_resolution(self):
        agent, _ = self._make_agent()
        artifact = agent.execute_skill(
            "conflict_resolution",
            {
                "conflicts": [
                    {
                        "parties": ["architect", "developer"],
                        "issue": "Database choice",
                        "options": ["PostgreSQL", "MongoDB"],
                    }
                ],
            },
        )
        resolutions = artifact.content["resolutions"]
        assert len(resolutions) == 1
        assert resolutions[0]["status"] == "resolved"

    def test_progress_tracking(self):
        bus = MessageBus()
        store = ArtifactStore()
        pm_agent = ProductManagerAgent(bus, store)
        proj_mgr = ProjectManagerAgent(bus, store)

        pm_agent.execute_skill("requirement_analysis", {"raw_requirements": "Feature X"})

        artifact = proj_mgr.execute_skill("progress_tracking", {})
        assert "phases" in artifact.content
        assert "progress_percentage" in artifact.content

    # ------------------------------------------------------------------
    # HA: notification handling
    # ------------------------------------------------------------------

    def test_handle_agent_crashed_notification(self):
        """PM acknowledges agent_crashed notification and broadcasts recovery."""
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProjectManagerAgent(bus, store)

        received_broadcasts = []

        def capture(msg: Message):
            received_broadcasts.append(msg)

        bus.subscribe("broadcast", capture)

        crashed_msg = Message(
            sender="orchestrator",
            receiver="project_manager",
            msg_type=MessageType.NOTIFICATION,
            content={"event": "agent_crashed", "agent": "developer", "tasks": []},
        )
        response = pm.handle_message(crashed_msg)

        assert response is not None
        assert response.content["status"] == "acknowledged"
        assert response.content["action"] == "restart"
        assert response.content["agent"] == "developer"
        assert len(received_broadcasts) >= 1
        broadcast = received_broadcasts[0]
        assert broadcast.content["event"] == "ha_recovery"
        assert broadcast.content["source_event"] == "agent_crashed"

    def test_handle_agent_stuck_notification(self):
        """PM acknowledges agent_stuck notification and broadcasts interrupt directive."""
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProjectManagerAgent(bus, store)

        received_broadcasts = []

        def capture(msg: Message):
            received_broadcasts.append(msg)

        bus.subscribe("broadcast", capture)

        stuck_msg = Message(
            sender="orchestrator",
            receiver="project_manager",
            msg_type=MessageType.NOTIFICATION,
            content={
                "event": "agent_stuck",
                "agent": "architect",
                "tasks": ["TASK-03", "TASK-04"],
            },
        )
        response = pm.handle_message(stuck_msg)

        assert response is not None
        assert response.content["status"] == "acknowledged"
        assert response.content["action"] == "interrupt_and_reassign"
        assert response.content["agent"] == "architect"
        broadcast = received_broadcasts[0]
        assert broadcast.content["action"] == "interrupt_and_reassign"
        assert broadcast.content["tasks"] == ["TASK-03", "TASK-04"]

    def test_unrelated_notification_falls_through(self):
        """Non-HA notifications are handled by the base class (return None)."""
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProjectManagerAgent(bus, store)

        other_msg = Message(
            sender="orchestrator",
            receiver="project_manager",
            msg_type=MessageType.NOTIFICATION,
            content={"event": "phase_complete", "phase": "requirements"},
        )
        response = pm.handle_message(other_msg)
        assert response is None
