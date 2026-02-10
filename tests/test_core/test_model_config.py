"""Tests for model configuration and per-agent LLM setup."""

from typing import Any

from aise.agents import (
    ArchitectAgent,
    DeveloperAgent,
    ProductManagerAgent,
    QAEngineerAgent,
    TeamLeadAgent,
)
from aise.config import AgentConfig, ModelConfig, ProjectConfig
from aise.core.agent import Agent, AgentRole
from aise.core.artifact import Artifact, ArtifactStore, ArtifactType
from aise.core.llm import LLMClient
from aise.core.message import MessageBus
from aise.core.skill import Skill, SkillContext
from aise.main import create_team


class EchoSkill(Skill):
    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Echoes input and records model info"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        return Artifact(
            artifact_type=ArtifactType.REQUIREMENTS,
            content={
                "input": input_data,
                "has_model_config": context.model_config is not None,
                "has_llm_client": context.llm_client is not None,
                "provider": context.model_config.provider if context.model_config else None,
                "model": context.model_config.model if context.model_config else None,
            },
            producer="test",
        )


class TestModelConfig:
    def test_default_values(self):
        cfg = ModelConfig()
        assert cfg.provider == "openai"
        assert cfg.model == "gpt-4o"
        assert cfg.api_key == ""
        assert cfg.base_url == ""
        assert cfg.temperature == 0.7
        assert cfg.max_tokens == 4096

    def test_custom_values(self):
        cfg = ModelConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            api_key="sk-test",
            base_url="https://api.anthropic.com",
            temperature=0.3,
            max_tokens=8192,
        )
        assert cfg.provider == "anthropic"
        assert cfg.model == "claude-sonnet-4-20250514"
        assert cfg.api_key == "sk-test"
        assert cfg.max_tokens == 8192

    def test_extra_field(self):
        cfg = ModelConfig(extra={"top_p": 0.9, "seed": 42})
        assert cfg.extra["top_p"] == 0.9
        assert cfg.extra["seed"] == 42

    def test_equality(self):
        a = ModelConfig()
        b = ModelConfig()
        assert a == b
        c = ModelConfig(provider="anthropic")
        assert a != c


class TestAgentConfigWithModel:
    def test_default_model(self):
        cfg = AgentConfig(name="test")
        assert cfg.model == ModelConfig()

    def test_custom_model(self):
        mc = ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514")
        cfg = AgentConfig(name="test", model=mc)
        assert cfg.model.provider == "anthropic"


class TestProjectConfigModelResolution:
    def test_default_model_fallback(self):
        default = ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514")
        config = ProjectConfig(default_model=default)
        resolved = config.get_model_config("product_manager")
        assert resolved.provider == "anthropic"
        assert resolved.model == "claude-sonnet-4-20250514"

    def test_agent_specific_override(self):
        default = ModelConfig(provider="openai", model="gpt-4o")
        agent_model = ModelConfig(provider="anthropic", model="claude-opus-4-20250514")
        config = ProjectConfig(
            default_model=default,
            agents={
                "developer": AgentConfig(name="developer", model=agent_model),
                "architect": AgentConfig(name="architect"),
            },
        )
        assert config.get_model_config("developer").provider == "anthropic"
        assert config.get_model_config("architect").provider == "openai"

    def test_unknown_agent_returns_default(self):
        default = ModelConfig(provider="ollama", model="llama3")
        config = ProjectConfig(default_model=default)
        resolved = config.get_model_config("nonexistent")
        assert resolved.provider == "ollama"


class TestLLMClient:
    def test_creation(self):
        cfg = ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514")
        client = LLMClient(cfg)
        assert client.provider == "anthropic"
        assert client.model == "claude-sonnet-4-20250514"
        assert client.config is cfg

    def test_complete_returns_empty_string(self):
        client = LLMClient(ModelConfig())
        result = client.complete([{"role": "user", "content": "hello"}])
        assert result == ""

    def test_repr(self):
        client = LLMClient(ModelConfig(provider="openai", model="gpt-4o"))
        r = repr(client)
        assert "openai" in r
        assert "gpt-4o" in r


class TestAgentWithModelConfig:
    def test_agent_gets_default_config(self):
        bus = MessageBus()
        store = ArtifactStore()
        agent = Agent("test", AgentRole.DEVELOPER, bus, store)
        assert agent.model_config.provider == "openai"
        assert agent.llm_client is not None

    def test_agent_with_custom_config(self):
        bus = MessageBus()
        store = ArtifactStore()
        cfg = ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514")
        agent = Agent("test", AgentRole.DEVELOPER, bus, store, model_config=cfg)
        assert agent.model_config.provider == "anthropic"
        assert agent.llm_client.provider == "anthropic"

    def test_model_config_passed_to_skill_context(self):
        bus = MessageBus()
        store = ArtifactStore()
        cfg = ModelConfig(provider="anthropic", model="claude-opus-4-20250514")
        agent = Agent("test", AgentRole.DEVELOPER, bus, store, model_config=cfg)
        agent.register_skill(EchoSkill())

        artifact = agent.execute_skill("echo", {"x": 1})
        assert artifact.content["has_model_config"] is True
        assert artifact.content["has_llm_client"] is True
        assert artifact.content["provider"] == "anthropic"
        assert artifact.content["model"] == "claude-opus-4-20250514"

    def test_repr_includes_model(self):
        bus = MessageBus()
        store = ArtifactStore()
        cfg = ModelConfig(provider="ollama", model="llama3")
        agent = Agent("test", AgentRole.DEVELOPER, bus, store, model_config=cfg)
        r = repr(agent)
        assert "ollama/llama3" in r


class TestConcreteAgentsWithModelConfig:
    def _bus_store(self):
        bus = MessageBus()
        store = ArtifactStore()
        return bus, store

    def test_product_manager_accepts_config(self):
        bus, store = self._bus_store()
        cfg = ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514")
        agent = ProductManagerAgent(bus, store, model_config=cfg)
        assert agent.model_config.provider == "anthropic"

    def test_architect_accepts_config(self):
        bus, store = self._bus_store()
        cfg = ModelConfig(provider="ollama", model="codellama")
        agent = ArchitectAgent(bus, store, model_config=cfg)
        assert agent.model_config.provider == "ollama"

    def test_developer_accepts_config(self):
        bus, store = self._bus_store()
        cfg = ModelConfig(provider="openai", model="o1-preview")
        agent = DeveloperAgent(bus, store, model_config=cfg)
        assert agent.model_config.model == "o1-preview"

    def test_qa_engineer_accepts_config(self):
        bus, store = self._bus_store()
        cfg = ModelConfig(provider="google", model="gemini-pro")
        agent = QAEngineerAgent(bus, store, model_config=cfg)
        assert agent.model_config.provider == "google"

    def test_team_lead_accepts_config(self):
        bus, store = self._bus_store()
        cfg = ModelConfig(provider="mistral", model="mistral-large")
        agent = TeamLeadAgent(bus, store, model_config=cfg)
        assert agent.model_config.provider == "mistral"

    def test_backward_compatible_without_config(self):
        bus, store = self._bus_store()
        agent = ProductManagerAgent(bus, store)
        assert agent.model_config == ModelConfig()
        assert len(agent.skill_names) == 6


class TestCreateTeamWithModelConfig:
    def test_create_team_default(self):
        orchestrator = create_team()
        for agent in orchestrator.agents.values():
            assert agent.model_config == ModelConfig()

    def test_create_team_with_project_default(self):
        cfg = ProjectConfig(
            default_model=ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514"),
        )
        orchestrator = create_team(cfg)
        for agent in orchestrator.agents.values():
            assert agent.model_config.provider == "anthropic"

    def test_create_team_mixed_providers(self):
        cfg = ProjectConfig(
            default_model=ModelConfig(provider="openai", model="gpt-4o"),
            agents={
                "product_manager": AgentConfig(name="product_manager"),
                "architect": AgentConfig(
                    name="architect",
                    model=ModelConfig(provider="anthropic", model="claude-opus-4-20250514"),
                ),
                "developer": AgentConfig(
                    name="developer",
                    model=ModelConfig(provider="ollama", model="codellama"),
                ),
                "qa_engineer": AgentConfig(name="qa_engineer"),
                "team_lead": AgentConfig(name="team_lead"),
            },
        )
        orchestrator = create_team(cfg)
        agents = orchestrator.agents

        assert agents["product_manager"].model_config.provider == "openai"
        assert agents["architect"].model_config.provider == "anthropic"
        assert agents["developer"].model_config.provider == "ollama"
        assert agents["qa_engineer"].model_config.provider == "openai"
        assert agents["team_lead"].model_config.provider == "openai"
