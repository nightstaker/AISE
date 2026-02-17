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
class ProjectConfig:
    """Top-level project configuration."""

    project_name: str = "Untitled Project"
    development_mode: str = "local"  # "local" or "github"
    default_model: ModelConfig = field(default_factory=ModelConfig)
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
        agent_cfg = self.agents.get(agent_name)
        if agent_cfg is not None and agent_cfg.model != ModelConfig():
            return agent_cfg.model
        return self.default_model

    def to_dict(self) -> dict[str, Any]:
        """Serialize project config to a JSON-compatible dictionary."""
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
            "agents": {
                name: {
                    "name": cfg.name,
                    "enabled": cfg.enabled,
                    "model": {
                        "provider": cfg.model.provider,
                        "model": cfg.model.model,
                        "api_key": cfg.model.api_key,
                        "base_url": cfg.model.base_url,
                        "temperature": cfg.model.temperature,
                        "max_tokens": cfg.model.max_tokens,
                        "extra": cfg.model.extra,
                    },
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
