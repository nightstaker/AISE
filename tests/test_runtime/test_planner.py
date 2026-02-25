from __future__ import annotations

import pytest

from aise.runtime.agents import build_default_worker
from aise.runtime.exceptions import PlanningError
from aise.runtime.models import Principal, RuntimeTask, TaskNode, TaskPlan
from aise.runtime.planner import HeuristicTaskPlanner, PlannerContext
from aise.runtime.registry import WorkerRegistry


def _planner_context() -> PlannerContext:
    wr = WorkerRegistry()
    wr.register(build_default_worker())
    return PlannerContext(worker_registry=wr, memory_summaries=[])


def test_planner_generate_plan_default() -> None:
    task = RuntimeTask(principal=Principal(user_id="u1", tenant_id="t1", roles=["Admin"]), prompt="设计 runtime")
    with pytest.raises(PlanningError):
        HeuristicTaskPlanner().generate_plan(task, _planner_context())


def test_planner_generate_plan_override_validated() -> None:
    task = RuntimeTask(
        principal=Principal(user_id="u1", tenant_id="t1", roles=["Admin"]),
        prompt="x",
        constraints={"task_plan": {"task_name": "override", "tasks": [{"id": "t1", "name": "n1"}]}},
    )
    plan = HeuristicTaskPlanner().generate_plan(task, _planner_context())
    assert plan.task_name == "override"


def test_planner_replan_appends_fallback_once() -> None:
    planner = HeuristicTaskPlanner()
    task = RuntimeTask(principal=Principal(user_id="u1", tenant_id="t1", roles=["Admin"]), prompt="x")
    plan = TaskPlan(task_name="p", tasks=[TaskNode(id="t1", name="n1", capability_hints=["a"])])
    replanned = planner.replan(task=task, current_plan=plan, failed_node_ids=["t1"], context=_planner_context())
    assert replanned is None


def test_planner_replan_respects_policy() -> None:
    planner = HeuristicTaskPlanner()
    task = RuntimeTask(principal=Principal(user_id="u1", tenant_id="t1", roles=["Admin"]), prompt="x")
    plan = TaskPlan(task_name="p", tasks=[TaskNode(id="t1", name="n1")])
    plan.strategy.replan_policy = "never"
    assert planner.replan(task=task, current_plan=plan, failed_node_ids=["t1"], context=_planner_context()) is None
