"""Configuration management for the AISE system."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ModelConfig:
    """Configuration for an LLM provider and model.

    Each agent can have its own provider, model, and tuning parameters,
    allowing heterogeneous setups (e.g. GPT-4o for the architect,
    Claude for the developer, a local Ollama model for QA).
    """

    provider: str = "openai"
    model: str = "gpt-4o"
    api_key: str = ""
    base_url: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    extra: dict[str, object] = field(default_factory=dict)


@dataclass
class ModelOption:
    """A selectable model entry identified by a single model ID."""

    id: str
    is_default: bool = False


@dataclass
class ModelProvider:
    """Provider endpoint configuration for a model."""

    provider: str
    api_key: str = ""
    base_url: str = ""
    enabled: bool = True


@dataclass
class ModelDefinition:
    """Model definition with multi-provider failover support."""

    id: str
    name: str = ""
    api_model: str = ""
    providers: list[str] = field(default_factory=list)
    default_provider: str = ""
    is_default: bool = False
    is_local: bool = False
    extra: dict[str, object] = field(default_factory=dict)


@dataclass
class AgentConfig:
    """Configuration for an individual agent."""

    name: str
    enabled: bool = True
    model: ModelConfig = field(default_factory=ModelConfig)


@dataclass
class WorkflowConfig:
    """Configuration for workflow execution."""

    max_review_iterations: int = 3
    fail_on_review_rejection: bool = False


@dataclass
class GitHubConfig:
    """Configuration for GitHub integration.

    The team owner configures a personal access token so that all agents
    can interact with GitHub pull requests.  Role-based permissions
    restrict which operations each agent may perform.
    """

    token: str = ""
    repo_owner: str = ""
    repo_name: str = ""

    @property
    def is_configured(self) -> bool:
        return bool(self.token and self.repo_owner and self.repo_name)

    @property
    def repo_full_name(self) -> str:
        return f"{self.repo_owner}/{self.repo_name}"


@dataclass
class WhatsAppConfig:
    """Configuration for WhatsApp Business API integration."""

    phone_number_id: str = ""
    access_token: str = ""
    verify_token: str = ""
    business_account_id: str = ""
    webhook_port: int = 8080
    webhook_path: str = "/webhook"

    @property
    def is_configured(self) -> bool:
        return bool(self.phone_number_id and self.access_token)


@dataclass
class SessionConfig:
    """Configuration for concurrent development sessions."""

    max_concurrent_sessions: int = 5
    status_update_interval_minutes: int = 5
    stale_task_threshold_minutes: int = 10
    reviewer_poll_interval_seconds: int = 60


@dataclass
class WorkspaceConfig:
    """Configuration for workspace layout and persistence."""

    projects_root: str = "projects"
    artifacts_root: str = "artifacts"
    auto_create_dirs: bool = True


@dataclass
class LoggingConfig:
    """Configuration for logging system."""

    level: str = "INFO"
    log_dir: str = "logs"
    json_format: bool = False
    rotate_daily: bool = True


@dataclass
class ProjectConfig:
    """Top-level project configuration."""

    project_name: str = "Untitled Project"
    development_mode: str = "local"  # "local" or "github"
    default_model: ModelConfig = field(default_factory=ModelConfig)
    model_providers: list[ModelProvider] = field(default_factory=list)
    models: list[ModelDefinition] = field(default_factory=list)
    model_catalog: list[ModelOption] = field(
        default_factory=lambda: [ModelOption(id="openai:gpt-4o", is_default=True)]
    )
    agent_model_selection: dict[str, str] = field(default_factory=dict)
    agents: dict[str, AgentConfig] = field(
        default_factory=lambda: {
            "product_manager": AgentConfig(name="product_manager"),
            "architect": AgentConfig(name="architect"),
            "developer": AgentConfig(name="developer"),
            "qa_engineer": AgentConfig(name="qa_engineer"),
            "project_manager": AgentConfig(name="project_manager"),
            "rd_director": AgentConfig(name="rd_director"),
        }
    )
    agent_counts: dict[str, int] = field(default_factory=dict)
    workflow: WorkflowConfig = field(default_factory=WorkflowConfig)
    session: SessionConfig = field(default_factory=SessionConfig)
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    whatsapp: WhatsAppConfig = field(default_factory=WhatsAppConfig)
    github: GitHubConfig = field(default_factory=GitHubConfig)

    @property
    def is_github_mode(self) -> bool:
        """Check if project is in GitHub development mode.

        Returns True if:
        1. development_mode is explicitly set to "github", AND
        2. GitHub configuration is properly configured

        Returns:
            True if GitHub mode is enabled and configured
        """
        return self.development_mode == "github" and self.github.is_configured

    @property
    def is_local_mode(self) -> bool:
        """Check if project is in local development mode.

        Returns:
            True if development mode is "local" or GitHub is not configured
        """
        return self.development_mode == "local" or not self.github.is_configured

    def get_model_config(self, agent_name: str) -> ModelConfig:
        """Return the effective model config for an agent.

        Uses the agent-specific config if it was explicitly set (differs
        from defaults), otherwise falls back to the project-level default.
        """
        selected_model_id = self.agent_model_selection.get(agent_name, "").strip()
        if selected_model_id:
            chain = self.get_model_fallback_chain(selected_model_id)
            primary = chain[0] if chain else self.default_model
            if len(chain) > 1:
                primary.extra = {
                    **primary.extra,
                    "fallback_chain": [
                        {
                            "provider": cfg.provider,
                            "model": cfg.model,
                            "api_key": cfg.api_key,
                            "base_url": cfg.base_url,
                        }
                        for cfg in chain[1:]
                    ],
                }
            return primary

        agent_cfg = self.agents.get(agent_name)
        if agent_cfg is not None and agent_cfg.model != ModelConfig():
            return agent_cfg.model
        return self.default_model

    def get_default_model_id(self) -> str:
        """Return the default model ID from catalog or fallback from default_model."""
        if self.models:
            for item in self.models:
                if item.is_default:
                    return item.id
            return self.models[0].id
        for item in self.model_catalog:
            if item.is_default:
                return item.id
        return f"{self.default_model.provider}:{self.default_model.model}"

    def resolve_model_id(self, model_id: str) -> ModelConfig:
        """Resolve model ID (provider:model) to ModelConfig."""
        model_id = model_id.strip()
        if not model_id:
            return self.default_model

        for cfg in self.get_model_fallback_chain(model_id):
            return cfg

        return self._parse_provider_model_id(model_id)

    def _parse_provider_model_id(self, model_id: str) -> ModelConfig:
        """Parse legacy provider:model or provider/model ID."""
        provider = self.default_model.provider
        model = model_id

        if ":" in model_id:
            provider, model = model_id.split(":", 1)
        elif "/" in model_id:
            provider, model = model_id.split("/", 1)

        return ModelConfig(
            provider=provider.strip() or self.default_model.provider,
            model=model.strip() or self.default_model.model,
            api_key=self.default_model.api_key,
            base_url=self.default_model.base_url,
            temperature=self.default_model.temperature,
            max_tokens=self.default_model.max_tokens,
            extra=dict(self.default_model.extra),
        )

    def get_model_fallback_chain(self, model_id: str) -> list[ModelConfig]:
        """Return provider fallback chain for a model ID."""
        model_id = model_id.strip()
        if not model_id:
            return [self.default_model]

        definition = next((item for item in self.models if item.id == model_id), None)
        if definition is None:
            # Backward compatible with provider:model format.
            if ":" in model_id or "/" in model_id:
                return [self._parse_provider_model_id(model_id)]
            return [self.default_model]

        if definition.is_local:
            local_cfg = ModelConfig(
                provider="local",
                model=definition.api_model or definition.id,
                api_key="",
                base_url="",
                temperature=self.default_model.temperature,
                max_tokens=self.default_model.max_tokens,
                extra={
                    **self.default_model.extra,
                    **definition.extra,
                    "is_local_model": True,
                    "model_id": definition.id,
                    "model_name": definition.name or definition.id,
                },
            )
            return [local_cfg]

        provider_map = {item.provider: item for item in self.model_providers}
        refs = [ref for ref in definition.providers if ref in provider_map and provider_map[ref].enabled]
        providers = [provider_map[ref] for ref in refs]
        if not providers:
            return [self.default_model]

        ordered: list[ModelProvider] = []
        if definition.default_provider:
            primary = next((p for p in providers if p.provider == definition.default_provider), None)
            if primary is not None:
                ordered.append(primary)
        ordered.extend([p for p in providers if p not in ordered])

        chain = [
            ModelConfig(
                provider=item.provider,
                model=definition.api_model or definition.id,
                api_key=item.api_key,
                base_url=item.base_url,
                temperature=self.default_model.temperature,
                max_tokens=self.default_model.max_tokens,
                extra={
                    **self.default_model.extra,
                    **definition.extra,
                    "model_id": definition.id,
                    "model_name": definition.name or definition.id,
                },
            )
            for item in ordered
        ]
        return chain or [self.default_model]

    def ensure_model_catalog_defaults(self) -> None:
        """Ensure model defaults and keep model_catalog backward-compatible."""
        dedup_provider_map: dict[str, ModelProvider] = {}
        for item in self.model_providers:
            name = item.provider.strip()
            if not name:
                continue
            dedup_provider_map[name] = ModelProvider(
                provider=name,
                api_key=item.api_key,
                base_url=item.base_url,
                enabled=item.enabled,
            )
        self.model_providers = list(dedup_provider_map.values())

        if not self.model_providers and self.default_model.provider:
            self.model_providers = [
                ModelProvider(
                    provider=self.default_model.provider,
                    api_key=self.default_model.api_key,
                    base_url=self.default_model.base_url,
                    enabled=True,
                )
            ]

        if not self.models:
            if self.default_model != ModelConfig():
                self.models = [
                    ModelDefinition(
                        id=self.default_model.model,
                        name=self.default_model.model,
                        api_model=self.default_model.model,
                        providers=[self.default_model.provider],
                        default_provider=self.default_model.provider,
                        is_default=True,
                        is_local=(self.default_model.provider == "local"),
                    )
                ]
            elif self.model_catalog:
                parsed_models: list[ModelDefinition] = []
                for item in self.model_catalog:
                    model_id = item.id.strip()
                    if not model_id:
                        continue
                    if ":" in model_id:
                        provider, actual_id = model_id.split(":", 1)
                    elif "/" in model_id:
                        provider, actual_id = model_id.split("/", 1)
                    else:
                        provider, actual_id = self.default_model.provider, model_id
                    parsed_models.append(
                        ModelDefinition(
                            id=actual_id.strip(),
                            name=actual_id.strip(),
                            api_model=actual_id.strip(),
                            providers=[provider.strip() or self.default_model.provider],
                            default_provider=provider.strip() or self.default_model.provider,
                            is_default=item.is_default,
                            is_local=((provider.strip() or self.default_model.provider) == "local"),
                        )
                    )
                self.models = parsed_models

        if not self.models:
            self.models = [
                ModelDefinition(
                    id=self.default_model.model,
                    name=self.default_model.model,
                    api_model=self.default_model.model,
                    providers=[self.default_model.provider],
                    default_provider=self.default_model.provider,
                    is_default=True,
                    is_local=(self.default_model.provider == "local"),
                )
            ]

        if not any(item.is_default for item in self.models):
            self.models[0].is_default = True

        for model in self.models:
            if not model.providers:
                if not model.is_local:
                    model.providers = [self.default_model.provider]
            if not model.default_provider:
                if model.providers:
                    model.default_provider = model.providers[0]
                elif model.is_local:
                    model.default_provider = "local"
            if not model.name:
                model.name = model.id
            if not model.api_model:
                model.api_model = model.id

        default_entry = next((item for item in self.models if item.is_default), self.models[0])
        default_chain = self.get_model_fallback_chain(default_entry.id)
        if default_chain:
            self.default_model = default_chain[0]

        self.model_catalog = [
            ModelOption(id=item.id, is_default=item.is_default)
            for item in self.models
        ]

    def to_dict(self) -> dict[str, Any]:
        """Serialize project config to a JSON-compatible dictionary."""
        self.ensure_model_catalog_defaults()
        default_model_id = self.default_model.model
        dedup_catalog: list[ModelOption] = []
        seen_ids: set[str] = set()
        for item in self.model_catalog:
            model_id = item.id.strip()
            if not model_id or model_id in seen_ids:
                continue
            seen_ids.add(model_id)
            dedup_catalog.append(ModelOption(id=model_id, is_default=(model_id == default_model_id)))
        if default_model_id not in seen_ids:
            dedup_catalog.insert(0, ModelOption(id=default_model_id, is_default=True))

        return {
            "project_name": self.project_name,
            "development_mode": self.development_mode,
            "default_model": {
                "provider": self.default_model.provider,
                "model": self.default_model.model,
                "api_key": self.default_model.api_key,
                "base_url": self.default_model.base_url,
                "temperature": self.default_model.temperature,
                "max_tokens": self.default_model.max_tokens,
                "extra": self.default_model.extra,
            },
            "model_catalog": [
                {"id": item.id, "default": item.is_default} for item in dedup_catalog
            ],
            "models": [
                {
                    "id": model.id,
                    "name": model.name,
                    "api_model": model.api_model,
                    "default": model.is_default,
                    "default_provider": model.default_provider,
                    "is_local": model.is_local,
                    "providers": list(model.providers),
                    "extra": dict(model.extra),
                }
                for model in self.models
            ],
            "model_providers": [
                {
                    "provider": provider.provider,
                    "api_key": provider.api_key,
                    "base_url": provider.base_url,
                    "enabled": provider.enabled,
                }
                for provider in self.model_providers
            ],
            "agent_model_selection": dict(self.agent_model_selection),
            "agents": {
                name: {
                    "name": cfg.name,
                    "enabled": cfg.enabled,
                }
                for name, cfg in self.agents.items()
            },
            "agent_counts": self.agent_counts,
            "workflow": {
                "max_review_iterations": self.workflow.max_review_iterations,
                "fail_on_review_rejection": self.workflow.fail_on_review_rejection,
            },
            "session": {
                "max_concurrent_sessions": self.session.max_concurrent_sessions,
                "status_update_interval_minutes": self.session.status_update_interval_minutes,
                "stale_task_threshold_minutes": self.session.stale_task_threshold_minutes,
                "reviewer_poll_interval_seconds": self.session.reviewer_poll_interval_seconds,
            },
            "workspace": {
                "projects_root": self.workspace.projects_root,
                "artifacts_root": self.workspace.artifacts_root,
                "auto_create_dirs": self.workspace.auto_create_dirs,
            },
            "logging": {
                "level": self.logging.level,
                "log_dir": self.logging.log_dir,
                "json_format": self.logging.json_format,
                "rotate_daily": self.logging.rotate_daily,
            },
            "whatsapp": {
                "phone_number_id": self.whatsapp.phone_number_id,
                "access_token": self.whatsapp.access_token,
                "verify_token": self.whatsapp.verify_token,
                "business_account_id": self.whatsapp.business_account_id,
                "webhook_port": self.whatsapp.webhook_port,
                "webhook_path": self.whatsapp.webhook_path,
            },
            "github": {
                "token": self.github.token,
                "repo_owner": self.github.repo_owner,
                "repo_name": self.github.repo_name,
            },
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ProjectConfig:
        """Build project config from a dictionary."""
        config = cls()

        if "project_name" in data:
            config.project_name = str(data["project_name"])
        if "development_mode" in data:
            config.development_mode = str(data["development_mode"])

        model_data = data.get("default_model", {})
        if isinstance(model_data, dict):
            config.default_model = ModelConfig(
                provider=str(model_data.get("provider", config.default_model.provider)),
                model=str(model_data.get("model", config.default_model.model)),
                api_key=str(model_data.get("api_key", config.default_model.api_key)),
                base_url=str(model_data.get("base_url", config.default_model.base_url)),
                temperature=float(model_data.get("temperature", config.default_model.temperature)),
                max_tokens=int(model_data.get("max_tokens", config.default_model.max_tokens)),
                extra=dict(model_data.get("extra", config.default_model.extra)),
            )

        models_data = data.get("models", [])
        if isinstance(models_data, list):
            parsed_models: list[ModelDefinition] = []
            inline_provider_map: dict[str, ModelProvider] = {}
            for item in models_data:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id", "")).strip()
                if not model_id:
                    continue
                providers_data = item.get("providers", [])
                provider_refs: list[str] = []
                if isinstance(providers_data, list):
                    for provider_item in providers_data:
                        if isinstance(provider_item, str):
                            name = provider_item.strip()
                            if name:
                                provider_refs.append(name)
                            continue
                        if isinstance(provider_item, dict):
                            provider_name = str(provider_item.get("provider", "")).strip()
                            if not provider_name:
                                continue
                            provider_refs.append(provider_name)
                            inline_provider_map[provider_name] = ModelProvider(
                                provider=provider_name,
                                api_key=str(provider_item.get("api_key", "")),
                                base_url=str(provider_item.get("base_url", "")),
                                enabled=bool(provider_item.get("enabled", True)),
                            )
                parsed_models.append(
                    ModelDefinition(
                        id=model_id,
                        name=str(item.get("name", model_id)),
                        api_model=str(item.get("api_model", model_id)),
                        providers=provider_refs,
                        default_provider=str(item.get("default_provider", "")),
                        is_default=bool(item.get("default", False)),
                        is_local=bool(item.get("is_local", False)),
                        extra=dict(item.get("extra", {})) if isinstance(item.get("extra", {}), dict) else {},
                    )
                )
            if parsed_models:
                config.models = parsed_models
                if inline_provider_map:
                    config.model_providers = list(inline_provider_map.values())

        model_providers_data = data.get("model_providers", [])
        if isinstance(model_providers_data, list):
            parsed_provider_list: list[ModelProvider] = []
            for provider_item in model_providers_data:
                if not isinstance(provider_item, dict):
                    continue
                provider_name = str(provider_item.get("provider", "")).strip()
                if not provider_name:
                    continue
                parsed_provider_list.append(
                    ModelProvider(
                        provider=provider_name,
                        api_key=str(provider_item.get("api_key", "")),
                        base_url=str(provider_item.get("base_url", "")),
                        enabled=bool(provider_item.get("enabled", True)),
                    )
                )
            if parsed_provider_list:
                config.model_providers = parsed_provider_list

        catalog_data = data.get("model_catalog", [])
        catalog_loaded = False
        if isinstance(catalog_data, list):
            parsed_catalog: list[ModelOption] = []
            for item in catalog_data:
                if not isinstance(item, dict):
                    continue
                model_id = str(item.get("id", "")).strip()
                if not model_id:
                    continue
                parsed_catalog.append(ModelOption(id=model_id, is_default=bool(item.get("default", False))))
            if parsed_catalog:
                config.model_catalog = parsed_catalog
                catalog_loaded = True

        if not catalog_loaded:
            config.model_catalog = [
                ModelOption(
                    id=f"{config.default_model.provider}:{config.default_model.model}",
                    is_default=True,
                )
            ]

        selection_data = data.get("agent_model_selection", {})
        if isinstance(selection_data, dict):
            config.agent_model_selection = {
                str(agent): str(model_id) for agent, model_id in selection_data.items()
            }

        agents_data = data.get("agents", {})
        if isinstance(agents_data, dict):
            merged_agents = config.agents.copy()
            for agent_name, agent_cfg_data in agents_data.items():
                if not isinstance(agent_cfg_data, dict):
                    continue
                existing = merged_agents.get(agent_name, AgentConfig(name=agent_name))
                model_cfg_data = agent_cfg_data.get("model", {})
                if not isinstance(model_cfg_data, dict):
                    model_cfg_data = {}
                merged_agents[agent_name] = AgentConfig(
                    name=str(agent_cfg_data.get("name", existing.name)),
                    enabled=bool(agent_cfg_data.get("enabled", existing.enabled)),
                    model=ModelConfig(
                        provider=str(model_cfg_data.get("provider", existing.model.provider)),
                        model=str(model_cfg_data.get("model", existing.model.model)),
                        api_key=str(model_cfg_data.get("api_key", existing.model.api_key)),
                        base_url=str(model_cfg_data.get("base_url", existing.model.base_url)),
                        temperature=float(model_cfg_data.get("temperature", existing.model.temperature)),
                        max_tokens=int(model_cfg_data.get("max_tokens", existing.model.max_tokens)),
                        extra=dict(model_cfg_data.get("extra", existing.model.extra)),
                    ),
                )
            config.agents = merged_agents

        agent_counts = data.get("agent_counts", {})
        if isinstance(agent_counts, dict):
            config.agent_counts = {str(k): int(v) for k, v in agent_counts.items()}

        workflow_data = data.get("workflow", {})
        if isinstance(workflow_data, dict):
            config.workflow = WorkflowConfig(
                max_review_iterations=int(
                    workflow_data.get("max_review_iterations", config.workflow.max_review_iterations)
                ),
                fail_on_review_rejection=bool(
                    workflow_data.get("fail_on_review_rejection", config.workflow.fail_on_review_rejection)
                ),
            )

        session_data = data.get("session", {})
        if isinstance(session_data, dict):
            config.session = SessionConfig(
                max_concurrent_sessions=int(
                    session_data.get("max_concurrent_sessions", config.session.max_concurrent_sessions)
                ),
                status_update_interval_minutes=int(
                    session_data.get(
                        "status_update_interval_minutes",
                        config.session.status_update_interval_minutes,
                    )
                ),
                stale_task_threshold_minutes=int(
                    session_data.get("stale_task_threshold_minutes", config.session.stale_task_threshold_minutes)
                ),
                reviewer_poll_interval_seconds=int(
                    session_data.get(
                        "reviewer_poll_interval_seconds",
                        config.session.reviewer_poll_interval_seconds,
                    )
                ),
            )

        workspace_data = data.get("workspace", {})
        if isinstance(workspace_data, dict):
            config.workspace = WorkspaceConfig(
                projects_root=str(workspace_data.get("projects_root", config.workspace.projects_root)),
                artifacts_root=str(workspace_data.get("artifacts_root", config.workspace.artifacts_root)),
                auto_create_dirs=bool(workspace_data.get("auto_create_dirs", config.workspace.auto_create_dirs)),
            )

        logging_data = data.get("logging", {})
        if isinstance(logging_data, dict):
            config.logging = LoggingConfig(
                level=str(logging_data.get("level", config.logging.level)),
                log_dir=str(logging_data.get("log_dir", config.logging.log_dir)),
                json_format=bool(logging_data.get("json_format", config.logging.json_format)),
                rotate_daily=bool(logging_data.get("rotate_daily", config.logging.rotate_daily)),
            )

        whatsapp_data = data.get("whatsapp", {})
        if isinstance(whatsapp_data, dict):
            config.whatsapp = WhatsAppConfig(
                phone_number_id=str(whatsapp_data.get("phone_number_id", config.whatsapp.phone_number_id)),
                access_token=str(whatsapp_data.get("access_token", config.whatsapp.access_token)),
                verify_token=str(whatsapp_data.get("verify_token", config.whatsapp.verify_token)),
                business_account_id=str(whatsapp_data.get("business_account_id", config.whatsapp.business_account_id)),
                webhook_port=int(whatsapp_data.get("webhook_port", config.whatsapp.webhook_port)),
                webhook_path=str(whatsapp_data.get("webhook_path", config.whatsapp.webhook_path)),
            )

        github_data = data.get("github", {})
        if isinstance(github_data, dict):
            config.github = GitHubConfig(
                token=str(github_data.get("token", config.github.token)),
                repo_owner=str(github_data.get("repo_owner", config.github.repo_owner)),
                repo_name=str(github_data.get("repo_name", config.github.repo_name)),
            )

        config.ensure_model_catalog_defaults()

        return config

    @classmethod
    def from_json_file(cls, file_path: str | Path) -> ProjectConfig:
        """Load project config from a JSON file."""
        path = Path(file_path)
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Expected JSON object in {path}")
        return cls.from_dict(data)

    def to_json_file(self, file_path: str | Path) -> None:
        """Write project config to a JSON file."""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2)
