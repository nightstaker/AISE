"""Provider-agnostic LLM factory.

Centralizes the construction of a LangChain ``BaseChatModel`` from a
:class:`aise.config.ModelConfig`. New providers register a builder
function under their provider name; the default registration covers
``openai`` (and ``local``, which is OpenAI-compatible with a custom
base_url).

Adding a new provider should not require touching the runtime code:
call :func:`register_provider` from a plugin module.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any
from urllib.parse import urlparse

from langchain_core.language_models import BaseChatModel

from ..config import ModelConfig
from .runtime_config import LLMDefaults

ProviderBuilder = Callable[[ModelConfig, LLMDefaults], BaseChatModel]

_REGISTRY: dict[str, ProviderBuilder] = {}


def register_provider(name: str, builder: ProviderBuilder) -> None:
    """Register a provider builder under the given name (lowercased)."""
    _REGISTRY[name.strip().lower()] = builder


def build_llm(config: ModelConfig, defaults: LLMDefaults | None = None) -> BaseChatModel:
    """Build a chat model instance from a ModelConfig.

    Resolution order:
    1. The provider name in ``config.provider`` (case-insensitive).
    2. ``"local"`` if the model is flagged or the base_url points at localhost.
    3. ``"openai"`` as the final fallback (OpenAI-compatible API).
    """
    defaults = defaults or LLMDefaults()
    provider_key = (config.provider or "").strip().lower()

    if provider_key in _REGISTRY:
        return _REGISTRY[provider_key](config, defaults)

    is_local_flag = bool(config.extra.get("is_local_model"))
    if provider_key == "local" or is_local_flag or _is_local_base_url(config.base_url):
        return _REGISTRY["local"](config, defaults)

    return _REGISTRY["openai"](config, defaults)


def _is_local_base_url(base_url: str) -> bool:
    if not base_url:
        return False
    try:
        parsed = urlparse(base_url)
    except Exception:
        return False
    host = (parsed.hostname or "").lower()
    return host in {"localhost", "127.0.0.1", "::1"}


# -- Built-in providers ----------------------------------------------------


def _build_openai(config: ModelConfig, defaults: LLMDefaults) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    effective_max_tokens = max(config.max_tokens, defaults.min_max_tokens)
    kwargs: dict[str, Any] = {
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": effective_max_tokens,
        "max_retries": defaults.max_retries,
    }

    api_key = config.api_key or os.environ.get("OPENAI_API_KEY", "")
    if api_key:
        kwargs["api_key"] = api_key
    if config.base_url:
        kwargs["base_url"] = config.base_url

    return ChatOpenAI(**kwargs)


def _build_local(config: ModelConfig, defaults: LLMDefaults) -> BaseChatModel:
    """Local OpenAI-compatible endpoint (vLLM/Ollama/LM Studio/etc.)."""
    from langchain_openai import ChatOpenAI

    effective_max_tokens = max(config.max_tokens, defaults.min_max_tokens)
    kwargs: dict[str, Any] = {
        "model": config.model,
        "temperature": config.temperature,
        "max_tokens": effective_max_tokens,
        "max_retries": defaults.max_retries,
    }

    api_key = config.api_key or os.environ.get("AISE_LOCAL_OPENAI_API_KEY") or "local-no-key-required"
    kwargs["api_key"] = api_key
    if config.base_url:
        kwargs["base_url"] = config.base_url

    return ChatOpenAI(**kwargs)


register_provider("openai", _build_openai)
register_provider("local", _build_local)
