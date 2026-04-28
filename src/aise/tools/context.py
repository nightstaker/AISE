"""Shared workflow + tool execution context (immutable contracts +
mutable per-session state) used by every orchestrator tool factory."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..runtime.runtime_config import RuntimeConfig
from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class WorkflowState:
    """Mutable workflow state shared by all primitives in a session.

    Code never inspects fields by string keys — instead a tool calls
    ``mark_complete(report)`` and the orchestrator loop reads
    ``state.is_complete``.
    """

    is_complete: bool = False
    final_report: str = ""
    completed_steps: list[str] = field(default_factory=list)


@dataclass
class ToolContext:
    """All the runtime state a tool primitive may need.

    ``manager`` is a :class:`RuntimeManager`. ``runtime_resolver`` is an
    optional callable ``(agent_name, global_runtime) -> AgentRuntime``
    that returns a project-scoped runtime when one exists.
    """

    manager: Any
    project_root: Path | None
    config: RuntimeConfig
    workflow_state: WorkflowState
    on_event: Callable[[dict[str, Any]], None] | None = None
    event_log: list[dict[str, Any]] = field(default_factory=list)
    event_lock: threading.Lock = field(default_factory=threading.Lock)
    runtime_resolver: Callable[[str, Any], Any] | None = None
    processes_dir: Path | None = None
    # The raw user requirement that kicked off this session. Prepended
    # to every dispatch_task prompt so workers see the user's original
    # natural language and can mirror it in any docs/*.md they write.
    # Empty string means "no requirement available" (e.g. unit tests
    # exercising the primitive directly); the prefix is then skipped.
    original_requirement: str = ""
    # Dedup caches: the orchestrator fires a ``stage_update`` before every
    # dispatch even when the stage has not actually changed (parallel
    # developer dispatches all emit "implementation started"), and weak
    # local LLMs spam ``write_todos`` with unchanged todo lists — both
    # make the run log visually incoherent. We suppress consecutive
    # duplicates at emit-time.
    _last_stage: str | None = field(default=None, repr=False, compare=False)
    _last_todos_by_task: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def emit(self, event: dict[str, Any]) -> None:
        """Thread-safe event recording + callback dispatch.

        Suppresses two classes of redundant events that pollute the UI:
        - ``stage_update`` with the same ``stage`` as the previous one
          (typical during parallel dispatch within one phase).
        - ``todos_update`` whose ``todos`` list is byte-identical to the
          previous one for the same ``taskId`` (LLM write_todos spam).
        """
        et = event.get("type")
        with self.event_lock:
            if et == "stage_update":
                stage = event.get("stage")
                if stage is not None and stage == self._last_stage:
                    return
                self._last_stage = stage
            elif et == "todos_update":
                tid = event.get("taskId")
                if tid is not None:
                    import json as _json

                    try:
                        sig = _json.dumps(event.get("todos"), sort_keys=True, ensure_ascii=False)
                    except Exception:
                        sig = repr(event.get("todos"))
                    if self._last_todos_by_task.get(tid) == sig:
                        return
                    self._last_todos_by_task[tid] = sig
            self.event_log.append(event)
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception as exc:  # pragma: no cover - sink should never break tools
                logger.debug("on_event sink raised: %s", exc)

    def dispatch_count(self) -> int:
        with self.event_lock:
            return sum(1 for e in self.event_log if e.get("type") == "task_request")
