from __future__ import annotations

import pytest

from aise.runtime.models import TaskNode, TaskPlan
from aise.runtime.schema import TASK_PLAN_JSON_SCHEMA, validate_task_plan, validate_task_plan_payload


def test_task_plan_json_schema_shape() -> None:
    assert TASK_PLAN_JSON_SCHEMA["type"] == "object"
    assert "tasks" in TASK_PLAN_JSON_SCHEMA["properties"]


def test_validate_task_plan_object() -> None:
    plan = TaskPlan(task_name="p", tasks=[TaskNode(id="t1", name="n1")])
    validate_task_plan(plan)


def test_validate_task_plan_payload_rejects_bad_strategy() -> None:
    with pytest.raises(Exception):
        validate_task_plan_payload({"task_name": "p", "tasks": [{"id": "t1", "name": "n1"}], "strategy": []})
