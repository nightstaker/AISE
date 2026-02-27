"""Master agent implementation for runtime planning and orchestration logic."""

from __future__ import annotations

import json
import re
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
        logger.error("Process selection forbidden by policy: task_id=%s", task.task_id)
        raise PlanningError("Heuristic process matching is forbidden. Use LLM planning inference output.")

    def build_planning_prompt(
        self,
        *,
        task: RuntimeTask,
        memory_summary_text: str,
        process_summaries: list[dict[str, Any]],
    ) -> str:
        # Backward-compatible alias; runtime now uses two-step prompts below.
        return self.build_task_planning_prompt(
            task=task,
            memory_summary_text=memory_summary_text,
            selected_process=None,
            process_summaries=process_summaries,
        )

    def build_process_selection_prompt(
        self,
        *,
        task: RuntimeTask,
        memory_summary_text: str,
        process_summaries: list[dict[str, Any]],
    ) -> str:
        lines = [
            "You are Master Agent. Step 1: select the best matching process.",
            "Instruction: Choose exactly one process_id from the list, or 'none' if no process matches.",
            f"User task prompt: {task.prompt}",
            f"Task constraints: {task.constraints}",
            "Relevant memory summaries:",
            memory_summary_text or "(none)",
            "Available process summaries:",
        ]
        for item in process_summaries:
            lines.append(f"- {item['process_id']} | work_type={item['work_type']} | summary={item['summary']}")
        lines.append(
            "Output JSON only: {"
            '"selected_process_id": "<process_id or none>", '
            '"process_match_score": <0-1 float>, '
            '"reason": "<short reason>"'
            "}"
        )
        return "\n".join(lines)

    def build_task_planning_prompt(
        self,
        *,
        task: RuntimeTask,
        memory_summary_text: str,
        selected_process: Any | None,
    ) -> str:
        worker_caps = self.scan_workers()
        available_agent_types = self._available_agent_types()
        lines = [
            "You are Master Agent. Step 2: generate task plan.",
            "Instruction: Generate a complete JSON task plan.",
            "Instruction: If a selected process is provided, strictly plan according to it.",
            "Instruction: If selected process is none, plan directly by task prompt and worker capabilities.",
            (
                "Instruction: For any phase/step agent assignment, use ONLY agent types from this allowed list: "
                + ", ".join(available_agent_types if available_agent_types else ["generic_worker"])
            ),
            "Instruction: Do NOT invent agent names, aliases, role variants, or suffixes like *_agent/*_worker.",
            "Instruction: If process text uses alias agent names, rewrite them to one of the allowed agent types.",
            "Instruction: Before output, self-check every phase/step/task agent field is in the allowed list.",
            (
                "Instruction: Plan must include explicit review/validation gates:\n"
                "- Requirements phase: design/analysis task + review task.\n"
                "- Design phase: overall system architecture task before subsystem design tasks, plus review tasks.\n"
                "- Implementation phase: code generation tasks + code review task(s) + fix/revise task(s) if needed.\n"
                "- Testing phase: validation test tasks + final test/review summary task."
            ),
            "Instruction: Each step/task should have concrete deliverables (documents/code/tests) in artifacts.",
            f"User task prompt: {task.prompt}",
            f"Task constraints: {task.constraints}",
            "Relevant memory summaries:",
            memory_summary_text or "(none)",
            "Available worker capabilities:",
        ]
        for worker_id, caps in worker_caps.items():
            cap_names = [str(item.get("name", "")) for item in caps]
            inferred_types: list[str] = []
            for item in caps:
                owners = item.get("owner_agent_types", [])
                if isinstance(owners, list):
                    for owner in owners:
                        token = str(owner).strip()
                        if token and token not in inferred_types:
                            inferred_types.append(token)
            lines.append(
                f"- {worker_id} (agent_types={', '.join(inferred_types) if inferred_types else '-'})"
                f": {', '.join(cap_names) if cap_names else '(none)'}"
            )
        if selected_process is not None:
            lines.append(f"Selected process id: {selected_process.process.process_id}")
            lines.append("Selected process full specification:")
            lines.append(selected_process.process.render_for_prompt())
        else:
            lines.append("Selected process id: none")
            lines.append("Selected process full specification: (none)")
        lines.append(
            "Output JSON only: {"
            '"selected_process_id": "<process_id or none>", '
            '"task_plan": { ... complete TaskPlan ... }'
            "}"
        )
        return "\n".join(lines)

    def _two_step_match_and_plan(
        self,
        *,
        task: RuntimeTask,
        memory_summary_text: str,
    ) -> tuple[Any | None, TaskPlan, dict[str, Any]]:
        process_summaries = self.scan_processes()
        selection_prompt = self.build_process_selection_prompt(
            task=task,
            memory_summary_text=memory_summary_text,
            process_summaries=process_summaries,
        )

        if self.llm_client is None:
            logger.error("MasterAgent missing llm_client for planning: task_id=%s", task.task_id)
            raise PlanningError(
                "MasterAgent requires an llm_client for process matching and task planning. "
                "Heuristic fallback is forbidden in this project."
            )
        try:
            selection_response_text = self.llm_client.complete(selection_prompt)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Planning inference call failed: task_id=%s error=%s", task.task_id, exc)
            raise PlanningError(f"Planning inference failed: {exc}") from exc

        process_selection = self._parse_process_selection_response(
            llm_response_text=selection_response_text,
            task=task,
        )
        planning_prompt = self.build_task_planning_prompt(
            task=task,
            memory_summary_text=memory_summary_text,
            selected_process=process_selection,
        )
        try:
            llm_response_text = self.llm_client.complete(planning_prompt)
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Task-plan inference call failed: task_id=%s error=%s", task.task_id, exc)
            raise PlanningError(f"Task plan inference failed: {exc}") from exc

        _, plan = self._parse_planning_inference_response(
            llm_response_text=llm_response_text,
            task=task,
        )
        if process_selection is not None:
            self._attach_process_context_to_plan(plan, process_selection.process)
        plan_meta = {
            "planning_inference": {
                "mode": "two_step",
                "prompt": planning_prompt,
                "response": llm_response_text,
            },
            "process_selection_inference": {
                "prompt": selection_prompt,
                "response": selection_response_text,
            },
            "process_match": process_selection.to_dict() if process_selection else None,
            "process_summaries": process_summaries,
            "available_agent_types": self._available_agent_types(),
        }
        return process_selection, plan, plan_meta

    def _parse_process_selection_response(
        self,
        *,
        llm_response_text: str,
        task: RuntimeTask,
    ):
        text = str(llm_response_text or "").strip()
        if not text:
            logger.error("Process selection returned empty response: task_id=%s", task.task_id)
            return None
        payload: Any = None
        try:
            payload = self._parse_json_object_tolerant(text)
        except json.JSONDecodeError:
            payload = text

        selected_process_id = ""
        score = 1.0
        if isinstance(payload, dict):
            selected_process_id = str(payload.get("selected_process_id", "")).strip()
            try:
                score = float(payload.get("process_match_score", payload.get("score", 1.0)))
            except Exception:
                score = 1.0
        elif isinstance(payload, str):
            selected_process_id = payload.strip()
        else:
            logger.error("Invalid process selection payload type: task_id=%s type=%s", task.task_id, type(payload))
            raise PlanningError("Process selection inference JSON root must be an object or string")

        if selected_process_id.lower() in {"", "none", "null"}:
            return None
        process = self.process_repository.get_process(selected_process_id)
        if process is None:
            logger.error(
                "Process selection chose unknown process: task_id=%s process_id=%s",
                task.task_id,
                selected_process_id,
            )
            raise PlanningError(f"Planning inference selected unknown process_id: {selected_process_id}")
        from .process import ProcessSelection

        return ProcessSelection(process=process, score=score)

    def _parse_planning_inference_response(
        self,
        *,
        llm_response_text: str,
        task: RuntimeTask,
    ):
        try:
            payload = self._parse_json_object_tolerant(llm_response_text)
        except json.JSONDecodeError as exc:
            logger.error(
                "Planning inference returned non-JSON: task_id=%s error=%s raw_prefix=%s",
                task.task_id,
                exc,
                str(llm_response_text or "")[:160].replace("\n", "\\n"),
            )
            raise PlanningError(f"Planning inference must return JSON. parse_error={exc}") from exc
        if not isinstance(payload, dict):
            logger.error("Planning inference JSON root is not object: task_id=%s type=%s", task.task_id, type(payload))
            raise PlanningError("Planning inference JSON root must be an object")
        plan_payload = payload.get("task_plan")
        if not isinstance(plan_payload, dict):
            alt_plan = payload.get("plan")
            if isinstance(alt_plan, dict):
                plan_payload = alt_plan
            elif isinstance(payload.get("tasks"), list):
                # Be tolerant when model returns TaskPlan directly as root object.
                plan_payload = dict(payload)
            else:
                logger.error(
                    "Planning inference missing task_plan: task_id=%s payload_keys=%s",
                    task.task_id,
                    sorted(payload.keys()),
                )
                raise PlanningError(
                    "Planning inference JSON must include object field 'task_plan' "
                    "(or compatible 'plan' / root TaskPlan object)"
                )
        plan_payload = dict(plan_payload)
        if not str(plan_payload.get("task_name", "")).strip():
            fallback_task_name = str(task.task_name or task.prompt[:80] or "runtime_task").strip()
            plan_payload["task_name"] = fallback_task_name or "runtime_task"
        plan_payload = self._normalize_task_plan_payload(plan_payload, task=task)
        self._validate_plan_agent_types(
            plan_payload,
            task=task,
            available_agent_types=self._available_agent_types(),
        )
        if not isinstance(plan_payload.get("tasks"), list) or not plan_payload.get("tasks"):
            logger.error(
                "Normalized task plan still has empty tasks: task_id=%s payload_keys=%s",
                task.task_id,
                sorted(plan_payload.keys()),
            )
            raise PlanningError("Planning inference produced empty executable tasks")
        plan = TaskPlan.from_dict(plan_payload)
        selected_process_id = payload.get("selected_process_id")
        process_selection = None
        if selected_process_id is not None and str(selected_process_id).strip().lower() not in {"", "none", "null"}:
            process = self.process_repository.get_process(str(selected_process_id).strip())
            if process is None:
                logger.error(
                    "Planning inference selected unknown process: task_id=%s process_id=%s",
                    task.task_id,
                    selected_process_id,
                )
                raise PlanningError(f"Planning inference selected unknown process_id: {selected_process_id}")
            from .process import ProcessSelection

            process_selection = ProcessSelection(process=process, score=float(payload.get("process_match_score", 1.0)))
        return process_selection, plan

    def _parse_json_object_tolerant(self, text: str) -> Any:
        """Parse JSON with tolerance for fenced blocks and extra wrapper text."""
        raw = str(text or "").strip()
        if not raw:
            raise json.JSONDecodeError("empty response", raw, 0)

        # Fast path: strict JSON.
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass

        # Markdown fenced JSON block: ```json ... ```
        fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
        if fence:
            candidate = fence.group(1).strip()
            if candidate:
                return json.loads(candidate)

        # Extract first balanced JSON object from mixed text.
        start = raw.find("{")
        if start >= 0:
            depth = 0
            in_string = False
            escape = False
            for idx in range(start, len(raw)):
                ch = raw[idx]
                if in_string:
                    if escape:
                        escape = False
                    elif ch == "\\":
                        escape = True
                    elif ch == '"':
                        in_string = False
                    continue
                if ch == '"':
                    in_string = True
                    continue
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        return json.loads(raw[start : idx + 1])

        # Let caller get a standard JSONDecodeError.
        return json.loads(raw)

    def _normalize_task_plan_payload(self, plan_payload: dict[str, Any], *, task: RuntimeTask) -> dict[str, Any]:
        """Normalize model-specific plan shapes into runtime TaskPlan schema."""
        available_agent_types = self._available_agent_types()
        available_set = set(available_agent_types)
        default_agent_type = "generic_worker" if "generic_worker" in available_set else (
            available_agent_types[0] if available_agent_types else "generic_worker"
        )

        def _norm_agent(value: Any, default: str = default_agent_type) -> str:
            raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
            return raw or default

        def _default_strategy() -> dict[str, Any]:
            return {
                "max_parallelism": 1,
                "budget": {"tokens": 200000, "time_sec": 1800},
                "replan_policy": "on_failure_or_new_evidence",
            }

        def _normalize_root_steps(raw_steps: list[Any]) -> dict[str, Any]:
            tasks: list[dict[str, Any]] = []
            node_ids: set[str] = set()
            prev_id = ""

            for index, step in enumerate(raw_steps, start=1):
                if not isinstance(step, dict):
                    continue
                raw_node_id = str(step.get("id") or step.get("step_id") or f"step_{index}").strip() or f"step_{index}"
                node_id = raw_node_id if raw_node_id not in node_ids else f"{raw_node_id}_{index}"
                node_ids.add(node_id)

                node_name = (
                    str(step.get("name") or step.get("action") or step.get("task") or f"step_{index}").strip()
                    or f"step_{index}"
                )
                node_desc = str(step.get("description") or step.get("task") or node_name).strip() or node_name

                participants = step.get("participating_agents")
                step_agent = _norm_agent(step.get("agent") or step.get("agent_type") or step.get("assigned_agent_type"))
                if not step_agent and isinstance(participants, list) and participants:
                    step_agent = _norm_agent(participants[0], default="generic_worker")

                raw_deps = step.get("dependencies")
                deps: list[str] = []
                if isinstance(raw_deps, list):
                    deps = [str(dep).strip() for dep in raw_deps if str(dep).strip()]
                elif prev_id:
                    deps = [prev_id]

                tasks.append(
                    {
                        "id": node_id,
                        "name": node_name,
                        "mode": "serial",
                        "assigned_agent_type": step_agent,
                        "dependencies": deps,
                        "priority": "medium",
                        "input_data": {
                            "prompt": node_desc,
                            "step": node_id,
                            "agent": step_agent,
                            "expected_output": str(step.get("expected_output", "")).strip(),
                        },
                        "capability_hints": [node_name, step_agent],
                        "memory_policy": {},
                        "success_criteria": (
                            [str(step.get("expected_output", "")).strip()] if step.get("expected_output") else []
                        ),
                        "children": [],
                        "metadata": {
                            "source": "llm_steps_plan",
                            "step_id": str(step.get("step_id", "")).strip() or node_id,
                            "process_step_name": str(step.get("name", "")).strip(),
                        },
                        "execute_self": True,
                    }
                )
                prev_id = node_id

            for node in tasks:
                node["dependencies"] = [dep for dep in node.get("dependencies", []) if dep in node_ids]

            normalized = dict(plan_payload)
            normalized["tasks"] = tasks
            normalized.setdefault("strategy", _default_strategy())
            logger.info(
                "Normalized root steps plan to task graph: task_id=%s steps=%d tasks=%d",
                task.task_id,
                len(raw_steps),
                len(tasks),
            )
            return normalized

        if isinstance(plan_payload.get("tasks"), list) and plan_payload.get("tasks"):
            return plan_payload

        root_steps = plan_payload.get("steps")
        if isinstance(root_steps, list) and root_steps:
            return _normalize_root_steps(root_steps)

        phases = plan_payload.get("phases")
        if not isinstance(phases, list) or not phases:
            return plan_payload

        tasks: list[dict[str, Any]] = []
        phase_ids: set[str] = set()
        for index, phase in enumerate(phases, start=1):
            if not isinstance(phase, dict):
                continue
            raw_phase_id = str(phase.get("phase_id") or f"phase_{index}")
            phase_id = raw_phase_id.strip() or f"phase_{index}"
            phase_ids.add(phase_id)
            phase_name = str(phase.get("phase_name") or phase.get("name") or phase_id).strip() or phase_id
            phase_desc = str(phase.get("description", "") or "")

            children: list[dict[str, Any]] = []
            prev_child_id = ""
            phase_tasks = phase.get("tasks")
            steps = phase.get("steps")
            step_items = phase_tasks if isinstance(phase_tasks, list) else steps
            if isinstance(step_items, list):
                for step_idx, step in enumerate(step_items, start=1):
                    if not isinstance(step, dict):
                        continue
                    raw_step_id = str(step.get("step_id") or step.get("task_id") or f"{phase_id}_step_{step_idx}")
                    step_id = raw_step_id.strip() or f"{phase_id}_step_{step_idx}"
                    child_id = f"{phase_id}.{step_id}"
                    action = (
                        str(step.get("action") or step.get("task_name") or step.get("task") or "execute_step").strip()
                        or "execute_step"
                    )
                    step_input = str(step.get("input") or step.get("task") or step.get("description") or "").strip()
                    step_agent = _norm_agent(
                        step.get("agent") or step.get("agent_type") or step.get("assigned_agent_type")
                    )
                    child_node = {
                        "id": child_id,
                        "name": action,
                        "mode": "serial",
                        "assigned_agent_type": step_agent,
                        "dependencies": [prev_child_id] if prev_child_id else [],
                        "priority": "medium",
                        "input_data": {
                            "prompt": step_input or action,
                            "phase": phase_id,
                            "step": step_id,
                            "agent": step_agent,
                            "expected_output": str(step.get("expected_output", "")),
                        },
                        "capability_hints": [action, step_agent],
                        "memory_policy": {},
                        "success_criteria": [str(step.get("expected_output", "")).strip()] if step.get("expected_output") else [],
                        "children": [],
                        "metadata": {
                            "source": "llm_phase_plan",
                            "phase_id": phase_id,
                            "step_id": step_id,
                        },
                        "execute_self": True,
                    }
                    children.append(child_node)
                    prev_child_id = child_id

            raw_phase_deps = phase.get("dependencies")
            phase_deps: list[str] = []
            if isinstance(raw_phase_deps, list):
                phase_deps = [str(item).strip() for item in raw_phase_deps if str(item).strip()]

            phase_node = {
                "id": phase_id,
                "name": phase_name,
                "mode": "serial",
                "assigned_agent_type": _norm_agent(
                    (
                        (phase.get("agents") or [default_agent_type])[0]
                        if isinstance(phase.get("agents"), list) and phase.get("agents")
                        else phase.get("agent") or phase.get("agent_type") or default_agent_type
                    )
                ),
                "dependencies": phase_deps,
                "priority": "medium",
                "input_data": {"prompt": phase_desc or phase_name, "phase": phase_id},
                "capability_hints": ["design", "analyze", "summarize"],
                "memory_policy": {},
                "success_criteria": [phase_desc] if phase_desc else [],
                "children": children,
                "metadata": {"source": "llm_phase_plan", "phase_id": phase_id},
                "execute_self": False if children else True,
            }
            tasks.append(phase_node)

        for node in tasks:
            deps = [dep for dep in node.get("dependencies", []) if dep in phase_ids]
            node["dependencies"] = deps

        normalized = dict(plan_payload)
        normalized["tasks"] = tasks
        normalized.setdefault("strategy", _default_strategy())
        logger.info(
            "Normalized phase plan to task graph: task_id=%s phases=%d tasks=%d",
            task.task_id,
            len(phases),
            len(tasks),
        )
        return normalized

    def _validate_plan_agent_types(
        self,
        plan_payload: dict[str, Any],
        *,
        task: RuntimeTask,
        available_agent_types: list[str],
    ) -> None:
        allowed = {str(item).strip().lower().replace("-", "_").replace(" ", "_") for item in available_agent_types}
        if not allowed:
            return
        invalid: list[tuple[str, str]] = []

        def _walk(nodes: list[Any], prefix: str = "tasks") -> None:
            for idx, node in enumerate(nodes):
                if not isinstance(node, dict):
                    continue
                path = f"{prefix}[{idx}]"
                agent = str(node.get("assigned_agent_type", "")).strip().lower().replace("-", "_").replace(" ", "_")
                if agent and agent not in allowed:
                    invalid.append((path, agent))
                children = node.get("children")
                if isinstance(children, list):
                    _walk(children, prefix=f"{path}.children")

        tasks = plan_payload.get("tasks")
        if isinstance(tasks, list):
            _walk(tasks)
        if invalid:
            logger.error(
                "Planning inference produced unsupported agent types: task_id=%s invalid=%s allowed=%s",
                task.task_id,
                invalid,
                sorted(allowed),
            )
            raise PlanningError(
                "Planning inference produced unsupported agent types: "
                + ", ".join(f"{path}={agent}" for path, agent in invalid[:8])
            )

    def _available_agent_types(self) -> list[str]:
        """Discover currently registered runtime worker agent types (normalized)."""
        seen: set[str] = set()
        ordered: list[str] = []
        try:
            workers = self.worker_registry.list_all()
        except Exception:
            workers = []
        for worker in workers:
            token = str(getattr(worker, "agent_type", "")).strip().lower().replace("-", "_").replace(" ", "_")
            if not token or token in seen:
                continue
            seen.add(token)
            ordered.append(token)
        if "generic_worker" not in seen:
            ordered.insert(0, "generic_worker")
        return ordered

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
            constraints = task.constraints if isinstance(task.constraints, dict) else {}
            logger.info(
                (
                    "Master used explicit task plan override: task_id=%s task_name=%s "
                    "project_id=%s run_id=%s plan_id=%s plan_task_name=%s top_level_tasks=%d"
                ),
                task.task_id,
                task.task_name or "-",
                str(constraints.get("project_id", "")).strip() or "-",
                str(constraints.get("run_id", "")).strip() or "-",
                override_plan.plan_id,
                override_plan.task_name,
                len(override_plan.tasks),
            )
            return override_plan
        _memory_summaries, memory_summary_text = self.retrieve_relevant_memory(task)
        process_selection, plan, plan_meta = self._two_step_match_and_plan(
            task=task,
            memory_summary_text=memory_summary_text,
        )
        plan.metadata.update(plan_meta)
        if process_selection is not None:
            plan.metadata.setdefault("selected_process", process_selection.to_dict())
            plan.metadata.setdefault("process_context", process_selection.process.to_dict())
        constraints = task.constraints if isinstance(task.constraints, dict) else {}
        logger.info("Master generated plan: task_id=%s plan_id=%s", task.task_id, plan.plan_id)
        logger.info(
            (
                "Master generated plan details: task_id=%s task_name=%s project_id=%s run_id=%s "
                "plan_id=%s plan_task_name=%s top_level_tasks=%d selected_process=%s"
            ),
            task.task_id,
            task.task_name or "-",
            str(constraints.get("project_id", "")).strip() or "-",
            str(constraints.get("run_id", "")).strip() or "-",
            plan.plan_id,
            plan.task_name,
            len(plan.tasks),
            (process_selection.process.process_id if process_selection is not None else "none"),
        )
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
