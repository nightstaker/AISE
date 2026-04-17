"""Core AgentRuntime - builds and manages a deepagents-based agent instance.

Usage::

    runtime = AgentRuntime(
        agent_md="path/to/agent.md",
        skills_dir="path/to/skills/",
        model="openai:gpt-4o",
    )
    runtime.evoke()  # activate the agent

    response = runtime.handle_message("Help me review this code")
    print(response)

    runtime.stop()
"""

from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph.state import CompiledStateGraph

from ..utils.logging import get_logger
from .agent_card import build_agent_card
from .agent_md_parser import parse_agent_md
from .models import AgentCard, AgentDefinition, AgentState
from .skill_loader import get_skill_source_paths, load_skills_from_directory

logger = get_logger(__name__)

try:
    from deepagents import create_deep_agent
except ImportError:
    create_deep_agent = None  # type: ignore[assignment,misc]


class AgentRuntime:
    """Agent runtime built on the deepagents framework.

    Accepts an agent.md definition, a skills directory, and a model
    to construct a fully functional agent with an A2A-compliant agent card.

    Lifecycle:
        1. ``__init__``: Parse definition, load skills, build deep agent, generate card.
           State → CREATED
        2. ``evoke()``: Activate the agent to accept messages.
           State → ACTIVE
        3. ``handle_message()``: Process an incoming text message (requires ACTIVE).
        4. ``stop()``: Deactivate the agent.
           State → STOPPED
    """

    def __init__(
        self,
        agent_md: str | Path,
        skills_dir: str | Path,
        model: str | BaseChatModel,
        *,
        extra_tools: list[Any] | None = None,
        backend: Any | None = None,
        trace_dir: str | Path | None = None,
        url: str = "",
        checkpointer: Any = None,
        max_iterations: int = 240,
    ) -> None:
        if create_deep_agent is None:
            raise RuntimeError(
                "deepagents package is required but not installed. Install it with: pip install deepagents>=0.4.3"
            )

        self._id = uuid.uuid4().hex[:12]
        self._state = AgentState.CREATED
        self._url = url
        self._trace_dir: Path | None = Path(trace_dir) if trace_dir else None
        if self._trace_dir:
            self._trace_dir.mkdir(parents=True, exist_ok=True)
        self._call_seq = 0
        self._current_task: str | None = None
        self._max_iterations = max_iterations

        # 1. Parse agent definition
        self._definition: AgentDefinition = parse_agent_md(agent_md)
        logger.info(
            "Agent definition parsed: name=%s version=%s skills=%d",
            self._definition.name,
            self._definition.version,
            len(self._definition.skills),
        )

        # 2. Load skills from directory + merge extra tools
        self._skills_dir = Path(skills_dir)
        tools, extra_skill_infos = load_skills_from_directory(self._skills_dir)
        if extra_tools:
            tools = list(tools) + list(extra_tools)
        self._tools = tools
        self._extra_skill_infos = extra_skill_infos

        # 3. Build the deep agent
        skill_sources = get_skill_source_paths(self._skills_dir)
        create_kwargs: dict[str, Any] = {
            "model": model,
            "tools": tools or None,
            "system_prompt": self._definition.system_prompt or None,
            "skills": skill_sources or None,
            "name": self._definition.name,
            "checkpointer": checkpointer,
        }
        if backend is not None:
            create_kwargs["backend"] = backend
        self._agent: CompiledStateGraph = create_deep_agent(**create_kwargs)
        logger.info(
            "Deep agent created: name=%s tools=%d skill_sources=%d",
            self._definition.name,
            len(tools),
            len(skill_sources),
        )

        # 4. Generate A2A agent card
        self._card: AgentCard = build_agent_card(
            self._definition,
            url=url,
            extra_skills=extra_skill_infos,
        )
        logger.info(
            "Agent card generated: name=%s skills=%d",
            self._card.name,
            len(self._card.skills),
        )

    # -- Properties ----------------------------------------------------------

    @property
    def id(self) -> str:
        """Unique runtime instance identifier."""
        return self._id

    @property
    def name(self) -> str:
        """Agent name from the definition."""
        return self._definition.name

    @property
    def state(self) -> AgentState:
        """Current lifecycle state."""
        return self._state

    @property
    def definition(self) -> AgentDefinition:
        """The parsed agent definition."""
        return self._definition

    @property
    def agent_card(self) -> AgentCard:
        """The A2A-compliant agent card."""
        return self._card

    @property
    def current_task(self) -> str | None:
        """Brief description of what the agent is working on, or None."""
        return self._current_task

    # -- Lifecycle -----------------------------------------------------------

    def evoke(self) -> None:
        """Activate the agent to start accepting messages.

        Transitions state from CREATED → ACTIVE.

        Raises:
            RuntimeError: If agent is not in CREATED or STOPPED state.
        """
        if self._state == AgentState.ACTIVE:
            logger.warning("Agent already active: name=%s", self.name)
            return

        if self._state not in (AgentState.CREATED, AgentState.STOPPED):
            raise RuntimeError(
                f"Cannot evoke agent in state {self._state.value}. Agent must be in CREATED or STOPPED state."
            )

        self._state = AgentState.ACTIVE
        logger.info("Agent activated: name=%s id=%s", self.name, self._id)

    def stop(self) -> None:
        """Deactivate the agent.

        Transitions state to STOPPED.
        """
        self._state = AgentState.STOPPED
        logger.info("Agent stopped: name=%s id=%s", self.name, self._id)

    # -- Message handling ----------------------------------------------------

    def handle_message(
        self,
        content: str,
        *,
        thread_id: str | None = None,
        on_todos_update: Any = None,
    ) -> str:
        """Process an incoming text message and return the agent's response.

        The agent must be in ACTIVE state. The message is passed to the
        deepagents runtime which autonomously invokes the LLM and any
        registered tools to produce a response.

        A single trace file per dispatch is written into ``trace_dir``
        when configured. The file is updated in-place after every LLM
        round-trip so a crash mid-run still leaves a prefix trace on disk.

        Args:
            content: The input message text.
            thread_id: Optional conversation thread ID for stateful interactions.
                Requires a checkpointer to be configured.
            on_todos_update: Optional callback ``(list[dict]) -> None`` fired
                whenever the agent invokes deepagents' ``write_todos`` tool.
                Used by the web UI to surface live progress.

        Returns:
            The agent's text response.

        Raises:
            RuntimeError: If the agent is not in ACTIVE state.
        """
        if self._state not in (AgentState.ACTIVE, AgentState.WORKING):
            raise RuntimeError(f"Agent is not active (state={self._state.value}). Call evoke() first.")

        self._call_seq += 1
        call_id = f"{self._id}_{self._call_seq:04d}"

        # Transition to WORKING so the Monitor sees real-time status.
        self._state = AgentState.WORKING
        self._current_task = content[:120]

        logger.info(
            "Message received: agent=%s call=%s thread=%s length=%d",
            self.name,
            call_id,
            thread_id or "default",
            len(content),
        )

        config: dict[str, Any] = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}

        # Build the shared trace record for this dispatch. All LLM round-
        # trips append to the same record and flush to the same file, so
        # there is exactly ONE trace file per handle_message call.
        started_at = datetime.now(timezone.utc).isoformat()
        trace_record: dict[str, Any] = {
            "call_id": call_id,
            "agent": self.name,
            "agent_id": self._id,
            "started_at": started_at,
            "input": content,
            "input_length": len(content),
            "status": "running",
            "llm_calls": [],
            "llm_call_count": 0,
        }
        trace_path: Path | None = None
        trace_lock = threading.Lock()
        if self._trace_dir:
            from .trace_callback import TraceLLMCallback, _flush

            ts_file = started_at.replace(":", "-").split(".")[0]
            trace_path = self._trace_dir / f"{self.name}_{call_id}_{ts_file}.json"
            _flush(trace_path, trace_record)

            llm_tracer = TraceLLMCallback(
                trace_record=trace_record,
                trace_path=trace_path,
                lock=trace_lock,
                on_todos_update=on_todos_update,
            )
            config.setdefault("callbacks", []).append(llm_tracer)
        elif on_todos_update is not None:
            # No trace_dir but still want live todos — attach a lightweight
            # callback whose only job is to forward ``write_todos`` invocations.
            from .trace_callback import TraceLLMCallback

            llm_tracer = TraceLLMCallback(
                trace_record=trace_record,
                trace_path=None,
                lock=trace_lock,
                on_todos_update=on_todos_update,
            )
            config.setdefault("callbacks", []).append(llm_tracer)

        # Override deepagents' default recursion_limit (1000) with a
        # sane cap. Without this, weak LLMs loop hundreds of times.
        config.setdefault("recursion_limit", self._max_iterations)

        try:
            result = self._agent.invoke(
                {"messages": [HumanMessage(content=content)]},
                config=config if config else None,
            )
            response = _extract_response(result)

            with trace_lock:
                trace_record["status"] = "completed"
                trace_record["completed_at"] = datetime.now(timezone.utc).isoformat()
                trace_record["response"] = response
                trace_record["response_length"] = len(response)
                trace_record["empty_response"] = not response.strip()
                messages_dump = _dump_messages(result)
                trace_record["messages_count"] = len(messages_dump)
                trace_record["messages"] = messages_dump
                if trace_path is not None:
                    from .trace_callback import _flush

                    _flush(trace_path, trace_record)

            # Detailed diagnostics on empty response
            if not response.strip():
                diag = _diagnose_empty_response(result)
                logger.warning(
                    "Empty response: agent=%s call=%s diagnosis=%s",
                    self.name,
                    call_id,
                    diag,
                )

            logger.info(
                "Message processed: agent=%s call=%s response_length=%d",
                self.name,
                call_id,
                len(response),
            )
            return response

        except Exception as exc:
            logger.error(
                "Message processing failed: agent=%s call=%s error=%s",
                self.name,
                call_id,
                exc,
            )
            with trace_lock:
                trace_record["status"] = "failed"
                trace_record["completed_at"] = datetime.now(timezone.utc).isoformat()
                trace_record["error"] = str(exc)
                trace_record["error_type"] = type(exc).__name__
                if trace_path is not None:
                    from .trace_callback import _flush

                    _flush(trace_path, trace_record)
            raise
        finally:
            # Back to ACTIVE (ready for next message). Clear the task.
            self._state = AgentState.ACTIVE
            self._current_task = None

    def get_agent_card_dict(self) -> dict[str, Any]:
        """Return the agent card as a JSON-serializable dict."""
        return self._card.to_dict()


def _extract_response(result: Any) -> str:
    """Extract the final text response from a deepagent invocation result.

    Only considers AIMessage content (never ToolMessage or HumanMessage).
    When the last AIMessage is empty (common when LLM ends with a tool call),
    walks backward to find the most recent AIMessage with actual text.
    """
    if isinstance(result, str):
        return result

    if isinstance(result, dict):
        messages = result.get("messages")
        if isinstance(messages, list):
            # Walk backward looking for the latest AIMessage with text content
            for msg in reversed(messages):
                if not isinstance(msg, AIMessage):
                    continue
                text = msg.content if isinstance(msg.content, str) else ""
                if text.strip():
                    return text

            # All AIMessages are empty — collect the longest AIMessage content
            # that contains tool_use results as context (this is a fallback)
            best = ""
            for msg in messages:
                if isinstance(msg, AIMessage):
                    text = msg.content if isinstance(msg.content, str) else ""
                    if len(text) > len(best):
                        best = text
            if best.strip():
                return best

        for key in ("output_text", "output", "text", "content", "response"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value

    if hasattr(result, "content") and isinstance(result.content, str):
        return result.content

    return ""


def _diagnose_empty_response(result: Any) -> str:
    """Produce a diagnostic string explaining why the response is empty."""
    parts: list[str] = []

    if not isinstance(result, dict):
        parts.append(f"result type={type(result).__name__}")
        return "; ".join(parts)

    messages = result.get("messages")
    if not isinstance(messages, list):
        parts.append("no messages list in result")
        return "; ".join(parts)

    parts.append(f"total_messages={len(messages)}")

    # Analyze last few messages
    for i, msg in enumerate(messages[-5:]):
        idx = len(messages) - 5 + i
        msg_type = type(msg).__name__
        content = getattr(msg, "content", None)
        content_len = len(content) if isinstance(content, str) else 0
        tool_calls = getattr(msg, "tool_calls", None)
        tc_count = len(tool_calls) if isinstance(tool_calls, list) else 0

        detail = f"[{idx}] {msg_type}: content_len={content_len}"
        if tc_count:
            tc_names = [tc.get("name", "?") for tc in tool_calls] if isinstance(tool_calls, list) else []
            detail += f" tool_calls={tc_count}({','.join(tc_names)})"
        parts.append(detail)

    # Check if last message is an AI message with only tool calls (no text)
    last = messages[-1] if messages else None
    if last and isinstance(last, AIMessage):
        tc = getattr(last, "tool_calls", None)
        has_tc = isinstance(tc, list) and len(tc) > 0
        has_text = isinstance(last.content, str) and last.content.strip()
        if has_tc and not has_text:
            parts.append("CAUSE: last AIMessage has tool_calls but no text content (LLM stopped mid-reasoning)")
        elif not has_text:
            parts.append("CAUSE: last AIMessage has empty content")

    return "; ".join(parts)


def _dump_messages(result: Any) -> list[dict[str, Any]]:
    """Serialize the messages from a deepagent result for trace output.

    Records FULL content and tool_call arguments so that traces can be
    used to diagnose edit_file/write_file failures, LLM hallucinations,
    and tool invocation loops without needing to reproduce the run.
    """
    if not isinstance(result, dict):
        return []
    messages = result.get("messages")
    if not isinstance(messages, list):
        return []

    dump: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {"type": type(msg).__name__}

        # Full content (no truncation — traces are diagnostic artifacts)
        content = getattr(msg, "content", None)
        if isinstance(content, str):
            entry["content"] = content
            entry["content_length"] = len(content)
        elif isinstance(content, list):
            # Multi-part content (e.g. tool_use blocks)
            entry["content"] = _safe_serialize(content)

        # Tool calls with FULL arguments
        tool_calls = getattr(msg, "tool_calls", None)
        if isinstance(tool_calls, list) and tool_calls:
            entry["tool_calls"] = [_dump_tool_call(tc) for tc in tool_calls]

        # Tool call ID (links ToolMessage back to the AIMessage that invoked it)
        tool_call_id = getattr(msg, "tool_call_id", None)
        if tool_call_id:
            entry["tool_call_id"] = tool_call_id

        # Name (set on ToolMessage to identify which tool returned)
        name = getattr(msg, "name", None)
        if name:
            entry["name"] = name

        # Additional response metadata if present
        response_metadata = getattr(msg, "response_metadata", None)
        if isinstance(response_metadata, dict) and response_metadata:
            # Extract token usage if available
            usage = response_metadata.get("token_usage") or response_metadata.get("usage")
            if usage:
                entry["token_usage"] = _safe_serialize(usage)
            finish_reason = response_metadata.get("finish_reason")
            if finish_reason:
                entry["finish_reason"] = finish_reason

        dump.append(entry)
    return dump


def _dump_tool_call(tc: Any) -> dict[str, Any]:
    """Serialize a single tool call with full arguments."""
    if isinstance(tc, dict):
        return {
            "id": tc.get("id", ""),
            "name": tc.get("name", ""),
            "args": _safe_serialize(tc.get("args", {})),
        }
    # Fallback for non-dict tool_call objects
    return {"raw": _safe_serialize(tc)}


def _safe_serialize(obj: Any) -> Any:
    """Best-effort JSON-safe serialization."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v) for v in obj]
    return str(obj)
