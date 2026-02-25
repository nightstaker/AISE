from __future__ import annotations

from aise.runtime.models import (
    CapabilityKind,
    ExecutionResult,
    ExecutionStatus,
    Principal,
    RuntimeTask,
    RuntimeTaskStatus,
    ToolCallRecord,
)
from aise.runtime.observability import EventRecord, ObservabilityCenter
from aise.runtime.reports import ReportEngine


def test_report_engine_generate() -> None:
    task = RuntimeTask(
        principal=Principal(user_id="u1", tenant_id="t1", roles=["Admin"]),
        prompt="x",
        status=RuntimeTaskStatus.COMPLETED,
    )
    r1 = ExecutionResult(
        node_id="n1", status=ExecutionStatus.SUCCESS, artifacts=[{"uri": "a"}], metrics={"duration_ms": 10}
    )
    r1.tool_calls = [ToolCallRecord(name="tool1", kind=CapabilityKind.TOOL, status=ExecutionStatus.SUCCESS)]
    r1.finish()
    r2 = ExecutionResult(
        node_id="n2", status=ExecutionStatus.FAILED, metrics={"duration_ms": 20, "token_in": 3, "token_out": 5}
    )
    r2.finish()
    task.node_results = {"n1": r1, "n2": r2}
    obs = ObservabilityCenter()
    obs.record_event(EventRecord(trace_id="tr1", span_id="sp1", task_id=task.task_id, event_type="node_retry"))
    report = ReportEngine().generate(task, obs)
    assert report["summary"]["total_nodes"] == 2
    assert report["summary"]["retried_nodes"] == 1
    assert report["efficiency"]["token_cost"] == 8
