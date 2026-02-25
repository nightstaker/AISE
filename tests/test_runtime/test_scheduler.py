from __future__ import annotations

import pytest

from aise.runtime.exceptions import SchedulingError
from aise.runtime.models import ExecutionResult, ExecutionStatus, TaskMode, TaskNode, TaskPlan
from aise.runtime.scheduler import TaskScheduler


def _executor(node: TaskNode) -> ExecutionResult:
    status = ExecutionStatus.FAILED if node.metadata.get("force_fail") else ExecutionStatus.SUCCESS
    r = ExecutionResult(node_id=node.id, status=status, summary=node.name)
    r.finish()
    return r


def test_scheduler_executes_serial_and_nested_children() -> None:
    scheduler = TaskScheduler()
    plan = TaskPlan(
        task_name="p",
        tasks=[
            TaskNode(
                id="g1",
                name="group",
                mode=TaskMode.SERIAL,
                execute_self=False,
                children=[
                    TaskNode(id="g1.1", name="c1"),
                    TaskNode(id="g1.2", name="c2", dependencies=["g1.1"]),
                ],
            ),
            TaskNode(id="t2", name="final", dependencies=["g1"]),
        ],
    )
    outcome = scheduler.execute_plan(plan, _executor)
    assert outcome.all_success is True
    assert {"g1", "g1.1", "g1.2", "t2"} <= set(outcome.results)


def test_scheduler_reports_failed_nodes() -> None:
    scheduler = TaskScheduler()
    plan = TaskPlan(task_name="p", tasks=[TaskNode(id="t1", name="n1", metadata={"force_fail": True})])
    outcome = scheduler.execute_plan(plan, _executor)
    assert outcome.all_success is False
    assert outcome.failed_node_ids == ["t1"]


def test_scheduler_rejects_duplicate_or_missing_dependencies() -> None:
    scheduler = TaskScheduler()
    dup_plan = TaskPlan(task_name="p", tasks=[TaskNode(id="t1", name="a"), TaskNode(id="t1", name="b")])
    with pytest.raises(SchedulingError):
        scheduler.execute_plan(dup_plan, _executor)
    missing_dep_plan = TaskPlan(task_name="p", tasks=[TaskNode(id="t2", name="b", dependencies=["x"])])
    with pytest.raises(SchedulingError):
        scheduler.execute_plan(missing_dep_plan, _executor)
