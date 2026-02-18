"""LLM client abstraction for provider-agnostic model access."""

from __future__ import annotations

from typing import Any

from ..config import ModelConfig
from ..utils.logging import format_inference_result, get_logger

logger = get_logger(__name__)


class LLMClient:
    """Thin wrapper that normalises access to different LLM providers.

    This is intentionally *not* tied to any SDK so the core framework
    stays dependency-free.  Concrete provider integrations can subclass
    this or be injected via a factory.

    The base implementation stores the resolved :class:`ModelConfig` and
    exposes a :meth:`complete` method that subclasses override to call
    the real API.
    """

    def __init__(self, config: ModelConfig) -> None:
        self.config = config

    @property
    def provider(self) -> str:
        return self.config.provider

    @property
    def model(self) -> str:
        return self.config.model

    def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """Send a chat-completion request and return the assistant text.

        Override in subclasses to call the real provider API.  The base
        implementation returns a placeholder so the deterministic skills
        keep working without an API key.
        """
        logger.debug(
            "Inference request: provider=%s model=%s messages=%d extra_keys=%s",
            self.provider,
            self.model,
            len(messages),
            sorted(kwargs.keys()),
        )
        result = ""
        logger.info(
            "Inference response: provider=%s model=%s result=%s",
            self.provider,
            self.model,
            format_inference_result(result),
        )
        return result

    def __repr__(self) -> str:
        return f"LLMClient(provider={self.config.provider!r}, model={self.config.model!r})"
