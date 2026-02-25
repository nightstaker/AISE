from __future__ import annotations

from aise.runtime.interfaces import CapabilityHandler, LLMRecorder
from aise.runtime.models import CapabilityKind, CapabilitySpec, LLMTrace


def test_capability_handler_calls_wrapped_function() -> None:
    called = {}

    def fn(input_data, context):
        called["input"] = dict(input_data)
        called["ctx"] = dict(context)
        return {"ok": True}

    spec = CapabilitySpec(
        capability_id="tool.x",
        name="x",
        kind=CapabilityKind.TOOL,
        description="test",
    )
    handler = CapabilityHandler(spec=spec, func=fn)
    out = handler({"a": 1}, {"b": 2})
    assert out == {"ok": True}
    assert called["input"] == {"a": 1}
    assert called["ctx"] == {"b": 2}


def test_llm_recorder_records_trace() -> None:
    recorder = LLMRecorder()
    trace = LLMTrace(trace_id="t1", prompt="p", response="r")
    recorder.record(trace)
    assert recorder.traces == [trace]
