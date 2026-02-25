from __future__ import annotations

from aise.runtime.memory import InMemoryMemoryManager
from aise.runtime.models import ExecutionResult, ExecutionStatus


def test_memory_manager_create_store_retrieve_and_load() -> None:
    mm = InMemoryMemoryManager()
    r1 = mm.create(
        tenant_id="t1",
        user_id="u1",
        scope="task",
        memory_type="summary",
        summary="runtime scheduler retry strategy",
        topic_tags=["runtime", "scheduler"],
        importance=0.9,
    )
    r2 = mm.create(
        tenant_id="t1",
        user_id="u1",
        scope="task",
        memory_type="summary",
        summary="other topic",
        topic_tags=["other"],
        importance=0.2,
    )
    summaries = mm.retrieve_summaries(tenant_id="t1", query_text="scheduler retry", top_k=1)
    assert summaries[0].memory_id == r1.memory_id
    details = mm.load_details([r1.memory_id, "missing"])
    assert [x.memory_id for x in details] == [r1.memory_id]
    summary_text = mm.summarize_records([r1, r2])
    assert r1.memory_id in summary_text and "runtime scheduler" in summary_text


def test_memory_manager_store_updates_version() -> None:
    mm = InMemoryMemoryManager()
    rec = mm.create(
        tenant_id="t1",
        user_id="u1",
        scope="task",
        memory_type="summary",
        summary="v1",
    )
    rec.summary = "v2"
    mm.store(rec)
    stored = mm.load_details([rec.memory_id])[0]
    assert stored.version >= 2


def test_write_execution_memory() -> None:
    mm = InMemoryMemoryManager()
    result = ExecutionResult(node_id="n1", status=ExecutionStatus.SUCCESS, summary="done")
    result.finish()
    mem = mm.write_execution_memory(
        tenant_id="t1",
        user_id="u1",
        task_id="task1",
        node_id="n1",
        result=result,
        topic_tags=["design"],
    )
    assert "task_execution" in mem.topic_tags
    assert mem.detail["node_id"] == "n1"
