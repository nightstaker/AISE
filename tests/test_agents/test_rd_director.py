"""Tests for the RD Director agent and skills."""

from aise.agents.rd_director import RDDirectorAgent
from aise.core.agent import AgentRole
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus


class TestRDDirectorAgent:
    def _make_agent(self):
        bus = MessageBus()
        store = ArtifactStore()
        return RDDirectorAgent(bus, store), bus, store

    def test_has_all_skills(self):
        agent, _, _ = self._make_agent()
        expected = {"team_formation", "requirement_distribution"}
        assert set(agent.skill_names) == expected

    def test_role_is_rd_director(self):
        agent, _, _ = self._make_agent()
        assert agent.role == AgentRole.RD_DIRECTOR
        assert agent.name == "rd_director"

    def test_team_formation_basic(self):
        agent, _, _ = self._make_agent()
        artifact = agent.execute_skill(
            "team_formation",
            {
                "roles": {
                    "developer": {"count": 3, "model": "gpt-4o"},
                    "qa_engineer": {"count": 1},
                    "architect": {"count": 1},
                },
                "development_mode": "local",
            },
        )
        content = artifact.content
        assert content["total_roles"] == 3
        assert content["total_agents"] == 5
        assert content["development_mode"] == "local"

    def test_team_formation_github_mode(self):
        agent, _, _ = self._make_agent()
        artifact = agent.execute_skill(
            "team_formation",
            {
                "roles": {"developer": {"count": 2}},
                "development_mode": "github",
            },
        )
        assert artifact.content["development_mode"] == "github"

    def test_team_formation_disabled_role_excluded(self):
        agent, _, _ = self._make_agent()
        artifact = agent.execute_skill(
            "team_formation",
            {
                "roles": {
                    "developer": {"count": 2},
                    "qa_engineer": {"count": 1, "enabled": False},
                },
                "development_mode": "local",
            },
        )
        assert artifact.content["total_roles"] == 1
        assert artifact.content["total_agents"] == 2

    def test_team_formation_single_agent_name(self):
        agent, _, _ = self._make_agent()
        artifact = agent.execute_skill(
            "team_formation",
            {
                "roles": {"developer": {"count": 1}},
                "development_mode": "local",
            },
        )
        roster = artifact.content["team_roster"]
        assert roster[0]["agent_names"] == ["developer"]

    def test_team_formation_multiple_agent_names(self):
        agent, _, _ = self._make_agent()
        artifact = agent.execute_skill(
            "team_formation",
            {
                "roles": {"developer": {"count": 3}},
                "development_mode": "local",
            },
        )
        roster = artifact.content["team_roster"]
        assert roster[0]["agent_names"] == ["developer_1", "developer_2", "developer_3"]

    def test_team_formation_validation_missing_roles(self):
        agent, _, _ = self._make_agent()
        skill = agent.get_skill("team_formation")
        errors = skill.validate_input({})
        assert len(errors) > 0

    def test_team_formation_validation_invalid_mode(self):
        agent, _, _ = self._make_agent()
        skill = agent.get_skill("team_formation")
        errors = skill.validate_input({"roles": {"developer": {}}, "development_mode": "cloud"})
        assert len(errors) > 0

    def test_requirement_distribution_string_input(self):
        agent, _, _ = self._make_agent()
        artifact = agent.execute_skill(
            "requirement_distribution",
            {
                "product_requirements": "Build a REST API for user management",
                "architecture_requirements": "Must use PostgreSQL and Docker",
                "project_name": "UserAPI",
            },
        )
        dist = artifact.content["distribution"]
        assert dist["product_requirement_count"] == 1
        assert dist["architecture_requirement_count"] == 1
        assert dist["project_name"] == "UserAPI"

    def test_requirement_distribution_list_input(self):
        agent, _, _ = self._make_agent()
        artifact = agent.execute_skill(
            "requirement_distribution",
            {
                "product_requirements": ["Feature A", "Feature B", "Feature C"],
                "architecture_requirements": ["Use microservices", "Deploy on K8s"],
            },
        )
        dist = artifact.content["distribution"]
        assert dist["product_requirement_count"] == 3
        assert dist["architecture_requirement_count"] == 2

    def test_requirement_distribution_defaults_recipients(self):
        agent, _, _ = self._make_agent()
        artifact = agent.execute_skill(
            "requirement_distribution",
            {"product_requirements": "Build something"},
        )
        dist = artifact.content["distribution"]
        assert "product_manager" in dist["recipients"]
        assert "architect" in dist["recipients"]

    def test_requirement_distribution_custom_recipients(self):
        agent, _, _ = self._make_agent()
        artifact = agent.execute_skill(
            "requirement_distribution",
            {
                "product_requirements": "Build something",
                "recipients": ["developer", "qa_engineer"],
            },
        )
        dist = artifact.content["distribution"]
        assert dist["recipients"] == ["developer", "qa_engineer"]

    def test_requirement_distribution_validation_missing_product_req(self):
        agent, _, _ = self._make_agent()
        skill = agent.get_skill("requirement_distribution")
        errors = skill.validate_input({})
        assert len(errors) > 0

    def test_form_team_method(self):
        agent, _, _ = self._make_agent()
        report = agent.form_team(
            roles={"developer": {"count": 2}, "architect": {"count": 1}},
            development_mode="local",
            project_name="TestProject",
        )
        assert report["total_roles"] == 2
        assert report["total_agents"] == 3

    def test_distribute_requirements_method(self):
        agent, _, _ = self._make_agent()
        record = agent.distribute_requirements(
            product_requirements="Build a dashboard",
            architecture_requirements="Use React and FastAPI",
            project_name="DashboardProject",
        )
        assert record["product_requirement_count"] == 1
        assert record["architecture_requirement_count"] == 1
        assert record["project_name"] == "DashboardProject"

    def test_handle_standard_skill_request(self):
        from aise.core.message import Message, MessageType

        agent, _, _ = self._make_agent()
        msg = Message(
            sender="orchestrator",
            receiver="rd_director",
            msg_type=MessageType.REQUEST,
            content={
                "skill": "team_formation",
                "input_data": {
                    "roles": {"developer": {"count": 1}},
                    "development_mode": "local",
                },
            },
        )
        response = agent.handle_message(msg)
        assert response is not None
        assert response.content["status"] == "success"
