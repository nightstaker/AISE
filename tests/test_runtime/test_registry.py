from __future__ import annotations

from aise.runtime.agents import WorkerAgent
from aise.runtime.models import CapabilityKind
from aise.runtime.registry import CapabilityQuery, CapabilityRegistry, WorkerRegistry


def test_capability_registry_register_query_execute() -> None:
    reg = CapabilityRegistry()
    reg.register_callable(
        capability_id="tool.echo",
        name="echo",
        kind=CapabilityKind.TOOL,
        description="Echo",
        func=lambda input_data, context: {"echo": input_data, "ctx": context},
        tags=["echo", "util"],
        owner_agent_types=["generic_worker"],
        permissions=["x"],
    )
    specs = reg.query(CapabilityQuery(tags=["echo"], owner_agent_type="generic_worker"))
    assert len(specs) == 1
    out = reg.execute("tool.echo", {"a": 1}, {"b": 2})
    assert out["echo"] == {"a": 1}
    assert out["ctx"] == {"b": 2}
    assert reg.get_spec("tool.echo") is not None
    assert reg.get_handler("tool.echo") is not None


def test_worker_registry_register_list_and_scan_capabilities() -> None:
    worker = WorkerAgent(adapter_id="w1", agent_type="generic_worker")
    worker.register_skill(
        capability_id="skill.s1",
        name="s1",
        description="s1",
        func=lambda input_data, context: {"output": {}},
        tags=["a"],
    )
    wr = WorkerRegistry()
    wr.register(worker)
    assert wr.get("w1") is worker
    assert wr.list_by_type("generic_worker") == [worker]
    scan = wr.scan_capabilities()
    assert "w1" in scan and len(scan["w1"]) == 1
