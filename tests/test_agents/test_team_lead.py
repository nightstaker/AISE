"""Tests for the Team Lead agent and skills."""

from aise.agents.product_manager import ProductManagerAgent
from aise.agents.team_lead import TeamLeadAgent
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus


class TestTeamLeadAgent:
    def _make_agent(self):
        bus = MessageBus()
        store = ArtifactStore()
        return TeamLeadAgent(bus, store), store

    def test_has_all_skills(self):
        agent, _ = self._make_agent()
        expected = {
            "task_decomposition",
            "task_assignment",
            "conflict_resolution",
            "progress_tracking",
            "pr_review",
            "pr_merge",
        }
        assert set(agent.skill_names) == expected

    def test_task_decomposition(self):
        agent, store = self._make_agent()
        artifact = agent.execute_skill(
            "task_decomposition",
            {
                "goals": ["Build user auth", "Build dashboard"],
            },
        )
        assert "tasks" in artifact.content
        assert artifact.content["total_tasks"] > 0

    def test_task_assignment(self):
        agent, store = self._make_agent()
        artifact = agent.execute_skill(
            "task_assignment",
            {
                "tasks": [
                    {"id": "T1", "skill": "code_generation", "phase": "impl"},
                    {"id": "T2", "skill": "test_plan_design", "phase": "test"},
                ],
            },
        )
        assignments = artifact.content["assignments"]
        assert len(assignments) == 2
        assert assignments[0]["assigned_to"] == "developer"
        assert assignments[1]["assigned_to"] == "qa_engineer"

    def test_conflict_resolution(self):
        agent, store = self._make_agent()
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
        pm = ProductManagerAgent(bus, store)
        lead = TeamLeadAgent(bus, store)

        pm.execute_skill("requirement_analysis", {"raw_requirements": "Feature X"})

        artifact = lead.execute_skill("progress_tracking", {})
        assert "phases" in artifact.content
        assert "progress_percentage" in artifact.content
