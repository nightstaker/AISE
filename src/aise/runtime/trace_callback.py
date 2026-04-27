"""LangChain callback that records every LLM call into a shared trace record.

Unlike a per-LLM-call file sink, this callback appends each round-trip to
a ``trace_record`` dict owned by the ``AgentRuntime`` for the current
``handle_message`` invocation. The runtime flushes that same dict to a
single file across the life of the dispatch (incrementally updated as
each LLM round-trip finishes), so a crash mid-run leaves a partial-but-
complete-on-prefix trace on disk.

It also detects deepagents' built-in ``write_todos`` tool calls and
forwards the todos list to an optional ``on_todos_update`` callback so
that the web UI can surface live task progress per dispatch.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from ..utils.logging import get_logger

logger = get_logger(__name__)


class TraceLLMCallback(BaseCallbackHandler):
    """Append every LLM round-trip to a shared trace record.

    The ``AgentRuntime`` owns one ``trace_record`` dict per
    ``handle_message`` call and passes it here. On each ``on_llm_end``
    (or ``on_llm_error``) we append to ``trace_record["llm_calls"]``
    and flush the whole record to ``trace_path``.
    """

    def __init__(
        self,
        *,
        trace_record: dict[str, Any],
        trace_path: Path | None,
        lock: threading.Lock,
        on_todos_update: Callable[[list[dict[str, Any]]], None] | None = None,
        on_token_usage: Callable[[dict[str, int]], None] | None = None,
    ) -> None:
        super().__init__()
        self._record = trace_record
        self._path = trace_path
        self._lock = lock
        self._on_todos_update = on_todos_update
        self._on_token_usage = on_token_usage
        self._pending: dict[UUID, dict[str, Any]] = {}
        # Aggregate per-dispatch token usage. The callback owns the
        # running totals so a crash mid-run still leaves an accurate
        # ``token_usage`` block on the partial trace prefix.
        self._record.setdefault(
            "token_usage",
            {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_calls": 0},
        )

    # -- LLM start: capture the full input messages -------------------------

    def on_chat_model_start(
        self,
        serialized: dict[str, Any],
        messages: list[list[BaseMessage]],
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        self._pending[run_id] = {
            "start_time": time.monotonic(),
            "input_messages": _dump_message_lists(messages),
        }

    # -- LLM end: append the output to the shared record --------------------

    def on_llm_end(
        self,
        response: LLMResult,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        pending = self._pending.pop(run_id, None)
        if pending is None:
            return

        duration_ms = int((time.monotonic() - pending["start_time"]) * 1000)
        output = _dump_llm_result(response)
        call_tokens = _extract_token_counts(response)
        if any(call_tokens.values()):
            output["token_usage_normalized"] = call_tokens

        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "input_messages": pending["input_messages"],
            "output": output,
        }

        forwarded: dict[str, int] | None = None
        with self._lock:
            calls = self._record.setdefault("llm_calls", [])
            entry["index"] = len(calls) + 1
            calls.append(entry)
            self._record["llm_call_count"] = len(calls)
            totals = self._record.setdefault(
                "token_usage",
                {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "llm_calls": 0},
            )
            totals["input_tokens"] += call_tokens["input_tokens"]
            totals["output_tokens"] += call_tokens["output_tokens"]
            totals["total_tokens"] += call_tokens["total_tokens"]
            totals["llm_calls"] += 1
            if any(call_tokens.values()):
                forwarded = dict(call_tokens)
            _flush(self._path, self._record)

        if forwarded is not None and self._on_token_usage is not None:
            try:
                self._on_token_usage(forwarded)
            except Exception as exc:  # pragma: no cover - never let UI plumbing crash the agent
                logger.debug("on_token_usage callback failed: %s", exc)

    # -- LLM error ----------------------------------------------------------

    def on_llm_error(
        self,
        error: BaseException,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        pending = self._pending.pop(run_id, None)
        if pending is None:
            return

        duration_ms = int((time.monotonic() - pending["start_time"]) * 1000)
        entry: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "input_messages": pending["input_messages"],
            "error": str(error),
            "error_type": type(error).__name__,
        }

        with self._lock:
            calls = self._record.setdefault("llm_calls", [])
            entry["index"] = len(calls) + 1
            calls.append(entry)
            self._record["llm_call_count"] = len(calls)
            _flush(self._path, self._record)

    # -- Tool callbacks -----------------------------------------------------

    def on_tool_start(
        self,
        serialized: dict[str, Any],
        input_str: str,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        inputs: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> None:
        if self._on_todos_update is None:
            return
        name = ""
        if isinstance(serialized, dict):
            name = serialized.get("name") or ""
        if name != "write_todos":
            return
        todos = _extract_todos(inputs, input_str)
        if todos is None:
            return
        try:
            self._on_todos_update(todos)
        except Exception as exc:  # pragma: no cover - never let UI plumbing crash the agent
            logger.debug("on_todos_update callback failed: %s", exc)


# -- Module-level helpers ---------------------------------------------------


def _flush(path: Path | None, record: dict[str, Any]) -> None:
    if path is None:
        return
    try:
        path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    except Exception as exc:  # pragma: no cover - best-effort logging
        logger.debug("Failed to flush trace: %s", exc)


def _extract_todos(inputs: dict[str, Any] | None, input_str: str) -> list[dict[str, Any]] | None:
    """Pull the todos list out of a ``write_todos`` tool invocation.

    deepagents' ``write_todos`` takes one argument: ``todos`` (list of
    ``{content, status, activeForm}``). Older or alternate integrations
    may pass it as a JSON string, so fall back to parsing ``input_str``.
    """
    if isinstance(inputs, dict):
        todos = inputs.get("todos")
        if isinstance(todos, list):
            return _safe(todos)
    if isinstance(input_str, str) and input_str.strip():
        try:
            parsed = json.loads(input_str)
        except Exception:
            return None
        if isinstance(parsed, list):
            return _safe(parsed)
        if isinstance(parsed, dict):
            todos = parsed.get("todos")
            if isinstance(todos, list):
                return _safe(todos)
    return None


# -- Serialization helpers --------------------------------------------------


def _dump_message_lists(batches: list[list[BaseMessage]]) -> list[list[dict[str, Any]]]:
    """Serialize the messages exactly as sent to the LLM."""
    result = []
    for batch in batches:
        result.append([_dump_single_message(m) for m in batch])
    return result


def _dump_single_message(msg: BaseMessage) -> dict[str, Any]:
    entry: dict[str, Any] = {"type": type(msg).__name__}

    content = getattr(msg, "content", None)
    if isinstance(content, str):
        entry["content"] = content
    elif isinstance(content, list):
        entry["content"] = _safe(content)

    tool_calls = getattr(msg, "tool_calls", None)
    if isinstance(tool_calls, list) and tool_calls:
        entry["tool_calls"] = [_dump_tool_call(tc) for tc in tool_calls]

    tool_call_id = getattr(msg, "tool_call_id", None)
    if tool_call_id:
        entry["tool_call_id"] = tool_call_id

    name = getattr(msg, "name", None)
    if name:
        entry["name"] = name

    return entry


def _dump_tool_call(tc: Any) -> dict[str, Any]:
    if isinstance(tc, dict):
        return {
            "id": tc.get("id", ""),
            "name": tc.get("name", ""),
            "args": _safe(tc.get("args", {})),
        }
    return {"raw": str(tc)}


def _extract_token_counts(result: LLMResult) -> dict[str, int]:
    """Pull ``input_tokens`` / ``output_tokens`` / ``total_tokens`` from an
    ``LLMResult``, normalizing across providers.

    OpenAI exposes ``prompt_tokens`` / ``completion_tokens``; Anthropic and
    LangChain's standardized ``UsageMetadata`` use ``input_tokens`` /
    ``output_tokens``. We accept both and fall back to summing components
    when ``total_tokens`` is absent.
    """
    counts = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}

    def _add(usage: Any) -> None:
        if not isinstance(usage, dict):
            return
        prompt = usage.get("input_tokens") if "input_tokens" in usage else usage.get("prompt_tokens")
        completion = usage.get("output_tokens") if "output_tokens" in usage else usage.get("completion_tokens")
        total = usage.get("total_tokens")
        try:
            counts["input_tokens"] += int(prompt or 0)
        except (TypeError, ValueError):
            pass
        try:
            counts["output_tokens"] += int(completion or 0)
        except (TypeError, ValueError):
            pass
        try:
            counts["total_tokens"] += int(total or 0)
        except (TypeError, ValueError):
            pass

    llm_output = result.llm_output
    if isinstance(llm_output, dict):
        _add(llm_output.get("token_usage"))
        _add(llm_output.get("usage"))

    if counts["input_tokens"] == 0 and counts["output_tokens"] == 0 and counts["total_tokens"] == 0:
        for batch in result.generations or []:
            for gen in batch:
                msg = getattr(gen, "message", None)
                if msg is None:
                    continue
                _add(getattr(msg, "usage_metadata", None))
                response_metadata = getattr(msg, "response_metadata", None)
                if isinstance(response_metadata, dict):
                    _add(response_metadata.get("token_usage"))
                    _add(response_metadata.get("usage"))

    if counts["total_tokens"] == 0:
        counts["total_tokens"] = counts["input_tokens"] + counts["output_tokens"]
    return counts


def _dump_llm_result(result: LLMResult) -> dict[str, Any]:
    """Extract the output message, token usage, and finish reason."""
    out: dict[str, Any] = {}

    if result.generations:
        gen = result.generations[0][0] if result.generations[0] else None
        if gen is not None:
            msg = getattr(gen, "message", None)
            if msg is not None:
                out["message"] = _dump_single_message(msg)
            out["text"] = getattr(gen, "text", "")
            gen_info = getattr(gen, "generation_info", None)
            if gen_info:
                out["generation_info"] = _safe(gen_info)

    llm_output = result.llm_output
    if isinstance(llm_output, dict):
        usage = llm_output.get("token_usage") or llm_output.get("usage")
        if usage:
            out["token_usage"] = _safe(usage)
        model = llm_output.get("model_name") or llm_output.get("model")
        if model:
            out["model"] = model

    return out


def _safe(obj: Any) -> Any:
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe(v) for v in obj]
    return str(obj)
