from __future__ import annotations

from aise.runtime.models import ExecutionResult, ExecutionStatus, LLMTrace
from aise.runtime.observability import EventRecord, ObservabilityCenter


def test_observability_records_events_and_llm_traces() -> None:
    obs = ObservabilityCenter()
    event = EventRecord(trace_id=obs.new_trace_id(), span_id=obs.new_span_id(), task_id="t1", event_type="started")
    obs.record_event(event)
    trace = LLMTrace(trace_id="lt1", prompt="p", response="r")
    obs.record_llm_trace("t1", trace)
    events = obs.get_events("t1")
    traces = obs.get_llm_traces("t1")
    assert len(events) == 1
    assert events[0]["event_type"] == "started"
    assert traces[0]["trace_id"] == "lt1"


def test_observability_record_execution_result_adds_node_result_and_traces() -> None:
    obs = ObservabilityCenter()
    result = ExecutionResult(
        node_id="n1",
        status=ExecutionStatus.SUCCESS,
        llm_traces=[LLMTrace(trace_id="lt2", prompt="p2", response="r2")],
    )
    result.finish()
    obs.record_execution_result(task_id="task1", tenant_id="ten1", node_id="n1", agent_id="w1", result=result)
    events = obs.get_events("task1")
    assert any(e["event_type"] == "node_result" for e in events)
    assert obs.get_llm_traces("task1")[0]["trace_id"] == "lt2"
