"""LLM client abstraction for provider-agnostic model access."""

from __future__ import annotations

import os
import re
from typing import Any, Iterator

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
        result = self._complete_openai_compatible(messages, **kwargs)
        logger.info(
            "Inference response: provider=%s model=%s result=%s",
            self.provider,
            self.model,
            format_inference_result(result),
        )
        return result

    def stream(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> Iterator[str]:
        """Send a streaming request and yield text chunks."""
        client = self._build_openai_client()
        if client is None:
            return

        payload = self._build_common_payload(messages, **kwargs)
        try:
            stream = client.responses.create(stream=True, **payload)
            for event in stream:
                delta = self._extract_event_text(event)
                if delta:
                    yield delta
            return
        except Exception:
            pass

        chat_payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": str(m.get("role", "user")), "content": str(m.get("content", ""))} for m in messages],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if "tools" in kwargs:
            chat_payload["tools"] = kwargs["tools"]
        chat_payload.update(self.config.extra)
        for chunk in client.chat.completions.create(stream=True, **chat_payload):
            choices = getattr(chunk, "choices", None) or []
            for choice in choices:
                delta = getattr(choice, "delta", None)
                content = getattr(delta, "content", "") if delta is not None else ""
                if content:
                    yield str(content)

    def _complete_openai_compatible(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        client = self._build_openai_client()
        if client is None:
            return ""
        try:
            if bool(kwargs.pop("stream", False)):
                return self._complete_with_stream(client, messages, **kwargs)
            return self._complete_with_responses(client, messages, **kwargs)
        except Exception as exc:
            logger.warning("LLM request failed: provider=%s model=%s error=%s", self.provider, self.model, exc)
            return ""

    def _build_openai_client(self):
        api_key = self.config.api_key or os.environ.get("OPENAI_API_KEY", "")
        if not api_key:
            return None

        try:
            from openai import OpenAI
        except Exception as exc:
            logger.warning("OpenAI SDK unavailable: error=%s", exc)
            return None

        base_url = (self.config.base_url or "https://api.openai.com/v1").rstrip("/")
        return OpenAI(
            api_key=api_key,
            base_url=base_url,
        )

    def _complete_with_responses(self, client, messages: list[dict[str, str]], **kwargs: Any) -> str:
        payload: dict[str, Any] = self._build_common_payload(messages, **kwargs)
        try:
            response = self._call_with_filtered_kwargs(client.responses.create, payload)
            text = self._extract_response_text(response)
            if text:
                return text
        except Exception:
            pass
        return self._complete_with_chat_completions(client, messages, **kwargs)

    def _complete_with_stream(self, client, messages: list[dict[str, str]], **kwargs: Any) -> str:
        payload: dict[str, Any] = self._build_common_payload(messages, **kwargs)
        chunks: list[str] = []
        try:
            stream = self._call_with_filtered_kwargs(client.responses.create, payload, stream=True)
            for event in stream:
                delta = self._extract_event_text(event)
                if delta:
                    chunks.append(delta)
            text = "".join(chunks).strip()
            if text:
                return text
        except Exception:
            pass
        return self._complete_with_chat_completions(client, messages, stream=True, **kwargs)

    def _complete_with_chat_completions(
        self,
        client,
        messages: list[dict[str, str]],
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> str:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": str(m.get("role", "user")), "content": str(m.get("content", ""))} for m in messages],
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_tokens,
        }
        if "tools" in kwargs:
            payload["tools"] = kwargs["tools"]
        payload.update(self.config.extra)
        if stream:
            chunks: list[str] = []
            stream_obj = self._call_with_filtered_kwargs(client.chat.completions.create, payload, stream=True)
            for chunk in stream_obj:
                choices = getattr(chunk, "choices", None) or []
                for choice in choices:
                    delta = getattr(choice, "delta", None)
                    content = getattr(delta, "content", "") if delta is not None else ""
                    if content:
                        chunks.append(str(content))
            return "".join(chunks).strip()

        response = self._call_with_filtered_kwargs(client.chat.completions.create, payload)
        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", "") if message is not None else ""
        return str(content).strip()

    def _build_common_payload(self, messages: list[dict[str, str]], **kwargs: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.model,
            "input": self._to_responses_input(messages),
            "temperature": self.config.temperature,
            "max_output_tokens": self.config.max_tokens,
        }
        if "tools" in kwargs:
            payload["tools"] = kwargs["tools"]
        if "response_format" in kwargs:
            payload["response_format"] = kwargs["response_format"]
        payload.update(self.config.extra)
        return payload

    def _to_responses_input(self, messages: list[dict[str, str]]) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        for msg in messages:
            role = str(msg.get("role", "user"))
            content = str(msg.get("content", ""))
            result.append({"role": role, "content": [{"type": "input_text", "text": content}]})
        return result

    def _extract_response_text(self, response: Any) -> str:
        direct = getattr(response, "output_text", None)
        if isinstance(direct, str):
            return direct

        # SDK object path
        output = getattr(response, "output", None)
        if output is None and isinstance(response, dict):
            output = response.get("output", [])
        if not isinstance(output, list):
            return ""
        chunks: list[str] = []
        for item in output:
            content = getattr(item, "content", None)
            if content is None and isinstance(item, dict):
                content = item.get("content", [])
            if not isinstance(content, list):
                continue
            for part in content:
                text = getattr(part, "text", None)
                if text is None and isinstance(part, dict):
                    text = part.get("text")
                if isinstance(text, str):
                    chunks.append(text)
        return "".join(chunks).strip()

    def _extract_event_text(self, event: Any) -> str:
        event_type = getattr(event, "type", None)
        if isinstance(event, dict):
            event_type = event.get("type", event_type)

        if event_type in {"response.output_text.delta", "response.content_part.added"}:
            delta = getattr(event, "delta", None)
            if delta is None and isinstance(event, dict):
                delta = event.get("delta")
            if isinstance(delta, str):
                return delta
            if isinstance(delta, dict):
                text = delta.get("text")
                if isinstance(text, str):
                    return text
        return ""

    def _call_with_filtered_kwargs(self, call, payload: dict[str, Any], **extra_kwargs: Any):
        request_kwargs = dict(payload)
        request_kwargs.update(extra_kwargs)
        while True:
            try:
                return call(**request_kwargs)
            except TypeError as exc:
                match = self._UNEXPECTED_KWARG_RE.search(str(exc))
                if not match:
                    raise
                bad_key = match.group(1)
                if bad_key not in request_kwargs:
                    raise
                request_kwargs.pop(bad_key, None)
                logger.debug(
                    "Dropped unsupported LLM request kwarg: provider=%s model=%s key=%s",
                    self.provider,
                    self.model,
                    bad_key,
                )

    def __repr__(self) -> str:
        return f"LLMClient(provider={self.config.provider!r}, model={self.config.model!r})"
    _UNEXPECTED_KWARG_RE = re.compile(r"unexpected keyword argument '([^']+)'")
