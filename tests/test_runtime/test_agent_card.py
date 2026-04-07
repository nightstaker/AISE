"""Tests for A2A agent card generation."""

import json

from aise.runtime.agent_card import agent_card_from_dict, agent_card_to_json, build_agent_card
from aise.runtime.models import AgentDefinition, ProviderInfo, SkillInfo


class TestBuildAgentCard:
    def test_basic_card(self):
        defn = AgentDefinition(
            name="TestAgent",
            description="A test agent",
            version="1.0.0",
            skills=[SkillInfo(id="s1", name="Skill1", description="First")],
        )
        card = build_agent_card(defn, url="http://localhost:8080")
        assert card.name == "TestAgent"
        assert card.url == "http://localhost:8080"
        assert len(card.skills) == 1
        assert card.capabilities["streaming"] is False

    def test_capabilities_override(self):
        defn = AgentDefinition(
            name="StreamAgent",
            description="Streaming agent",
            capabilities={"streaming": True},
        )
        card = build_agent_card(defn)
        assert card.capabilities["streaming"] is True
        assert card.capabilities["pushNotifications"] is False

    def test_extra_skills_merged(self):
        defn = AgentDefinition(
            name="Test",
            description="Test",
            skills=[SkillInfo(id="s1", name="S1", description="First")],
        )
        extra = [
            SkillInfo(id="s2", name="S2", description="Second"),
            SkillInfo(id="s1", name="S1 Duplicate", description="Should not duplicate"),
        ]
        card = build_agent_card(defn, extra_skills=extra)
        assert len(card.skills) == 2
        skill_ids = [s.id for s in card.skills]
        assert "s1" in skill_ids
        assert "s2" in skill_ids

    def test_provider_info(self):
        defn = AgentDefinition(
            name="Test",
            description="Test",
            provider=ProviderInfo(organization="MyOrg", url="https://myorg.com"),
        )
        card = build_agent_card(defn)
        assert card.provider.organization == "MyOrg"


class TestAgentCardSerialization:
    def test_to_json(self):
        defn = AgentDefinition(
            name="JsonAgent",
            description="JSON test",
            skills=[SkillInfo(id="s1", name="S1", description="First", tags=["t1"])],
        )
        card = build_agent_card(defn)
        json_str = agent_card_to_json(card)
        data = json.loads(json_str)
        assert data["name"] == "JsonAgent"
        assert data["skills"][0]["tags"] == ["t1"]

    def test_roundtrip(self):
        defn = AgentDefinition(
            name="RoundTrip",
            description="Roundtrip test",
            version="3.0.0",
            provider=ProviderInfo(organization="Org", url="https://org.com"),
            skills=[SkillInfo(id="x", name="X", description="Skill X", tags=["a"], examples=["ex1"])],
        )
        card = build_agent_card(defn)
        json_str = agent_card_to_json(card)
        restored = agent_card_from_dict(json.loads(json_str))
        assert restored.name == "RoundTrip"
        assert restored.version == "3.0.0"
        assert restored.provider.organization == "Org"
        assert len(restored.skills) == 1
        assert restored.skills[0].examples == ["ex1"]
