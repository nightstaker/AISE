from __future__ import annotations

from aise.runtime.models import (
    CapabilityKind,
    CapabilitySpec,
    ExecutionResult,
    ExecutionStatus,
    LLMTrace,
    MemoryRecord,
    PlanStrategy,
    Principal,
    RuntimeTask,
    RuntimeTaskStatus,
    TaskMode,
    TaskNode,
    TaskPlan,
    ToolCallRecord,
)


def test_capability_spec_and_plan_strategy_to_dict() -> None:
    spec = CapabilitySpec(
        capability_id="skill.test",
        name="test",
        kind=CapabilityKind.SKILL,
        description="desc",
        tags=["a"],
    )
    assert spec.to_dict()["kind"] == "skill"
    strategy = PlanStrategy(max_parallelism=2, budget={"tokens": 1}, replan_policy="x")
    assert strategy.to_dict()["max_parallelism"] == 2


def test_task_node_and_task_plan_roundtrip() -> None:
    node = TaskNode(
        id="t1",
        name="root",
        mode=TaskMode.PARALLEL,
        children=[TaskNode(id="t1.1", name="child")],
    )
    plan = TaskPlan(task_name="demo", tasks=[node])
    payload = plan.to_dict()
    restored = TaskPlan.from_dict(payload)
    assert restored.task_name == "demo"
    assert restored.tasks[0].mode == TaskMode.PARALLEL
    assert restored.tasks[0].children[0].id == "t1.1"


def test_execution_result_finish_and_to_dict() -> None:
    trace = LLMTrace(trace_id="lt1", prompt="p", response="r")
    call = ToolCallRecord(name="tool", kind=CapabilityKind.TOOL, status=ExecutionStatus.SUCCESS)
    result = ExecutionResult(
        node_id="n1",
        status=ExecutionStatus.SUCCESS,
        llm_traces=[trace],
        tool_calls=[call],
        agent_id="w1",
    )
    result.finish()
    payload = result.to_dict()
    assert payload["status"] == "success"
    assert payload["llm_traces"] == ["lt1"]
    assert payload["tool_calls"][0]["kind"] == "tool"
    assert payload["finished_at"] is not None


def test_memory_record_new_and_runtime_task_to_dict() -> None:
    mem = MemoryRecord.new(
        tenant_id="t1",
        user_id="u1",
        scope="task",
        memory_type="summary",
        summary="abc",
        topic_tags=["x"],
    )
    assert mem.memory_id.startswith("mem_")
    task = RuntimeTask(
        principal=Principal(user_id="u1", tenant_id="t1", roles=["Admin"]),
        prompt="hello",
        status=RuntimeTaskStatus.CREATED,
    )
    task_dict = task.to_dict()
    assert task_dict["status"] == "created"
    assert task_dict["tenant_id"] == "t1"
