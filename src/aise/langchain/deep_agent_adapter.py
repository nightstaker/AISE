"""Adapters for building runtime agents with strict DeepAgents usage."""

from __future__ import annotations

import inspect
from typing import Any, Iterable

from langchain_core.messages import BaseMessage

from ..utils.logging import get_logger

logger = get_logger(__name__)

_CREATE_DEEP_AGENT = None
try:
    from deepagents import create_deep_agent as _CREATE_DEEP_AGENT  # type: ignore[assignment]
except Exception:
    _CREATE_DEEP_AGENT = None


def create_runtime_agent(
    llm: Any,
    tools: Iterable[Any],
    system_prompt: str,
) -> Any:
    """Build an agent runtime with DeepAgents only.

    Raises:
        RuntimeError: if DeepAgents is unavailable or cannot build the runtime.
    """
    return _create_deep_runtime(llm, list(tools), system_prompt)


def _create_deep_runtime(
    llm: Any,
    tools: list[Any],
    system_prompt: str,
) -> Any:
    """Try to construct a deep agent with signature-adaptive invocation."""
    if _CREATE_DEEP_AGENT is None:
        raise RuntimeError("DeepAgents is required but `deepagents.create_deep_agent` is not importable.")

    factory = _CREATE_DEEP_AGENT
    error: Exception | None = None

    # First attempt: map by parameter names to avoid API-version mismatch.
    try:
        kwargs = _map_deep_agent_kwargs(factory, llm=llm, tools=tools, system_prompt=system_prompt)
        candidate = factory(**kwargs)
        if hasattr(candidate, "invoke"):
            return candidate
        raise RuntimeError("DeepAgents runtime is invalid: missing invoke() method.")
    except Exception as exc:
        error = exc

    # Second attempt: positional calling for old/unknown signatures.
    try:
        candidate = factory(llm, tools, system_prompt)
        if hasattr(candidate, "invoke"):
            return candidate
    except Exception as exc:
        error = exc

    logger.error("Deep agent creation failed: error=%s", error)
    raise RuntimeError("DeepAgents runtime creation failed.") from error


def _map_deep_agent_kwargs(
    factory: Any,
    *,
    llm: Any,
    tools: list[Any],
    system_prompt: str,
) -> dict[str, Any]:
    sig = inspect.signature(factory)
    kwargs: dict[str, Any] = {}

    _set_first_matching(kwargs, sig.parameters, ("model", "llm", "chat_model"), llm)
    _set_first_matching(kwargs, sig.parameters, ("tools", "toolkit", "toolset"), tools)
    _set_first_matching(
        kwargs,
        sig.parameters,
        ("instructions", "system_prompt", "system", "prompt"),
        system_prompt,
    )

    # Some variants accept explicit message-history key names.
    if "message_key" in sig.parameters:
        kwargs["message_key"] = "messages"

    return kwargs


def _set_first_matching(
    kwargs: dict[str, Any],
    parameters: Any,
    candidate_names: tuple[str, ...],
    value: Any,
) -> None:
    for name in candidate_names:
        if name in parameters:
            kwargs[name] = value
            return


def extract_text_from_runtime_result(result: Any) -> str:
    """Extract plain text from common agent result shapes."""
    if isinstance(result, str):
        return result

    if hasattr(result, "content") and isinstance(result.content, str):
        return result.content

    if isinstance(result, dict):
        # Typical LangChain/deep-agent result: {"messages": [...]}
        messages = result.get("messages")
        if isinstance(messages, list):
            for msg in reversed(messages):
                if hasattr(msg, "content") and isinstance(msg.content, str):
                    return msg.content
                if isinstance(msg, BaseMessage):
                    return str(msg.content)
                if isinstance(msg, dict) and isinstance(msg.get("content"), str):
                    return msg["content"]
        # Generic text payload keys
        for key in ("output_text", "output", "text", "content", "response"):
            value = result.get(key)
            if isinstance(value, str):
                return value

    return str(result)
