from __future__ import annotations

from dataclasses import dataclass

import pytest

from aise.runtime.exceptions import ExecutionError
from aise.runtime.executor import ExecutionContext, ExecutionEngine
from aise.runtime.memory import InMemoryMemoryManager
from aise.runtime.models import ExecutionResult, ExecutionStatus, Principal, RuntimeTask, TaskNode
from aise.runtime.observability import ObservabilityCenter
from aise.runtime.recovery import RecoveryManager, RetryPolicy
from aise.runtime.registry import WorkerRegistry


@dataclass
class StubWorker:
    adapter_id: str
    agent_type: str
    language: str = "python"
    mode: str = "success"
    calls: int = 0

    def discover_capabilities(self):
        return []

    def health_check(self):
        return {"status": "ok"}

    def cancel(self, task_id: str, node_id: str) -> bool:
        return False

    def execute_task(self, node: TaskNode, context: dict):
        self.calls += 1
        if self.mode == "retry_then_success":
            if self.calls == 1:
                raise RuntimeError("transient")
        if self.mode == "invalid_status":
            return ExecutionResult(node_id=node.id, status=ExecutionStatus.RUNNING)
        if self.mode == "raise":
            raise RuntimeError("boom")
        result = ExecutionResult(
            node_id=node.id, status=ExecutionStatus.SUCCESS, summary="ok", agent_id=self.adapter_id
        )
        result.finish()
        return result


def _task() -> RuntimeTask:
    return RuntimeTask(principal=Principal(user_id="u1", tenant_id="t1", roles=["Admin"]), prompt="x")


def test_execution_engine_execute_node_success_and_retry(monkeypatch) -> None:
    monkeypatch.setattr("aise.runtime.recovery.time.sleep", lambda *_a, **_k: None)
    monkeypatch.setattr("aise.runtime.recovery.random.uniform", lambda *_a, **_k: 0.0)
    wr = WorkerRegistry()
    worker = StubWorker(adapter_id="w1", agent_type="generic_worker", mode="retry_then_success")
    wr.register(worker)
    engine = ExecutionEngine(
        worker_registry=wr,
        memory_manager=InMemoryMemoryManager(),
        observability=ObservabilityCenter(),
        recovery_manager=RecoveryManager(RetryPolicy(max_attempts=2, base_delay_sec=0, jitter_sec=0)),
    )
    ctx = ExecutionContext(task=_task())
    node = TaskNode(id="n1", name="n1", assigned_agent_type="generic_worker")
    result = engine.execute_node(node, ctx)
    assert result.status == ExecutionStatus.SUCCESS
    assert worker.calls == 2
    events = engine.observability.get_events(ctx.task.task_id)
    assert any(e["event_type"] == "node_retry" for e in events)


def test_execution_engine_injects_process_context_to_worker() -> None:
    captured = {}

    @dataclass
    class CaptureWorker(StubWorker):
        def execute_task(self, node: TaskNode, context: dict):
            captured.update(context)
            result = ExecutionResult(
                node_id=node.id, status=ExecutionStatus.SUCCESS, summary="ok", agent_id=self.adapter_id
            )
            result.finish()
            return result

    wr = WorkerRegistry()
    worker = CaptureWorker(adapter_id="w1", agent_type="generic_worker")
    wr.register(worker)
    engine = ExecutionEngine(
        worker_registry=wr,
        memory_manager=InMemoryMemoryManager(),
        observability=ObservabilityCenter(),
        recovery_manager=RecoveryManager(RetryPolicy(max_attempts=1)),
    )
    task = _task()
    task.plan = type("PlanLike", (), {"metadata": {"process_context": {"process_id": "p1"}}})()
    node = TaskNode(
        id="n1",
        name="n1",
        assigned_agent_type="generic_worker",
        metadata={
            "process_step": {"step_id": "s1", "name": "step1"},
            "effective_agent_requirements": ["output_format: json"],
        },
    )
    engine.execute_node(node, ExecutionContext(task=task))
    assert captured["process_context"]["process_id"] == "p1"
    assert captured["process_step_context"]["step_id"] == "s1"
    assert captured["effective_agent_requirements"] == ["output_format: json"]


def test_execution_engine_invalid_status_raises() -> None:
    wr = WorkerRegistry()
    wr.register(StubWorker(adapter_id="w1", agent_type="generic_worker", mode="invalid_status"))
    engine = ExecutionEngine(
        worker_registry=wr,
        memory_manager=InMemoryMemoryManager(),
        observability=ObservabilityCenter(),
        recovery_manager=RecoveryManager(RetryPolicy(max_attempts=1)),
    )
    with pytest.raises(ExecutionError):
        engine.execute_node(
            TaskNode(id="n1", name="n1", assigned_agent_type="generic_worker"), ExecutionContext(task=_task())
        )


def test_execution_engine_select_worker_round_robin_and_no_worker() -> None:
    wr = WorkerRegistry()
    w1 = StubWorker(adapter_id="w1", agent_type="t")
    w2 = StubWorker(adapter_id="w2", agent_type="t")
    wr.register(w1)
    wr.register(w2)
    engine = ExecutionEngine(
        worker_registry=wr,
        memory_manager=InMemoryMemoryManager(),
        observability=ObservabilityCenter(),
        recovery_manager=RecoveryManager(RetryPolicy(max_attempts=1)),
    )
    assert engine._select_worker("t").adapter_id == "w1"
    assert engine._select_worker("t").adapter_id == "w2"
    empty_engine = ExecutionEngine(
        worker_registry=WorkerRegistry(),
        memory_manager=InMemoryMemoryManager(),
        observability=ObservabilityCenter(),
        recovery_manager=RecoveryManager(RetryPolicy(max_attempts=1)),
    )
    with pytest.raises(ExecutionError):
        empty_engine._select_worker("missing")
