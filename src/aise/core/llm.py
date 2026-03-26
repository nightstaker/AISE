"""LLM client abstraction for provider-agnostic model access."""

from __future__ import annotations

import os
import random
import re
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlparse
from uuid import uuid4

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
        self._call_context: dict[str, Any] = {}
        self._active_call_id: str = ""
        self._last_response_meta: dict[str, Any] = {}

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
        call_id = uuid4().hex
        self._active_call_id = call_id
        self._last_response_meta = {}
        started_at = datetime.now()
        purpose = str(kwargs.get("llm_purpose", "")).strip() or self._derive_call_purpose()
        trace_meta = self._build_trace_meta(
            call_id=call_id,
            started_at=started_at,
            purpose=purpose,
            messages=messages,
            kwargs=kwargs,
        )
        logger.info(
            "LLM call started: call_id=%s provider=%s model=%s purpose=%s agent=%s skill=%s",
            call_id,
            self.provider,
            self.model,
            purpose,
            str(self._call_context.get("agent", "")),
            str(self._call_context.get("skill", "")),
        )
        logger.debug(
            "Inference request: provider=%s model=%s messages=%d extra_keys=%s",
            self.provider,
            self.model,
            len(messages),
            sorted(kwargs.keys()),
        )
        try:
            result, attempts = self._complete_with_provider_failover(messages, **kwargs)
            self._write_trace_file(
                trace_meta
                | {
                    "output": result,
                    "attempts": attempts,
                    "provider_response_meta": self._safe_json(self._last_response_meta),
                }
            )
            logger.info(
                "Inference response: call_id=%s provider=%s model=%s result=%s",
                call_id,
                self.provider,
                self.model,
                format_inference_result(result),
            )
            logger.info(
                "LLM call completed: call_id=%s provider=%s model=%s",
                call_id,
                self.provider,
                self.model,
            )
            return result
        except Exception as exc:
            self._write_trace_file(
                trace_meta
                | {
                    "output": "",
                    "error": {"type": type(exc).__name__, "message": str(exc)},
                    "provider_response_meta": self._safe_json(self._last_response_meta),
                }
            )
            raise
        finally:
            self._active_call_id = ""

    def set_call_context(self, context: dict[str, Any]) -> None:
        self._call_context = dict(context)

    def clear_call_context(self) -> None:
        self._call_context = {}

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
            stream = client.responses.create(
                stream=True,
                timeout=self._resolve_stream_event_timeout_seconds(),
                **payload,
            )
            for event in stream:
                delta = self._extract_event_text(event)
                if delta:
                    yield delta
            return
        except Exception:
            logger.debug(
                "Responses streaming API failed in stream(): provider=%s model=%s",
                self.provider,
                self.model,
                exc_info=True,
            )
            raise

    def _complete_openai_compatible(self, messages: list[dict[str, str]], **kwargs: Any) -> str:
        client = self._build_openai_client()
        if client is None:
            raise RuntimeError(
                f"LLM client unavailable for provider={self.provider} model={self.model}: missing API key or SDK"
            )
        if bool(kwargs.pop("stream", False)):
            return self._complete_with_stream(client, messages, **kwargs)
        return self._complete_with_stream(client, messages, **kwargs)

    def _complete_with_provider_failover(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> tuple[str, list[dict[str, Any]]]:
        original_config = self.config
        attempts: list[dict[str, Any]] = []
        provider_chain = self._provider_chain()
        last_error: Exception | None = None
        max_attempts_per_provider = 3  # 1 initial + 2 retries

        for cfg_index, cfg in enumerate(provider_chain, start=1):
            self.config = cfg
            for attempt_index in range(1, max_attempts_per_provider + 1):
                try:
                    attempt_client = self._build_attempt_client(cfg)
                    result = attempt_client._complete_openai_compatible(messages, **dict(kwargs))
                    response_meta = dict(attempt_client._last_response_meta or {})
                    self._last_response_meta = dict(response_meta or {})
                    if not result.strip():
                        raise RuntimeError("Empty response from LLM provider")
                    attempts.append(
                        {
                            "provider": cfg.provider,
                            "model": cfg.model,
                            "base_url": cfg.base_url,
                            "provider_index": cfg_index,
                            "attempt": attempt_index,
                            "status": "success",
                        }
                    )
                    self.config = original_config
                    return result, attempts
                except Exception as exc:
                    details = self._extract_exception_details(exc)
                    attempts.append(
                        {
                            "provider": cfg.provider,
                            "model": cfg.model,
                            "base_url": cfg.base_url,
                            "provider_index": cfg_index,
                            "attempt": attempt_index,
                            "status": "failed",
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        }
                    )
                    logger.warning(
                        (
                            "LLM request failed: call_id=%s provider=%s model=%s "
                            "base_url=%s provider_index=%d attempt=%d/%d "
                            "error_type=%s error=%s details=%s"
                        ),
                        self._active_call_id,
                        cfg.provider,
                        cfg.model,
                        (cfg.base_url or "https://api.openai.com/v1"),
                        cfg_index,
                        attempt_index,
                        max_attempts_per_provider,
                        type(exc).__name__,
                        str(exc),
                        details,
                        exc_info=self._should_log_retry_traceback(exc, attempt_index, max_attempts_per_provider),
                    )
                    last_error = exc

                    # Apply exponential backoff with jitter before retrying
                    if attempt_index < max_attempts_per_provider:
                        delay = self._calculate_backoff_delay(attempt_index)
                        logger.debug(
                            "LLM retry backoff: call_id=%s sleeping=%.2fs (attempt %d/%d)",
                            self._active_call_id,
                            delay,
                            attempt_index,
                            max_attempts_per_provider,
                        )
                        time.sleep(delay)

            if cfg_index < len(provider_chain):
                logger.warning(
                    "Switching LLM provider after retries exhausted: call_id=%s from=%s/%s to=%s/%s",
                    self._active_call_id,
                    cfg.provider,
                    cfg.model,
                    provider_chain[cfg_index].provider,
                    provider_chain[cfg_index].model,
                )

        self.config = original_config
        if last_error is not None:
            raise RuntimeError(
                f"All LLM providers failed for model={original_config.model} provider={original_config.provider}"
            ) from last_error
        raise RuntimeError("All LLM providers failed with unknown errors")


    def _calculate_backoff_delay(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter.

        Uses exponential backoff: delay = base_delay * 2^(attempt-1) + random jitter
        Jitter is uniform random between 0 and 0.1 * calculated_delay to prevent thundering herd.

        Args:
            attempt: Current attempt number (1-indexed)

        Returns:
            Delay in seconds to wait before retry
        """
        base_delay = 1.0  # seconds
        max_delay = 30.0  # seconds

        # Exponential backoff: 1s, 2s, 4s, 8s, ...
        exponential_delay = base_delay * (2 ** (attempt - 1))
        # Cap at max_delay
        capped_delay = min(exponential_delay, max_delay)
        # Add jitter (0-10% of delay) to prevent thundering herd
        jitter = random.uniform(0, capped_delay * 0.1)
        return capped_delay + jitter

    def _is_transient_error(self, exc: Exception) -> bool:
        """Check if an error is likely transient and worth retrying."""
        error_type = type(exc).__name__.lower()
        error_msg = str(exc).lower()

        transient_types = {
            "connectionerror", "connectionreseterror", "connecttimeout",
            "readtimeout", "timeouterror", "temporaryfailure"
        }
        if error_type in transient_types:
            return True

        transient_patterns = {
            "connection error", "timed out", "connection reset",
            "network is unreachable", "temporary failure", "try again later",
            "rate limit", "too many requests", "quota exceeded"
        }
        return any(pattern in error_msg for pattern in transient_patterns)

    def _build_attempt_client(self, cfg: ModelConfig) -> LLMClient:
        attempt_client = self.__class__(cfg)
        attempt_client.set_call_context(dict(self._call_context))
        attempt_client._active_call_id = self._active_call_id
        # Preserve instance-level monkeypatches/hooks (commonly used in unit tests and
        # local overrides) when provider failover spawns a per-attempt client.
        for attr_name in ("_complete_openai_compatible", "_build_openai_client", "_provider_chain"):
            if attr_name in self.__dict__:
                setattr(attempt_client, attr_name, self.__dict__[attr_name])
        return attempt_client

    def _provider_chain(self) -> list[ModelConfig]:
        chain = [self.config]
        raw_chain = self.config.extra.get("fallback_chain")
        if not isinstance(raw_chain, list):
            return chain

        for item in raw_chain:
            if not isinstance(item, dict):
                continue
            provider = str(item.get("provider", "")).strip()
            model = str(item.get("model", "")).strip()
            if not provider or not model:
                continue
            extra_without_chain = {k: v for k, v in self.config.extra.items() if k != "fallback_chain"}
            chain.append(
                ModelConfig(
                    provider=provider,
                    model=model,
                    api_key=str(item.get("api_key", "")),
                    base_url=str(item.get("base_url", "")),
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    extra=extra_without_chain,
                )
            )
        return chain

    def _build_openai_client(self):
        api_key = self._resolve_api_key()
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
            timeout=self._resolve_timeout_seconds(),
            max_retries=0,
        )

    def _resolve_api_key(self) -> str:
        api_key = self.config.api_key or os.environ.get("OPENAI_API_KEY", "")
        if api_key:
            return api_key

        provider = (self.config.provider or "").strip().lower()
        is_local_model = bool(self.config.extra.get("is_local_model"))
        if provider == "local" or is_local_model or self._is_local_base_url(self.config.base_url):
            return os.environ.get("AISE_LOCAL_OPENAI_API_KEY", "local-no-key-required")
        return ""

    def _is_local_base_url(self, base_url: str) -> bool:
        value = (base_url or "").strip()
        if not value:
            return False
        try:
            parsed = urlparse(value)
        except Exception:
            return False
        host = (parsed.hostname or "").lower()
        return host in {"localhost", "127.0.0.1", "::1"}

    def _derive_call_purpose(self) -> str:
        skill = str(self._call_context.get("skill", "")).strip()
        agent = str(self._call_context.get("agent", "")).strip()
        role = str(self._call_context.get("role", "")).strip()
        if skill and agent:
            return f"agent:{agent} role:{role or 'unknown'} skill:{skill}"
        if skill:
            return f"skill:{skill}"
        return "llm_inference"

    def _build_trace_meta(
        self,
        *,
        call_id: str,
        started_at: datetime,
        purpose: str,
        messages: list[dict[str, str]],
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        base_url = (self.config.base_url or "https://api.openai.com/v1").rstrip("/")
        return {
            "call_id": call_id,
            "timestamp": started_at.strftime("%Y%m%d-%H%M%S"),
            "called_at_iso": started_at.isoformat(),
            "purpose": purpose,
            "provider": self.provider,
            "model": self.model,
            "url": base_url,
            "agent": str(self._call_context.get("agent", "")),
            "role": str(self._call_context.get("role", "")),
            "skill": str(self._call_context.get("skill", "")),
            "project_name": str(self._call_context.get("project_name", "")),
            "project_root": str(self._call_context.get("project_root", "")),
            "input": {
                "messages": self._safe_json(messages),
                "kwargs": self._safe_json({k: v for k, v in kwargs.items() if k != "stream"}),
            },
        }

    def _write_trace_file(self, payload: dict[str, Any]) -> None:
        trace_dir_raw = str(self._call_context.get("trace_dir", "")).strip()
        if not trace_dir_raw:
            return
        trace_dir = Path(trace_dir_raw)
        trace_dir.mkdir(parents=True, exist_ok=True)
        ts = str(payload.get("timestamp", datetime.now().strftime("%Y%m%d-%H%M%S")))
        call_id = str(payload.get("call_id", uuid4().hex))
        trace_file = trace_dir / f"{ts}-{call_id}.json"
        try:
            trace_file.write_text(
                self._json_dumps(payload),
                encoding="utf-8",
            )
            logger.info("LLM trace saved: call_id=%s file=%s", call_id, trace_file)
        except Exception as exc:
            logger.warning("LLM trace write failed: call_id=%s error=%s", call_id, exc)

    def _safe_json(self, value: Any) -> Any:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, dict):
            return {str(k): self._safe_json(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self._safe_json(v) for v in value]
        if isinstance(value, tuple):
            return [self._safe_json(v) for v in value]
        return str(value)

    def _json_dumps(self, value: Any) -> str:
        import json

        return json.dumps(value, ensure_ascii=False, indent=2)

    def _complete_with_responses(self, client, messages: list[dict[str, str]], **kwargs: Any) -> str:
        payload: dict[str, Any] = self._build_common_payload(messages, **kwargs)
        try:
            response = self._call_with_filtered_kwargs(client.responses.create, payload)
            text = self._extract_response_text(response)
            if text:
                return text
        except Exception as exc:
            logger.debug(
                (
                    "Responses API failed, falling back to chat.completions: "
                    "provider=%s model=%s error_type=%s error=%s details=%s"
                ),
                self.provider,
                self.model,
                type(exc).__name__,
                str(exc),
                self._extract_exception_details(exc),
                exc_info=True,
            )
        return self._complete_with_chat_completions(client, messages, **kwargs)

    def _complete_with_stream(self, client, messages: list[dict[str, str]], **kwargs: Any) -> str:
        payload: dict[str, Any] = self._build_common_payload(messages, **kwargs)
        chunks: list[str] = []
        try:
            stream = self._call_with_filtered_kwargs(
                client.responses.create,
                payload,
                stream=True,
                timeout=self._resolve_stream_event_timeout_seconds(),
            )
            for event in stream:
                delta = self._extract_event_text(event)
                if delta:
                    chunks.append(delta)
            text = "".join(chunks).strip()
            if text:
                return text
        except Exception as exc:
            logger.debug(
                ("Responses streaming API failed: provider=%s model=%s error_type=%s error=%s details=%s"),
                self.provider,
                self.model,
                type(exc).__name__,
                str(exc),
                self._extract_exception_details(exc),
                exc_info=True,
            )
            raise

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
        if "response_format" in kwargs:
            payload["response_format"] = kwargs["response_format"]
        payload.update(self.config.extra)
        if stream:
            chunks: list[str] = []
            finish_reason = ""
            stream_obj = self._call_with_filtered_kwargs(
                client.chat.completions.create,
                payload,
                stream=True,
                timeout=self._resolve_stream_event_timeout_seconds(),
            )
            for chunk in stream_obj:
                choices = getattr(chunk, "choices", None) or []
                for choice in choices:
                    reason = getattr(choice, "finish_reason", None)
                    if reason:
                        finish_reason = str(reason)
                    delta = getattr(choice, "delta", None)
                    content = getattr(delta, "content", "") if delta is not None else ""
                    if content:
                        chunks.append(str(content))
            if finish_reason:
                self._last_response_meta = dict(self._last_response_meta or {})
                self._last_response_meta["finish_reason"] = finish_reason
            return "".join(chunks).strip()

        response = self._call_with_filtered_kwargs(client.chat.completions.create, payload)
        choices = getattr(response, "choices", None) or []
        if not choices:
            return ""
        self._capture_response_meta(response)
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
            self._capture_response_meta(response)
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
        self._capture_response_meta(response)
        return "".join(chunks).strip()

    def _capture_response_meta(self, response: Any) -> None:
        meta: dict[str, Any] = {}
        finish_reason = self._extract_finish_reason(response)
        if finish_reason:
            meta["finish_reason"] = finish_reason
        usage = getattr(response, "usage", None)
        if usage is not None:
            meta["usage"] = self._safe_json(usage)
        if meta:
            self._last_response_meta = meta

    def _extract_finish_reason(self, response: Any) -> str:
        # Chat Completions shape
        choices = getattr(response, "choices", None)
        if choices is None and isinstance(response, dict):
            choices = response.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0]
            finish = getattr(first, "finish_reason", None)
            if finish is None and isinstance(first, dict):
                finish = first.get("finish_reason")
            if finish:
                return str(finish)

        # Responses API shape (best effort; provider SDKs vary)
        for attr in ("finish_reason", "status"):
            value = getattr(response, attr, None)
            if value:
                return str(value)
            if isinstance(response, dict) and response.get(attr):
                return str(response.get(attr))
        return ""

    def _extract_event_text(self, event: Any) -> str:
        event_type = getattr(event, "type", None)
        if isinstance(event, dict):
            event_type = event.get("type", event_type)
        event_type = str(event_type or "")

        def _field(obj: Any, name: str, default: Any = None) -> Any:
            if isinstance(obj, dict):
                return obj.get(name, default)
            return getattr(obj, name, default)

        def _text_from_candidate(value: Any) -> str:
            if isinstance(value, str):
                return value
            if isinstance(value, dict):
                # Common shapes: {"text": "..."} / {"delta": "..."} / nested content part
                for key in ("text", "delta"):
                    part = value.get(key)
                    if isinstance(part, str):
                        return part
                nested_part = value.get("part")
                if nested_part is not None:
                    text = _text_from_candidate(nested_part)
                    if text:
                        return text
            # SDK object path
            text = getattr(value, "text", None)
            if isinstance(text, str):
                return text
            delta = getattr(value, "delta", None)
            if isinstance(delta, str):
                return delta
            part = getattr(value, "part", None)
            if part is not None:
                return _text_from_candidate(part)
            return ""

        # Explicit terminal/non-text events (ignore to avoid duplicate output).
        if event_type in {
            "response.created",
            "response.in_progress",
            "response.completed",
            "response.failed",
            "response.incomplete",
            "response.output_item.done",
            "response.content_part.done",
            "response.output_text.done",
            "response.refusal.done",
            "response.function_call_arguments.done",
        }:
            return ""

        # Canonical text streaming delta event.
        if event_type == "response.output_text.delta":
            return _text_from_candidate(_field(event, "delta"))

        # Content part events may contain text directly in part/content_part/delta.
        if event_type in {
            "response.content_part.added",
            "response.content_part.delta",
            "response.output_item.added",
            "response.output_item.delta",
        }:
            for key in ("part", "content_part", "delta", "item"):
                text = _text_from_candidate(_field(event, key))
                if text:
                    return text
            return ""

        # Reasoning/refusal text deltas can appear as string deltas in some SDK/provider variants.
        if event_type in {
            "response.refusal.delta",
            "response.reasoning.delta",
            "response.reasoning_summary_text.delta",
        }:
            return _text_from_candidate(_field(event, "delta"))

        # Generic fallback for future/unknown text-bearing events.
        if event_type.endswith(".delta") or event_type.endswith(".added"):
            for key in ("delta", "part", "content_part", "item", "text"):
                text = _text_from_candidate(_field(event, key))
                if text:
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

    def _extract_exception_details(self, exc: Exception) -> dict[str, Any]:
        details: dict[str, Any] = {
            "type": type(exc).__name__,
            "args": [str(item) for item in getattr(exc, "args", ())],
            "repr": repr(exc),
            "traceback_tail": traceback.format_exc().splitlines()[-5:],
        }

        status_code = getattr(exc, "status_code", None)
        if status_code is not None:
            details["status_code"] = status_code

        request_id = getattr(exc, "request_id", None)
        if request_id is not None:
            details["request_id"] = request_id

        response = getattr(exc, "response", None)
        if response is not None:
            response_details: dict[str, Any] = {}
            resp_status = getattr(response, "status_code", None)
            if resp_status is not None:
                response_details["status_code"] = resp_status
            resp_text = getattr(response, "text", None)
            if isinstance(resp_text, str) and resp_text:
                response_details["text"] = resp_text[:2000]
            resp_headers = getattr(response, "headers", None)
            if resp_headers is not None:
                safe_headers: dict[str, str] = {}
                for key in ("x-request-id", "cf-ray", "server", "content-type"):
                    value = None
                    try:
                        value = resp_headers.get(key)
                    except Exception:
                        value = None
                    if value:
                        safe_headers[key] = str(value)
                if safe_headers:
                    response_details["headers"] = safe_headers
            if response_details:
                details["response"] = response_details

        return details

    def _should_log_retry_traceback(self, exc: Exception, attempt_index: int, max_attempts: int) -> bool:
        if attempt_index >= max_attempts:
            return True
        error_type = type(exc).__name__.lower()
        if "connection" in error_type or "timeout" in error_type:
            return False
        message = str(exc).lower()
        if "connection error" in message or "timed out" in message:
            return False
        return True

    _UNEXPECTED_KWARG_RE = re.compile(r"unexpected keyword argument '([^']+)'")
    _DEFAULT_TIMEOUT_SECONDS = 45.0
    _DEFAULT_STREAM_EVENT_TIMEOUT_SECONDS = 600.0

    def _resolve_timeout_seconds(self) -> float:
        raw = os.environ.get("AISE_LLM_TIMEOUT_SECONDS", "").strip()
        if not raw:
            return self._DEFAULT_TIMEOUT_SECONDS
        try:
            value = float(raw)
            return value if value > 0 else self._DEFAULT_TIMEOUT_SECONDS
        except ValueError:
            return self._DEFAULT_TIMEOUT_SECONDS

    def _resolve_stream_event_timeout_seconds(self) -> float:
        raw = os.environ.get("AISE_LLM_STREAM_EVENT_TIMEOUT_SECONDS", "").strip()
        if not raw:
            return self._DEFAULT_STREAM_EVENT_TIMEOUT_SECONDS
        try:
            value = float(raw)
            return value if value > 0 else 0.0
        except ValueError:
            return self._DEFAULT_STREAM_EVENT_TIMEOUT_SECONDS
