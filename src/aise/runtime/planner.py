"""Task planning and replanning logic for the Master Agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..utils.logging import get_logger
from .exceptions import PlanningError
from .models import RuntimeTask, TaskPlan
from .process import ProcessDefinition
from .registry import WorkerRegistry
from .schema import validate_task_plan_payload

logger = get_logger(__name__)


@dataclass(slots=True)
class PlannerContext:
    worker_registry: WorkerRegistry
    memory_summaries: list[dict[str, Any]]
    selected_process: ProcessDefinition | None = None
    planning_prompt: str = ""


class HeuristicTaskPlanner:
    """Planner adapter.

    Project policy: heuristic fallback planning is forbidden.
    This class only validates caller-provided plan overrides and process-based
    node augmentation helpers. It must not synthesize plans heuristically.
    """

    def generate_plan(self, task: RuntimeTask, context: PlannerContext) -> TaskPlan:
        override = task.constraints.get("task_plan")
        if isinstance(override, dict):
            logger.info("Using caller-provided plan override: task_id=%s", task.task_id)
            validate_task_plan_payload(override)
            return TaskPlan.from_dict(override)
        raise PlanningError("Heuristic fallback planning is forbidden. Master Agent must use LLM-generated task plans.")

    def replan(
        self,
        *,
        task: RuntimeTask,
        current_plan: TaskPlan,
        failed_node_ids: list[str],
        context: PlannerContext,
    ) -> TaskPlan | None:
        # No heuristic fallback re-planning. Replanning must be LLM-driven.
        return None

    def _generate_plan_from_process(
        self,
        task: RuntimeTask,
        process: ProcessDefinition,
        selected_primary: str,
        worker_types: list[str],
        context: PlannerContext,
    ) -> TaskPlan:
        raise NotImplementedError("Heuristic process-to-plan synthesis is forbidden by project policy.")
