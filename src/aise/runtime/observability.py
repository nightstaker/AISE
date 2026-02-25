"""Monitoring, logging, and trace capture for runtime execution."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import RLock
from typing import Any
from uuid import uuid4

from ..utils.logging import get_logger
from .models import ExecutionResult, LLMTrace

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(slots=True)
class EventRecord:
    trace_id: str
    span_id: str
    task_id: str
    event_type: str
    payload: dict[str, Any] = field(default_factory=dict)
    tenant_id: str | None = None
    node_id: str | None = None
    agent_id: str | None = None
    event_time: str = field(default_factory=_now_iso)

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "tenant_id": self.tenant_id,
            "task_id": self.task_id,
            "node_id": self.node_id,
            "agent_id": self.agent_id,
            "event_type": self.event_type,
            "event_time": self.event_time,
            "payload": dict(self.payload),
        }


class ObservabilityCenter:
    """Collects execution events, LLM traces, and task logs."""

    def __init__(self) -> None:
        self._events_by_task: dict[str, list[EventRecord]] = defaultdict(list)
        self._llm_traces_by_task: dict[str, list[LLMTrace]] = defaultdict(list)
        self._lock = RLock()

    def new_trace_id(self) -> str:
        return f"tr_{uuid4().hex[:12]}"

    def new_span_id(self) -> str:
        return f"sp_{uuid4().hex[:12]}"

    def record_event(self, event: EventRecord) -> None:
        with self._lock:
            self._events_by_task[event.task_id].append(event)
        logger.debug(
            "Runtime event: task=%s node=%s type=%s agent=%s",
            event.task_id,
            event.node_id,
            event.event_type,
            event.agent_id,
        )

    def record_llm_trace(self, task_id: str, trace: LLMTrace) -> None:
        with self._lock:
            self._llm_traces_by_task[task_id].append(trace)

    def record_execution_result(
        self,
        *,
        task_id: str,
        tenant_id: str,
        node_id: str,
        agent_id: str | None,
        result: ExecutionResult,
    ) -> None:
        trace_id = self.new_trace_id()
        self.record_event(
            EventRecord(
                trace_id=trace_id,
                span_id=self.new_span_id(),
                tenant_id=tenant_id,
                task_id=task_id,
                node_id=node_id,
                agent_id=agent_id,
                event_type="node_result",
                payload=result.to_dict(),
            )
        )
        for trace in result.llm_traces:
            self.record_llm_trace(task_id, trace)

    def get_events(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return [e.to_dict() for e in self._events_by_task.get(task_id, [])]

    def get_llm_traces(self, task_id: str) -> list[dict[str, Any]]:
        with self._lock:
            traces = list(self._llm_traces_by_task.get(task_id, []))
        return [
            {
                "trace_id": t.trace_id,
                "prompt": t.prompt,
                "response": t.response,
                "model": t.model,
                "metadata": dict(t.metadata),
                "created_at": t.created_at.isoformat(),
            }
            for t in traces
        ]
