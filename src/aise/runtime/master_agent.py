"""Master agent implementation for runtime planning and orchestration logic."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..utils.logging import get_logger
from .exceptions import PlanningError
from .interfaces import LLMClientProtocol
from .memory import InMemoryMemoryManager
from .models import ExecutionResult, ExecutionStatus, RuntimeTask, TaskNode, TaskPlan
from .planner import HeuristicTaskPlanner, PlannerContext
from .process import ProcessRepository
from .registry import WorkerRegistry

logger = get_logger(__name__)


@dataclass(slots=True)
class MasterAgent:
    """Master agent: planning, memory retrieval, re-planning, and summarization."""

    worker_registry: WorkerRegistry
    memory_manager: InMemoryMemoryManager
    planner: HeuristicTaskPlanner = field(default_factory=HeuristicTaskPlanner)
    process_repository: ProcessRepository = field(default_factory=ProcessRepository)
    llm_client: LLMClientProtocol | None = None

    def scan_workers(self) -> dict[str, list[dict[str, Any]]]:
        scan = self.worker_registry.scan_capabilities()
        return {wid: [spec.to_dict() for spec in specs] for wid, specs in scan.items()}

    def scan_processes(self) -> list[dict[str, Any]]:
        return self.process_repository.summaries()

    def retrieve_relevant_memory(self, task: RuntimeTask) -> tuple[list[dict[str, Any]], str]:
        summaries = self.memory_manager.retrieve_summaries(
            tenant_id=task.principal.tenant_id,
            user_id=task.principal.user_id,
            query_text=task.prompt,
            top_k=5,
        )
        summary_text = self.memory_manager.summarize_records(summaries)
        return [rec.to_dict() for rec in summaries], summary_text

    def select_process_for_task(self, task: RuntimeTask):
        # Project policy forbids heuristic fallback matching in runtime planning.
        raise PlanningError("Heuristic process matching is forbidden. Use LLM planning inference output.")

    def build_planning_prompt(
        self,
        *,
        task: RuntimeTask,
        memory_summary_text: str,
        process_summaries: list[dict[str, Any]],
    ) -> str:
        worker_caps = self.scan_workers()
        lines = [
            "You are Master Agent. Perform process matching and task planning in ONE inference.",
            "Instruction: If there is a matching process, generate the task plan according to that process.",
            "Instruction: If no process matches, generate the task plan directly "
            "based on the task prompt and capabilities.",
            f"User task prompt: {task.prompt}",
            f"Task constraints: {task.constraints}",
            "Relevant memory summaries:",
            memory_summary_text or "(none)",
            "Available worker capabilities:",
        ]
        for worker_id, caps in worker_caps.items():
            cap_names = [str(item.get("name", "")) for item in caps]
            lines.append(f"- {worker_id}: {', '.join(cap_names) if cap_names else '(none)'}")
        lines.append("Available process summaries:")
        for item in process_summaries:
            lines.append(f"- {item['process_id']} | work_type={item['work_type']} | summary={item['summary']}")
        lines.append("Output expectation: choose one process_id or none, then produce a JSON task plan.")
        return "\n".join(lines)

    def _single_inference_match_and_plan(
        self,
        *,
        task: RuntimeTask,
        memory_summaries: list[dict[str, Any]],
        memory_summary_text: str,
    ) -> tuple[Any | None, TaskPlan, dict[str, Any]]:
        process_summaries = self.scan_processes()
        planning_prompt = self.build_planning_prompt(
            task=task,
            memory_summary_text=memory_summary_text,
            process_summaries=process_summaries,
        )

        if self.llm_client is None:
            raise PlanningError(
                "MasterAgent requires an llm_client for process matching and task planning. "
                "Heuristic fallback is forbidden in this project."
            )
        try:
            llm_response_text = self.llm_client.complete(planning_prompt)
        except Exception as exc:  # pragma: no cover - defensive
            raise PlanningError(f"Planning inference failed: {exc}") from exc

        process_selection, plan = self._parse_planning_inference_response(
            llm_response_text=llm_response_text,
            task=task,
            process_summaries=process_summaries,
        )
        if process_selection is not None:
            planning_prompt = (
                planning_prompt
                + "\n\nSelected process specification (matched by planning inference):\n"
                + process_selection.process.render_for_prompt()
            )
            self._attach_process_context_to_plan(plan, process_selection.process)
        plan_meta = {
            "planning_inference": {
                "mode": "single_inference",
                "prompt": planning_prompt,
                "response": llm_response_text,
            },
            "process_match": process_selection.to_dict() if process_selection else None,
            "process_summaries": process_summaries,
        }
        return process_selection, plan, plan_meta

    def _parse_planning_inference_response(
        self,
        *,
        llm_response_text: str,
        task: RuntimeTask,
        process_summaries: list[dict[str, Any]],
    ):
        try:
            payload = json.loads(llm_response_text)
        except json.JSONDecodeError as exc:
            raise PlanningError(f"Planning inference must return JSON. parse_error={exc}") from exc
        if not isinstance(payload, dict):
            raise PlanningError("Planning inference JSON root must be an object")
        plan_payload = payload.get("task_plan")
        if not isinstance(plan_payload, dict):
            raise PlanningError("Planning inference JSON must include object field 'task_plan'")
        plan = TaskPlan.from_dict(plan_payload)
        selected_process_id = payload.get("selected_process_id")
        process_selection = None
        if selected_process_id is not None and str(selected_process_id).strip().lower() not in {"", "none", "null"}:
            process = self.process_repository.get_process(str(selected_process_id).strip())
            if process is None:
                raise PlanningError(f"Planning inference selected unknown process_id: {selected_process_id}")
            from .process import ProcessSelection

            process_selection = ProcessSelection(process=process, score=float(payload.get("process_match_score", 1.0)))
        return process_selection, plan

    def _attach_process_context_to_plan(self, plan: TaskPlan, process) -> None:
        step_map = {step.step_id: step for step in process.steps}
        plan.metadata.setdefault("process_context", process.to_dict())
        for node in plan.tasks:
            self._attach_process_context_to_node(node, process, step_map)

    def _attach_process_context_to_node(self, node: TaskNode, process, step_map: dict[str, Any]) -> None:
        step = step_map.get(node.id)
        if step is not None:
            node.metadata.setdefault("process_id", process.process_id)
            node.metadata.setdefault("process_step", step.to_dict())
            assigned_agent = node.assigned_agent_type or ""
            if assigned_agent:
                node.metadata.setdefault(
                    "effective_agent_requirements",
                    process.resolve_agent_requirements(
                        agent_type=assigned_agent,
                        step_id=step.step_id,
                        agent_md_requirements=[],
                    ),
                )
        for child in node.children:
            self._attach_process_context_to_node(child, process, step_map)

    def generate_plan(self, task: RuntimeTask) -> TaskPlan:
        if isinstance(task.constraints.get("task_plan"), dict):
            override_plan = self.planner.generate_plan(
                task,
                PlannerContext(worker_registry=self.worker_registry, memory_summaries=[]),
            )
            override_plan.metadata.setdefault(
                "planning_inference",
                {"mode": "override", "prompt": "", "response": ""},
            )
            logger.info(
                "Master used explicit task plan override: task_id=%s plan_id=%s", task.task_id, override_plan.plan_id
            )
            return override_plan
        memory_summaries, memory_summary_text = self.retrieve_relevant_memory(task)
        process_selection, plan, plan_meta = self._single_inference_match_and_plan(
            task=task,
            memory_summaries=memory_summaries,
            memory_summary_text=memory_summary_text,
        )
        plan.metadata.update(plan_meta)
        if process_selection is not None:
            plan.metadata.setdefault("selected_process", process_selection.to_dict())
            plan.metadata.setdefault("process_context", process_selection.process.to_dict())
        logger.info("Master generated plan: task_id=%s plan_id=%s", task.task_id, plan.plan_id)
        return plan

    def maybe_replan(self, task: RuntimeTask, current_plan: TaskPlan) -> TaskPlan | None:
        failed = [nid for nid, res in task.node_results.items() if res.status == ExecutionStatus.FAILED]
        if not failed:
            return None
        mem_summaries, memory_summary_text = self.retrieve_relevant_memory(task)
        # Heuristic fallback replanning is forbidden. Replan must be explicitly LLM-driven;
        # until implemented, runtime does not perform automatic replanning.
        return None

    def update_memory_from_node_result(self, task: RuntimeTask, node: TaskNode, result: ExecutionResult) -> None:
        topic_tags = [node.assigned_agent_type or "unknown"] + list(node.capability_hints[:3])
        self.memory_manager.write_execution_memory(
            tenant_id=task.principal.tenant_id,
            user_id=task.principal.user_id,
            task_id=task.task_id,
            node_id=node.id,
            result=result,
            topic_tags=topic_tags,
        )

    def finalize_task_output(self, task: RuntimeTask) -> dict[str, Any]:
        successful = [r for r in task.node_results.values() if r.status == ExecutionStatus.SUCCESS]
        failed = [r for r in task.node_results.values() if r.status == ExecutionStatus.FAILED]
        ordered_nodes = sorted(task.node_results.keys())
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "completed_nodes": [
                nid for nid in ordered_nodes if task.node_results[nid].status == ExecutionStatus.SUCCESS
            ],
            "failed_nodes": [nid for nid in ordered_nodes if task.node_results[nid].status == ExecutionStatus.FAILED],
            "summaries": {nid: task.node_results[nid].summary for nid in ordered_nodes},
            "success_count": len(successful),
            "failure_count": len(failed),
        }
