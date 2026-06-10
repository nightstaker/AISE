"""Context compaction: drop superseded ``read_file`` results from the prompt.

A deep agent's ReAct loop keeps every tool result in the message history.
On a wide ``impl:<subsystem>`` fanout the developer re-reads the same files
repeatedly, and each full file dump stays in context forever. Measured on
project_21-calculator (2026-06-10): in the dispatch that overflowed the
128K window, ``read_file`` results were 77.6% of the input and **34% of
that was literal duplicate re-reads** — the same file (same path, offset,
limit) read up to 7×, every copy retained.

This middleware rewrites the messages sent to the model so that, when the
exact same read occurs more than once, only the **latest** copy keeps its
content; earlier copies are replaced by a short stub pointing forward. It
is non-destructive: it edits the per-call request, not the durable state,
so nothing is lost — the agent always sees the freshest read of each file,
just not the stale duplicates.

Reads are keyed by the full signature ``(file_path, offset, limit)``. A
full read and a ranged read of the same file are *different* views and are
both kept; only identical reads collapse.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

READ_TOOL = "read_file"

# Shown in place of a superseded read. Kept short — the whole point is to
# reclaim tokens — and explicit about why, so the model does not re-issue
# the read believing the content is missing.
_STUB = "（read_file `{path}`{region} 的此次结果已被后续相同读取取代，最新内容见下文。）"


def _read_signature(args: dict[str, Any]) -> tuple[Any, Any, Any] | None:
    """``(file_path, offset, limit)`` for a ``read_file`` tool call, or
    ``None`` when no file path is present."""
    path = args.get("file_path")
    if not path:
        return None
    return (path, args.get("offset"), args.get("limit"))


def _region_hint(sig: tuple[Any, Any, Any]) -> str:
    offset, limit = sig[1], sig[2]
    if offset is None and limit is None:
        return ""
    parts = []
    if offset is not None:
        parts.append(f"offset={offset}")
    if limit is not None:
        parts.append(f"limit={limit}")
    return " (" + ", ".join(parts) + ")"


def compact_superseded_reads(messages: Sequence[BaseMessage]) -> list[BaseMessage]:
    """Return ``messages`` with superseded ``read_file`` results stubbed.

    For every read signature that appears more than once, all occurrences
    except the last are replaced with a stub. The returned list is a new
    list; the stubbed messages are copies (originals are untouched). The
    same list object is returned when nothing changed, so callers can skip
    work cheaply.
    """
    # tool_call_id -> read signature, taken from the AIMessage tool calls.
    # Resolving through the call (not ToolMessage.name) gives us the file
    # path and is robust to providers that omit ``name`` on the result.
    id_to_sig: dict[str, tuple[Any, Any, Any]] = {}
    for msg in messages:
        if isinstance(msg, AIMessage):
            for call in msg.tool_calls or []:
                if call.get("name") != READ_TOOL:
                    continue
                sig = _read_signature(call.get("args") or {})
                call_id = call.get("id")
                if sig is not None and call_id is not None:
                    id_to_sig[call_id] = sig

    # Index of the LAST read result per signature — the one we keep.
    last_index: dict[tuple[Any, Any, Any], int] = {}
    for i, msg in enumerate(messages):
        if isinstance(msg, ToolMessage):
            sig = id_to_sig.get(msg.tool_call_id)
            if sig is not None:
                last_index[sig] = i

    new_messages = list(messages)
    changed = False
    for i, msg in enumerate(messages):
        if not isinstance(msg, ToolMessage):
            continue
        sig = id_to_sig.get(msg.tool_call_id)
        if sig is None or last_index.get(sig) == i:
            continue  # not a tracked read, or this is the kept (latest) copy
        if not isinstance(msg.content, str):
            continue
        stub = _STUB.format(path=sig[0], region=_region_hint(sig))
        if len(msg.content) <= len(stub):
            continue  # already small (or already a stub) — no win, skip
        new_messages[i] = msg.model_copy(update={"content": stub})
        changed = True

    return new_messages if changed else messages


class SupersededReadCompactionMiddleware(AgentMiddleware):
    """Strip duplicate ``read_file`` results from each model request.

    Hooks ``wrap_model_call`` (and its async twin) so the compaction runs
    on every model call against the live message list, transiently — the
    durable conversation state is never mutated.
    """

    name = "SupersededReadCompactionMiddleware"

    def _apply(self, request: ModelRequest) -> ModelRequest:
        compacted = compact_superseded_reads(request.messages)
        # ``compact_superseded_reads`` returns the same object when nothing
        # was superseded, so identity is a sufficient (and cheap) no-op test.
        if compacted is request.messages:
            return request
        return request.override(messages=compacted)

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Any],
    ) -> Any:
        return handler(self._apply(request))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[Any]],
    ) -> Any:
        return await handler(self._apply(request))
