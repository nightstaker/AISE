"""Tests for the new Agent Runtime package."""

from __future__ import annotations

import pytest

from aise.runtime import validate_task_plan_payload
from aise.runtime.exceptions import PlanningError
from aise.runtime.models import Principal


def _admin_principal() -> Principal:
    return Principal(user_id="u-test", tenant_id="t-test", roles=["Admin"])


def test_runtime_submit_and_execute_sync(runtime_factory) -> None:
    runtime = runtime_factory()
    principal = _admin_principal()

    task_id = runtime.submit_task(
        prompt="设计一个简单 Agent Runtime 并汇总结果",
        principal=principal,
        run_sync=True,
    )

    status = runtime.get_task_status(task_id, principal=principal)
    result = runtime.get_task_result(task_id, principal=principal)
    report = runtime.get_task_report(task_id, principal=principal)
    logs = runtime.get_task_logs(task_id, principal=principal)

    assert status["status"] == "completed"
    assert result["status"] == "completed"
    assert report["summary"]["status"] == "completed"
    assert result["node_results"]
    assert len(logs) >= 3


def test_task_plan_validation_accepts_nested_parallel_plan() -> None:
    payload = {
        "task_name": "nested plan",
        "strategy": {"max_parallelism": 2},
        "tasks": [
            {
                "id": "t1",
                "name": "group",
                "mode": "parallel",
                "execute_self": False,
                "children": [
                    {"id": "t1.1", "name": "child1"},
                    {"id": "t1.2", "name": "child2", "dependencies": ["t1.1"]},
                ],
            },
            {"id": "t2", "name": "final", "dependencies": ["t1"]},
        ],
    }
    validate_task_plan_payload(payload)


@pytest.mark.parametrize(
    "payload,error_contains",
    [
        ({"tasks": []}, "task_name"),
        ({"task_name": "x", "tasks": []}, "tasks"),
        (
            {"task_name": "x", "tasks": [{"id": "t1", "name": "n1"}, {"id": "t1", "name": "n2"}]},
            "Duplicate",
        ),
        (
            {"task_name": "x", "tasks": [{"id": "t1", "name": "n1", "dependencies": ["missing"]}]},
            "unknown node id",
        ),
    ],
)
def test_task_plan_validation_rejects_invalid_payload(payload, error_contains: str) -> None:
    with pytest.raises(PlanningError) as exc:
        validate_task_plan_payload(payload)
    assert error_contains.lower() in str(exc.value).lower()


def test_runtime_respects_plan_override(runtime_factory) -> None:
    runtime = runtime_factory()
    principal = _admin_principal()
    plan = {
        "task_name": "override plan",
        "tasks": [
            {
                "id": "n1",
                "name": "Analyze",
                "assigned_agent_type": "generic_worker",
                "capability_hints": ["analyze"],
            },
            {
                "id": "n2",
                "name": "Finalize",
                "assigned_agent_type": "generic_worker",
                "dependencies": ["n1"],
                "capability_hints": ["summarize"],
            },
        ],
    }
    task_id = runtime.submit_task(
        prompt="ignore planner default and use supplied plan",
        principal=principal,
        constraints={"task_plan": plan},
        run_sync=True,
    )
    task = runtime.get_task(task_id, principal=principal)
    assert task["plan"]["task_name"] == "override plan"
    assert set(task["node_results"].keys()) == {"n1", "n2"}
