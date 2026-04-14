"""LangChain callback that records every LLM call's full input and output.

Attaches to the ChatModel via ``callbacks=[TraceLLMCallback(...)]``.
On each ``on_chat_model_start`` → ``on_llm_end`` pair it writes a JSON
file into the trace directory with:

- ``llm_call_index``: sequential call number within this agent session
- ``input_messages``: the FULL messages array sent to the LLM API
- ``output_message``: the LLM's response (including tool_calls)
- ``token_usage``: prompt/completion/total tokens (if returned)
- ``tool_calls``: extracted from the AIMessage (if any)
- ``duration_ms``: wall-clock time of the LLM call

This is complementary to the per-handle_message trace that
``AgentRuntime._write_trace`` already writes — that one captures the
final message list after the deepagents agent loop; this one captures
each individual LLM round-trip.
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.messages import BaseMessage
from langchain_core.outputs import LLMResult

from ..utils.logging import get_logger

logger = get_logger(__name__)


class TraceLLMCallback(BaseCallbackHandler):
    """Write a trace file for every LLM API call."""

    def __init__(self, trace_dir: str | Path, agent_name: str) -> None:
        super().__init__()
        self._trace_dir = Path(trace_dir)
        self._trace_dir.mkdir(parents=True, exist_ok=True)
        self._agent_name = agent_name
        self._call_index = 0
        # Pending state keyed by run_id
        self._pending: dict[UUID, dict[str, Any]] = {}

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
        self._call_index += 1
        self._pending[run_id] = {
            "call_index": self._call_index,
            "start_time": time.monotonic(),
            "input_messages": _dump_message_lists(messages),
        }

    # -- LLM end: capture the output and write the trace --------------------

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

        trace: dict[str, Any] = {
            "agent": self._agent_name,
            "llm_call_index": pending["call_index"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "input_messages": pending["input_messages"],
            "output": output,
        }

        try:
            ts = trace["timestamp"].replace(":", "-").split(".")[0]
            filename = f"{self._agent_name}_llm_{pending['call_index']:03d}_{ts}.json"
            path = self._trace_dir / filename
            path.write_text(
                json.dumps(trace, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Failed to write LLM trace: %s", exc)

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
        trace: dict[str, Any] = {
            "agent": self._agent_name,
            "llm_call_index": pending["call_index"],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_ms": duration_ms,
            "input_messages": pending["input_messages"],
            "error": str(error),
        }

        try:
            ts = trace["timestamp"].replace(":", "-").split(".")[0]
            filename = f"{self._agent_name}_llm_{pending['call_index']:03d}_ERROR_{ts}.json"
            path = self._trace_dir / filename
            path.write_text(
                json.dumps(trace, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception:
            pass

    # -- Tool callbacks (optional, for completeness) -------------------------

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
        # Tool traces are captured in the per-message trace.
        # No separate file needed.
        pass

    def on_tool_end(
        self,
        output: Any,
        *,
        run_id: UUID,
        parent_run_id: UUID | None = None,
        **kwargs: Any,
    ) -> None:
        pass


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
