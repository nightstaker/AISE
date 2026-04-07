"""Tests for runtime data models."""

from aise.runtime.models import AgentCard, AgentDefinition, AgentState, ProviderInfo, SkillInfo


class TestAgentState:
    def test_lifecycle_states(self):
        assert AgentState.CREATED.value == "created"
        assert AgentState.ACTIVE.value == "active"
        assert AgentState.STOPPED.value == "stopped"


class TestSkillInfo:
    def test_basic_creation(self):
        skill = SkillInfo(id="code_review", name="Code Review", description="Review code")
        assert skill.id == "code_review"
        assert skill.tags == []
        assert skill.examples == []

    def test_with_tags(self):
        skill = SkillInfo(
            id="test", name="Test", description="desc",
            tags=["qa", "testing"], examples=["example1"],
        )
        assert skill.tags == ["qa", "testing"]
        assert skill.examples == ["example1"]


class TestAgentDefinition:
    def test_defaults(self):
        defn = AgentDefinition(name="test", description="A test agent")
        assert defn.version == "1.0.0"
        assert defn.system_prompt == ""
        assert defn.skills == []
        assert defn.capabilities == {}

    def test_full_definition(self):
        defn = AgentDefinition(
            name="reviewer",
            description="Code reviewer",
            version="2.0.0",
            system_prompt="You are a reviewer",
            skills=[SkillInfo(id="review", name="Review", description="Review code")],
            capabilities={"streaming": True},
            provider=ProviderInfo(organization="AISE"),
        )
        assert defn.name == "reviewer"
        assert len(defn.skills) == 1
        assert defn.capabilities["streaming"] is True


class TestAgentCard:
    def test_to_dict(self):
        card = AgentCard(
            name="TestAgent",
            description="A test agent",
            url="http://localhost:8080",
            version="1.0.0",
            provider=ProviderInfo(organization="AISE", url="https://aise.dev"),
            skills=[SkillInfo(id="s1", name="Skill 1", description="First skill", tags=["t1"])],
        )
        d = card.to_dict()
        assert d["name"] == "TestAgent"
        assert d["version"] == "1.0.0"
        assert d["provider"]["organization"] == "AISE"
        assert len(d["skills"]) == 1
        assert d["skills"][0]["id"] == "s1"
        assert d["skills"][0]["tags"] == ["t1"]
        assert d["defaultInputModes"] == ["text"]
        assert d["defaultOutputModes"] == ["text"]

    def test_default_capabilities(self):
        card = AgentCard(name="test", description="test")
        assert card.capabilities["streaming"] is False
        assert card.capabilities["pushNotifications"] is False
