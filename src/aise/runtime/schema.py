"""JSON Schema and validation helpers for runtime task plans."""

from __future__ import annotations

from typing import Any

from .exceptions import PlanningError
from .models import TaskPlan

TASK_NODE_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["id", "name"],
    "properties": {
        "id": {"type": "string", "minLength": 1},
        "name": {"type": "string", "minLength": 1},
        "mode": {"type": "string", "enum": ["serial", "parallel"]},
        "assigned_agent_type": {"type": ["string", "null"]},
        "dependencies": {"type": "array", "items": {"type": "string"}},
        "priority": {"type": "string", "enum": ["high", "medium", "low"]},
        "input_data": {"type": "object"},
        "capability_hints": {"type": "array", "items": {"type": "string"}},
        "memory_policy": {"type": "object"},
        "success_criteria": {"type": "array", "items": {"type": "string"}},
        "children": {"type": "array", "items": {}},  # recursive; validated manually
        "metadata": {"type": "object"},
        "execute_self": {"type": "boolean"},
    },
    "additionalProperties": True,
}

TASK_PLAN_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "AgentRuntimeTaskPlan",
    "type": "object",
    "required": ["task_name", "tasks"],
    "properties": {
        "plan_id": {"type": "string"},
        "task_name": {"type": "string", "minLength": 1},
        "version": {"type": "integer", "minimum": 1},
        "strategy": {
            "type": "object",
            "properties": {
                "max_parallelism": {"type": "integer", "minimum": 1},
                "budget": {"type": "object"},
                "replan_policy": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "tasks": {"type": "array", "items": TASK_NODE_JSON_SCHEMA, "minItems": 1},
        "metadata": {"type": "object"},
    },
    "additionalProperties": True,
}


def validate_task_plan_payload(payload: dict[str, Any]) -> None:
    """Validate task plan payload without external dependencies.

    This is a structural validator aligned with ``TASK_PLAN_JSON_SCHEMA``.
    """

    if not isinstance(payload, dict):
        raise PlanningError("Task plan must be a JSON object")
    if not str(payload.get("task_name", "")).strip():
        raise PlanningError("Task plan requires non-empty 'task_name'")
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        raise PlanningError("Task plan requires non-empty 'tasks' array")
    strategy = payload.get("strategy", {})
    if strategy is not None and not isinstance(strategy, dict):
        raise PlanningError("'strategy' must be an object")
    if isinstance(strategy, dict):
        mp = strategy.get("max_parallelism")
        if mp is not None and (not isinstance(mp, int) or mp < 1):
            raise PlanningError("'strategy.max_parallelism' must be an integer >= 1")

    seen_ids: set[str] = set()
    _validate_nodes(tasks, path="tasks", global_seen_ids=seen_ids, parent_ids=None)


def validate_task_plan(plan: TaskPlan) -> None:
    validate_task_plan_payload(plan.to_dict())


def _validate_nodes(
    nodes: list[Any],
    *,
    path: str,
    global_seen_ids: set[str],
    parent_ids: set[str] | None,
) -> None:
    local_ids: set[str] = set()
    for idx, node in enumerate(nodes):
        node_path = f"{path}[{idx}]"
        if not isinstance(node, dict):
            raise PlanningError(f"{node_path} must be an object")
        node_id = str(node.get("id", "")).strip()
        node_name = str(node.get("name", "")).strip()
        if not node_id:
            raise PlanningError(f"{node_path}.id is required")
        if not node_name:
            raise PlanningError(f"{node_path}.name is required")
        if node_id in global_seen_ids:
            raise PlanningError(f"Duplicate task node id: {node_id}")
        global_seen_ids.add(node_id)
        local_ids.add(node_id)

        mode = node.get("mode", "serial")
        if mode not in {"serial", "parallel"}:
            raise PlanningError(f"{node_path}.mode must be 'serial' or 'parallel'")

        priority = node.get("priority", "medium")
        if priority not in {"high", "medium", "low"}:
            raise PlanningError(f"{node_path}.priority must be high/medium/low")

        for field_name in ("dependencies", "capability_hints", "success_criteria"):
            value = node.get(field_name, [])
            if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
                raise PlanningError(f"{node_path}.{field_name} must be an array of strings")

        for field_name in ("input_data", "memory_policy", "metadata"):
            value = node.get(field_name, {})
            if value is not None and not isinstance(value, dict):
                raise PlanningError(f"{node_path}.{field_name} must be an object")

        children = node.get("children", [])
        if not isinstance(children, list):
            raise PlanningError(f"{node_path}.children must be an array")
        if children:
            _validate_nodes(
                children,
                path=f"{node_path}.children",
                global_seen_ids=global_seen_ids,
                parent_ids=None,
            )

    # dependencies are validated against siblings for each level
    current_level_ids = set(local_ids)
    if parent_ids:
        current_level_ids |= set(parent_ids)
    for idx, node in enumerate(nodes):
        node_path = f"{path}[{idx}]"
        deps = node.get("dependencies", [])
        for dep in deps:
            if dep not in current_level_ids:
                raise PlanningError(
                    f"{node_path}.dependencies contains unknown node id '{dep}' in current execution level"
                )
