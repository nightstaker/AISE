"""Configuration management for the AISE system."""

from __future__ import annotations

from dataclasses import dataclass, field


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
            "team_lead": AgentConfig(name="team_lead"),
            "team_manager": AgentConfig(name="team_manager"),
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
