"""Tests for model configuration and per-agent LLM setup."""

from typing import Any

from aise.agents import (
    ArchitectAgent,
    DeveloperAgent,
    ProductManagerAgent,
    ProjectManagerAgent,
    QAEngineerAgent,
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

    def test_project_config_json_round_trip(self, tmp_path):
        config = ProjectConfig(project_name="RoundTrip")
        config.default_model = ModelConfig(provider="anthropic", model="claude-opus-4")
        config.workflow.max_review_iterations = 7
        config.github.repo_owner = "acme"
        config.github.repo_name = "platform"

        file_path = tmp_path / "project_config.json"
        config.to_json_file(file_path)
        loaded = ProjectConfig.from_json_file(file_path)

        assert loaded.project_name == "RoundTrip"
        assert loaded.default_model.provider == "anthropic"
        assert loaded.workflow.max_review_iterations == 7
        assert loaded.github.repo_full_name == "acme/platform"

    def test_model_catalog_default_and_agent_selection(self):
        config = ProjectConfig.from_dict(
            {
                "default_model": {"provider": "openai", "model": "gpt-4o"},
                "model_catalog": [
                    {"id": "openai:gpt-4.1", "default": True},
                    {"id": "anthropic:claude-sonnet-4-20250514", "default": False},
                ],
                "agent_model_selection": {
                    "architect": "anthropic:claude-sonnet-4-20250514",
                },
            }
        )

        assert config.get_default_model_id() == "gpt-4.1"
        assert config.default_model.provider == "openai"
        assert config.default_model.model == "gpt-4.1"

        resolved = config.get_model_config("architect")
        assert resolved.provider == "anthropic"
        assert resolved.model == "claude-sonnet-4-20250514"

    def test_model_catalog_backward_compatible_without_catalog(self):
        config = ProjectConfig.from_dict(
            {
                "default_model": {"provider": "anthropic", "model": "claude-opus-4"},
            }
        )

        assert config.get_default_model_id() == "claude-opus-4"
        assert len(config.model_catalog) == 1
        assert config.model_catalog[0].is_default is True

    def test_to_dict_removes_legacy_agent_model_block(self):
        config = ProjectConfig()
        data = config.to_dict()
        assert "agents" in data
        first_agent = data["agents"]["product_manager"]
        assert "model" not in first_agent

    def test_models_support_name_api_model_and_local_flag(self):
        config = ProjectConfig.from_dict(
            {
                "model_providers": [{"provider": "openai", "api_key": "", "base_url": "", "enabled": True}],
                "models": [
                    {
                        "id": "gpt-4o",
                        "name": "GPT-4o",
                        "api_model": "gpt-4o",
                        "default": True,
                        "default_provider": "openai",
                        "providers": ["openai"],
                        "is_local": False,
                    },
                    {
                        "id": "qwen2.5-coder:7b",
                        "name": "Qwen2.5 Coder 7B",
                        "api_model": "qwen2.5-coder:7b",
                        "default": False,
                        "default_provider": "local",
                        "providers": [],
                        "is_local": True,
                    },
                ],
                "agent_model_selection": {"developer": "qwen2.5-coder:7b"},
            }
        )
        resolved = config.get_model_config("developer")
        assert resolved.provider == "local"
        assert resolved.model == "qwen2.5-coder:7b"
        assert resolved.extra.get("is_local_model") is True


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

    def test_complete_uses_openai_compatible_path_for_any_provider(self, monkeypatch):
        client = LLMClient(ModelConfig(provider="anthropic", model="claude-sonnet-4-20250514"))

        def fake_complete(_messages, **_kwargs):
            return "ok"

        monkeypatch.setattr(client, "_complete_openai_compatible", fake_complete)
        result = client.complete([{"role": "user", "content": "hello"}])
        assert result == "ok"

    def test_extract_response_text_from_sdk_like_object(self):
        client = LLMClient(ModelConfig())

        class Part:
            def __init__(self, text: str):
                self.text = text

        class Item:
            def __init__(self, content):
                self.content = content

        class Response:
            def __init__(self):
                self.output = [Item([Part("hello "), Part("world")])]

        result = client._extract_response_text(Response())
        assert result == "hello world"

    def test_complete_filters_unsupported_extra_kwargs(self):
        cfg = ModelConfig(
            provider="OpenRouter",
            model="moonshotai/kimi-k2.5",
            api_key="sk-test",
            base_url="https://example.com/v1",
            extra={"model_id": "gpt-4o", "model_name": "TestModel"},
        )
        client = LLMClient(cfg)

        class _Message:
            content = "ok"

        class _Choice:
            message = _Message()

        class _Response:
            choices = [_Choice()]

        class _Completions:
            def create(self, **kwargs):
                if "model_id" in kwargs:
                    raise TypeError("Completions.create() got an unexpected keyword argument 'model_id'")
                if "model_name" in kwargs:
                    raise TypeError("Completions.create() got an unexpected keyword argument 'model_name'")
                return _Response()

        class _Chat:
            completions = _Completions()

        class _Client:
            chat = _Chat()

            class responses:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("force fallback to chat")

        client._build_openai_client = lambda: _Client()  # type: ignore[method-assign]

        result = client.complete([{"role": "user", "content": "hello"}])
        assert result == "ok"

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

    def test_project_manager_accepts_config(self):
        bus, store = self._bus_store()
        cfg = ModelConfig(provider="mistral", model="mistral-large")
        agent = ProjectManagerAgent(bus, store, model_config=cfg)
        assert agent.model_config.provider == "mistral"

    def test_backward_compatible_without_config(self):
        bus, store = self._bus_store()
        agent = ProductManagerAgent(bus, store)
        assert agent.model_config == ModelConfig()
        # 9 skills: 6 original + 3 new (system_feature_analysis, system_requirement_analysis, document_generation)
        assert len(agent.skill_names) == 9


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
                "project_manager": AgentConfig(name="project_manager"),
            },
        )
        orchestrator = create_team(cfg)
        agents = orchestrator.agents

        assert agents["product_manager"].model_config.provider == "openai"
        assert agents["architect"].model_config.provider == "anthropic"
        assert agents["developer"].model_config.provider == "ollama"
        assert agents["qa_engineer"].model_config.provider == "openai"
        assert agents["project_manager"].model_config.provider == "openai"
