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

import json
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
    ) -> None:
        if create_deep_agent is None:
            raise RuntimeError(
                "deepagents package is required but not installed. "
                "Install it with: pip install deepagents>=0.4.3"
            )

        self._id = uuid.uuid4().hex[:12]
        self._state = AgentState.CREATED
        self._url = url
        self._trace_dir: Path | None = Path(trace_dir) if trace_dir else None
        if self._trace_dir:
            self._trace_dir.mkdir(parents=True, exist_ok=True)
        self._call_seq = 0

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
                f"Cannot evoke agent in state {self._state.value}. "
                "Agent must be in CREATED or STOPPED state."
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

    def handle_message(self, content: str, *, thread_id: str | None = None) -> str:
        """Process an incoming text message and return the agent's response.

        The agent must be in ACTIVE state. The message is passed to the
        deepagents runtime which autonomously invokes the LLM and any
        registered tools to produce a response.

        A full trace (input, raw result, extracted response) is written
        to ``trace_dir`` when configured.

        Args:
            content: The input message text.
            thread_id: Optional conversation thread ID for stateful interactions.
                Requires a checkpointer to be configured.

        Returns:
            The agent's text response.

        Raises:
            RuntimeError: If the agent is not in ACTIVE state.
        """
        if self._state != AgentState.ACTIVE:
            raise RuntimeError(
                f"Agent is not active (state={self._state.value}). "
                "Call evoke() first."
            )

        self._call_seq += 1
        call_id = f"{self._id}_{self._call_seq:04d}"

        logger.info(
            "Message received: agent=%s call=%s thread=%s length=%d",
            self.name, call_id, thread_id or "default", len(content),
        )

        config: dict[str, Any] = {}
        if thread_id:
            config["configurable"] = {"thread_id": thread_id}

        try:
            result = self._agent.invoke(
                {"messages": [HumanMessage(content=content)]},
                config=config if config else None,
            )
            response = _extract_response(result)

            # Write trace
            self._write_trace(call_id, content, result, response)

            # Detailed diagnostics on empty response
            if not response.strip():
                diag = _diagnose_empty_response(result)
                logger.warning(
                    "Empty response: agent=%s call=%s diagnosis=%s",
                    self.name, call_id, diag,
                )

            logger.info(
                "Message processed: agent=%s call=%s response_length=%d",
                self.name, call_id, len(response),
            )
            return response

        except Exception as exc:
            logger.error(
                "Message processing failed: agent=%s call=%s error=%s",
                self.name, call_id, exc,
            )
            raise

    def _write_trace(
        self, call_id: str, input_text: str, raw_result: Any, response: str,
    ) -> None:
        """Write a JSON trace file for this LLM call."""
        if not self._trace_dir:
            return
        try:
            ts = datetime.now(timezone.utc).isoformat()
            messages_dump = _dump_messages(raw_result)
            trace = {
                "call_id": call_id,
                "agent": self.name,
                "timestamp": ts,
                "input": input_text[:2000],
                "input_length": len(input_text),
                "response": response[:5000],
                "response_length": len(response),
                "empty_response": not response.strip(),
                "messages_count": len(messages_dump),
                "messages": messages_dump,
            }
            filename = f"{self.name}_{call_id}_{ts.replace(':', '-').split('.')[0]}.json"
            path = self._trace_dir / filename
            path.write_text(
                json.dumps(trace, ensure_ascii=False, indent=2, default=str),
                encoding="utf-8",
            )
        except Exception as exc:
            logger.debug("Failed to write trace: %s", exc)

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
    """Serialize the messages from a deepagent result for trace output."""
    if not isinstance(result, dict):
        return []
    messages = result.get("messages")
    if not isinstance(messages, list):
        return []

    dump: list[dict[str, Any]] = []
    for msg in messages:
        entry: dict[str, Any] = {"type": type(msg).__name__}
        content = getattr(msg, "content", None)
        if isinstance(content, str):
            entry["content"] = content[:3000]
            entry["content_length"] = len(content)
        elif isinstance(content, list):
            entry["content"] = str(content)[:1000]
        tool_calls = getattr(msg, "tool_calls", None)
        if isinstance(tool_calls, list) and tool_calls:
            entry["tool_calls"] = [
                {"name": tc.get("name", ""), "args_keys": sorted(tc.get("args", {}).keys())}
                for tc in tool_calls
            ]
        name = getattr(msg, "name", None)
        if name:
            entry["name"] = name
        dump.append(entry)
    return dump
