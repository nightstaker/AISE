"""Execution engine for dispatching task nodes to worker agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from ..utils.logging import get_logger
from .exceptions import ExecutionError
from .memory import InMemoryMemoryManager
from .models import ExecutionResult, ExecutionStatus, RuntimeTask, TaskNode
from .observability import EventRecord, ObservabilityCenter
from .recovery import RecoveryManager
from .registry import WorkerRegistry

logger = get_logger(__name__)


@dataclass(slots=True)
class ExecutionContext:
    task: RuntimeTask
    memory_summary: str = ""
    memory_details: list[dict[str, Any]] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


class ExecutionEngine:
    """Dispatches task nodes to workers, with retry and observability."""

    def __init__(
        self,
        *,
        worker_registry: WorkerRegistry,
        memory_manager: InMemoryMemoryManager,
        observability: ObservabilityCenter,
        recovery_manager: RecoveryManager,
    ) -> None:
        self.worker_registry = worker_registry
        self.memory_manager = memory_manager
        self.observability = observability
        self.recovery_manager = recovery_manager
        self._rr_index_by_type: dict[str, int] = {}
        self._lock = RLock()

    def execute_node(self, node: TaskNode, context: ExecutionContext) -> ExecutionResult:
        task = context.task
        worker = self._select_worker(node.assigned_agent_type)
        logger.info(
            "Node execution started: task_id=%s task_name=%s node_id=%s node_name=%s worker_id=%s worker_type=%s",
            task.task_id,
            task.task_name or "-",
            node.id,
            node.name,
            getattr(worker, "adapter_id", None),
            getattr(worker, "agent_type", None),
        )
        trace_id = self.observability.new_trace_id()
        self.observability.record_event(
            EventRecord(
                trace_id=trace_id,
                span_id=self.observability.new_span_id(),
                tenant_id=task.principal.tenant_id,
                task_id=task.task_id,
                node_id=node.id,
                agent_id=getattr(worker, "adapter_id", None),
                event_type="node_started",
                payload={
                    "node": node.to_dict(),
                    "worker_id": getattr(worker, "adapter_id", None),
                    "worker_type": getattr(worker, "agent_type", None),
                },
            )
        )

        def _run() -> ExecutionResult:
            process_context = None
            process_step_context = None
            effective_agent_requirements: list[str] = []
            if task.plan is not None and isinstance(task.plan.metadata, dict):
                process_context = task.plan.metadata.get("process_context")
            if isinstance(node.metadata, dict):
                process_step_context = node.metadata.get("process_step")
                effective_agent_requirements = list(node.metadata.get("effective_agent_requirements", []) or [])
            worker_context = {
                "task_id": task.task_id,
                "tenant_id": task.principal.tenant_id,
                "user_id": task.principal.user_id,
                "memory_summary": context.memory_summary,
                "memory_details": context.memory_details,
                "task_constraints": task.constraints,
                "task_metadata": task.metadata,
                "process_context": process_context,
                "process_step_context": process_step_context,
                "effective_agent_requirements": effective_agent_requirements,
                **context.extra,
            }
            return worker.execute_task(node, worker_context)

        try:
            result = self.recovery_manager.run_with_retry(
                _run,
                operation_name=f"node:{node.id}",
                on_retry=lambda attempt, exc: self.observability.record_event(
                    EventRecord(
                        trace_id=trace_id,
                        span_id=self.observability.new_span_id(),
                        tenant_id=task.principal.tenant_id,
                        task_id=task.task_id,
                        node_id=node.id,
                        agent_id=getattr(worker, "adapter_id", None),
                        event_type="node_retry",
                        payload={"attempt": attempt, "error": str(exc)},
                    )
                ),
            )
        except Exception as exc:
            logger.exception("Node execution exception: task=%s node=%s error=%s", task.task_id, node.id, exc)
            result = ExecutionResult(
                node_id=node.id,
                status=ExecutionStatus.FAILED,
                summary=f"Execution engine exception: {exc}",
                errors=[str(exc)],
                agent_id=getattr(worker, "adapter_id", None),
            )
            result.finish()

        if result.status not in {ExecutionStatus.SUCCESS, ExecutionStatus.FAILED, ExecutionStatus.PARTIAL}:
            raise ExecutionError(f"Invalid execution status for node {node.id}: {result.status}")

        logger.info(
            "Node execution finished: task_id=%s task_name=%s node_id=%s node_name=%s status=%s summary=%s",
            task.task_id,
            task.task_name or "-",
            node.id,
            node.name,
            result.status.value,
            result.summary,
        )

        self.observability.record_execution_result(
            task_id=task.task_id,
            tenant_id=task.principal.tenant_id,
            node_id=node.id,
            agent_id=result.agent_id,
            result=result,
        )
        return result

    def _select_worker(self, agent_type: str | None):
        candidates = self.worker_registry.list_by_type(agent_type) if agent_type else self.worker_registry.list_all()
        if not candidates:
            raise ExecutionError(f"No available worker for agent_type={agent_type!r}")
        with self._lock:
            idx = self._rr_index_by_type.get(agent_type or "*", 0)
            worker = candidates[idx % len(candidates)]
            self._rr_index_by_type[agent_type or "*"] = idx + 1
        return worker
