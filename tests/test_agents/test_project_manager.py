"""Tests for the Project Manager agent and skills."""

from datetime import datetime, timedelta, timezone

from aise.agents.product_manager import ProductManagerAgent
from aise.agents.project_manager import ProjectManagerAgent
from aise.core.agent import AgentRole
from aise.core.artifact import Artifact, ArtifactStore, ArtifactType
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
            "version_release",
            "team_health",
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

    def test_version_release_ready(self):
        bus = MessageBus()
        store = ArtifactStore()
        agent = ProjectManagerAgent(bus, store)

        # Seed required artifacts
        for artifact_type in (
            ArtifactType.REQUIREMENTS,
            ArtifactType.ARCHITECTURE_DESIGN,
            ArtifactType.SOURCE_CODE,
            ArtifactType.UNIT_TESTS,
        ):
            store.store(
                Artifact(
                    artifact_type=artifact_type,
                    content={"data": "present"},
                    producer="test",
                )
            )

        artifact = agent.execute_skill(
            "version_release",
            {"version": "1.0.0", "release_notes": "Initial release", "release_type": "major"},
        )
        assert artifact.content["version"] == "1.0.0"
        assert artifact.content["is_ready"] is True
        assert artifact.content["status"] == "released"
        assert artifact.content["blockers"] == []

    def test_version_release_blocked(self):
        agent, _ = self._make_agent()
        # No artifacts seeded — release should be blocked
        artifact = agent.execute_skill(
            "version_release",
            {"version": "0.1.0"},
        )
        assert artifact.content["is_ready"] is False
        assert artifact.content["status"] == "blocked"
        assert len(artifact.content["blockers"]) > 0

    def test_version_release_validation_missing_version(self):
        agent, _ = self._make_agent()
        skill = agent.get_skill("version_release")
        errors = skill.validate_input({})
        assert len(errors) > 0

    def test_team_health_healthy(self):
        bus = MessageBus()
        store = ArtifactStore()
        agent = ProjectManagerAgent(bus, store)
        # Seed an artifact so delivery is considered started
        store.store(Artifact(artifact_type=ArtifactType.REQUIREMENTS, content={}, producer="test"))
        artifact = agent.execute_skill(
            "team_health",
            {
                "agent_statuses": {"developer": "active", "architect": "active"},
                "blocked_tasks": [],
                "overdue_tasks": [],
            },
        )
        assert artifact.content["health_score"] == 100
        assert artifact.content["health_status"] == "healthy"
        assert artifact.content["risk_factors"] == []

    def test_team_health_at_risk(self):
        agent, _ = self._make_agent()
        artifact = agent.execute_skill(
            "team_health",
            {
                "blocked_tasks": ["task1", "task2", "task3", "task4"],
                "overdue_tasks": ["task5", "task6", "task7"],
            },
        )
        assert artifact.content["health_score"] < 70
        assert artifact.content["health_status"] in ("at_risk", "critical")
        assert len(artifact.content["risk_factors"]) > 0
        assert len(artifact.content["recommendations"]) > 0

    def test_team_health_critical(self):
        agent, _ = self._make_agent()
        artifact = agent.execute_skill(
            "team_health",
            {
                "blocked_tasks": ["t1", "t2", "t3", "t4", "t5", "t6", "t7"],
                "overdue_tasks": ["o1", "o2", "o3", "o4", "o5"],
            },
        )
        assert artifact.content["health_score"] < 40
        assert artifact.content["health_status"] == "critical"

    # ------------------------------------------------------------------
    # HA: crash detection
    # ------------------------------------------------------------------

    def test_ha_crash_detection_no_messages(self):
        """Agent in registry with no message activity is flagged as crashed."""
        agent, store = self._make_agent()
        store.store(Artifact(artifact_type=ArtifactType.REQUIREMENTS, content={}, producer="test"))

        artifact = agent.execute_skill(
            "team_health",
            {
                "agent_registry": {"developer": {}, "architect": {}},
                "message_history": [],  # no messages at all
                "task_statuses": [],
            },
        )
        content = artifact.content
        assert len(content["crashed_agents"]) == 2
        crashed_names = {a["agent"] for a in content["crashed_agents"]}
        assert crashed_names == {"developer", "architect"}
        assert len(content["recovery_actions"]) == 2
        assert all(a["action"] == "restart" for a in content["recovery_actions"])
        # HA penalty: 2 crashed × 20 = −40 → score 60 → at_risk
        assert content["health_score"] == 60
        assert content["health_status"] == "at_risk"

    def test_ha_crash_detection_partial(self):
        """Only agents absent from message history are flagged."""
        agent, store = self._make_agent()
        store.store(Artifact(artifact_type=ArtifactType.REQUIREMENTS, content={}, producer="test"))

        now = datetime.now(timezone.utc)
        history = [
            {
                "sender": "developer",
                "receiver": "project_manager",
                "timestamp": now.isoformat(),
            }
        ]
        artifact = agent.execute_skill(
            "team_health",
            {
                "agent_registry": {"developer": {}, "architect": {}},
                "message_history": history,
                "task_statuses": [],
            },
        )
        content = artifact.content
        crashed_names = {a["agent"] for a in content["crashed_agents"]}
        assert "architect" in crashed_names
        assert "developer" not in crashed_names

    # ------------------------------------------------------------------
    # HA: stuck-session detection
    # ------------------------------------------------------------------

    def test_ha_stuck_detection(self):
        """Agent with in-progress tasks and stale last message is flagged stuck."""
        agent, store = self._make_agent()
        store.store(Artifact(artifact_type=ArtifactType.REQUIREMENTS, content={}, producer="test"))

        stale_ts = (datetime.now(timezone.utc) - timedelta(seconds=600)).isoformat()
        history = [{"sender": "developer", "receiver": "architect", "timestamp": stale_ts}]
        task_statuses = [{"task_id": "TASK-01", "assignee": "developer", "status": "in_progress"}]
        artifact = agent.execute_skill(
            "team_health",
            {
                "agent_registry": {"developer": {}},
                "message_history": history,
                "task_statuses": task_statuses,
                "stuck_threshold_seconds": 300,
            },
        )
        content = artifact.content
        assert len(content["stuck_agents"]) == 1
        stuck = content["stuck_agents"][0]
        assert stuck["agent"] == "developer"
        assert stuck["idle_seconds"] >= 600
        assert "TASK-01" in stuck["in_progress_tasks"]
        assert any(a["action"] == "interrupt_and_reassign" for a in content["recovery_actions"])
        assert content["health_score"] <= 85  # −15 for stuck agent

    def test_ha_active_agent_not_stuck(self):
        """Agent with recent message activity is not flagged even with in-progress tasks."""
        agent, store = self._make_agent()
        store.store(Artifact(artifact_type=ArtifactType.REQUIREMENTS, content={}, producer="test"))

        recent_ts = datetime.now(timezone.utc).isoformat()
        history = [{"sender": "developer", "receiver": "architect", "timestamp": recent_ts}]
        task_statuses = [{"task_id": "TASK-01", "assignee": "developer", "status": "in_progress"}]
        artifact = agent.execute_skill(
            "team_health",
            {
                "agent_registry": {"developer": {}},
                "message_history": history,
                "task_statuses": task_statuses,
                "stuck_threshold_seconds": 300,
            },
        )
        content = artifact.content
        assert content["stuck_agents"] == []
        assert content["crashed_agents"] == []

    def test_ha_no_registry_skips_ha_checks(self):
        """Without an agent_registry, HA checks are skipped and lists are empty."""
        agent, store = self._make_agent()
        store.store(Artifact(artifact_type=ArtifactType.REQUIREMENTS, content={}, producer="test"))

        artifact = agent.execute_skill("team_health", {})
        content = artifact.content
        assert content["crashed_agents"] == []
        assert content["stuck_agents"] == []
        assert content["recovery_actions"] == []

    # ------------------------------------------------------------------
    # HA: check_agent_health convenience method
    # ------------------------------------------------------------------

    def test_check_agent_health_convenience(self):
        """check_agent_health returns dict with HA fields."""
        bus = MessageBus()
        store = ArtifactStore()
        agent = ProjectManagerAgent(bus, store)
        store.store(Artifact(artifact_type=ArtifactType.REQUIREMENTS, content={}, producer="test"))

        result = agent.check_agent_health(
            agent_registry={"developer": {}},
            message_history=[],
            task_statuses=[],
        )
        assert "crashed_agents" in result
        assert "stuck_agents" in result
        assert "recovery_actions" in result
        # developer never messaged → crashed
        assert len(result["crashed_agents"]) == 1
        assert result["crashed_agents"][0]["agent"] == "developer"

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
        # A recovery broadcast should have been sent
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
        # Base handler returns None for unrecognised notifications
        assert response is None
