"""Top-level Agent Runtime coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from threading import RLock
from typing import Any

from ..utils.logging import get_logger
from .agents import WorkerAgent, build_default_worker_fleet
from .executor import ExecutionContext, ExecutionEngine
from .interfaces import LLMClientProtocol
from .master_agent import MasterAgent
from .memory import InMemoryMemoryManager
from .models import ExecutionResult, Principal, RuntimeTask, RuntimeTaskStatus, TaskNode, TaskPlan
from .observability import EventRecord, ObservabilityCenter
from .recovery import RecoveryManager, RetryPolicy
from .registry import WorkerRegistry
from .reports import ReportEngine
from .scheduler import ScheduleOutcome, TaskScheduler
from .schema import validate_task_plan
from .security import Authenticator, PolicyEngine

logger = get_logger(__name__)


@dataclass(slots=True)
class SubmitTaskRequest:
    prompt: str
    principal: Principal
    task_name: str | None = None
    constraints: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None
    run_sync: bool = True


class AgentRuntime:
    """In-process runtime implementing the two-level Agent Runtime design."""

    def __init__(
        self,
        *,
        master_agent: MasterAgent | None = None,
        worker_registry: WorkerRegistry | None = None,
        memory_manager: InMemoryMemoryManager | None = None,
        policy_engine: PolicyEngine | None = None,
        authenticator: Authenticator | None = None,
        observability: ObservabilityCenter | None = None,
        recovery_manager: RecoveryManager | None = None,
        scheduler: TaskScheduler | None = None,
        report_engine: ReportEngine | None = None,
        llm_client: LLMClientProtocol | None = None,
        auto_register_default_worker: bool = True,
    ) -> None:
        self.worker_registry = worker_registry or WorkerRegistry()
        self.memory_manager = memory_manager or InMemoryMemoryManager()
        self.policy_engine = policy_engine or PolicyEngine()
        self.authenticator = authenticator or Authenticator()
        self.observability = observability or ObservabilityCenter()
        self.recovery_manager = recovery_manager or RecoveryManager(RetryPolicy())
        self.scheduler = scheduler or TaskScheduler()
        self.report_engine = report_engine or ReportEngine()
        self.execution_engine = ExecutionEngine(
            worker_registry=self.worker_registry,
            memory_manager=self.memory_manager,
            observability=self.observability,
            recovery_manager=self.recovery_manager,
        )
        self.master_agent = master_agent or MasterAgent(
            worker_registry=self.worker_registry,
            memory_manager=self.memory_manager,
            llm_client=llm_client,
        )
        self._tasks: dict[str, RuntimeTask] = {}
        self._lock = RLock()

        if auto_register_default_worker and not self.worker_registry.list_all():
            for worker in build_default_worker_fleet(llm_client=self.master_agent.llm_client):
                self.register_worker(worker)

    @staticmethod
    def _task_log_context(task: RuntimeTask) -> str:
        constraints = task.constraints if isinstance(task.constraints, dict) else {}
        project_id = str(constraints.get("project_id", "")).strip() or "-"
        run_id = str(constraints.get("run_id", "")).strip() or "-"
        task_name = str(task.task_name or "").strip() or "-"
        return f"task_id={task.task_id} task_name={task_name} project_id={project_id} run_id={run_id}"

    # Registration ---------------------------------------------------------

    def register_worker(self, worker: WorkerAgent) -> None:
        self.worker_registry.register(worker)

    # Gateway-like interfaces ---------------------------------------------

    def submit_task(
        self,
        *,
        prompt: str,
        principal: Principal | None = None,
        auth_context: dict[str, Any] | None = None,
        task_name: str | None = None,
        constraints: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        run_sync: bool = True,
    ) -> str:
        if principal is None:
            principal = self.authenticator.authenticate(auth_context or {})
        self.policy_engine.check(principal, "task:create")

        task = RuntimeTask(
            principal=principal,
            prompt=prompt,
            task_name=task_name,
            constraints=dict(constraints or {}),
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._tasks[task.task_id] = task
        logger.info(
            "Task submitted: %s tenant=%s user=%s",
            self._task_log_context(task),
            principal.tenant_id,
            principal.user_id,
        )

        self.observability.record_event(
            EventRecord(
                trace_id=self.observability.new_trace_id(),
                span_id=self.observability.new_span_id(),
                tenant_id=principal.tenant_id,
                task_id=task.task_id,
                event_type="task_submitted",
                payload={"prompt": prompt, "task_name": task_name, "constraints": task.constraints},
            )
        )

        if run_sync:
            self.run_task(task.task_id, principal=principal)
        return task.task_id

    def run_task(self, task_id: str, *, principal: Principal | None = None) -> dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        principal = principal or task.principal
        self._check_read_permission(principal, task)
        self._execute_task(task)
        return self.get_task(task_id, principal=principal)

    def get_task(self, task_id: str, *, principal: Principal | None = None) -> dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        principal = principal or task.principal
        self._check_read_permission(principal, task)
        return task.to_dict()

    def get_task_status(self, task_id: str, *, principal: Principal | None = None) -> dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        principal = principal or task.principal
        self._check_read_permission(principal, task)
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "updated_at": task.updated_at.isoformat(),
            "plan_id": task.plan.plan_id if task.plan else None,
            "node_status": {nid: res.status.value for nid, res in task.node_results.items()},
        }

    def get_task_result(self, task_id: str, *, principal: Principal | None = None) -> dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        principal = principal or task.principal
        self._check_read_permission(principal, task)
        return {
            "task_id": task.task_id,
            "status": task.status.value,
            "final_output": dict(task.final_output),
            "node_results": {nid: res.to_dict() for nid, res in task.node_results.items()},
            "errors": list(task.errors),
        }

    def get_task_logs(self, task_id: str, *, principal: Principal | None = None) -> list[dict[str, Any]]:
        task = self._get_task_or_raise(task_id)
        principal = principal or task.principal
        self.policy_engine.check(principal, "logs:read", task)
        return self.observability.get_events(task_id)

    def get_task_llm_traces(
        self,
        task_id: str,
        *,
        principal: Principal | None = None,
        include_sensitive: bool = False,
    ) -> list[dict[str, Any]]:
        task = self._get_task_or_raise(task_id)
        principal = principal or task.principal
        self._check_read_permission(principal, task)
        if include_sensitive:
            self.policy_engine.check(principal, "audit:read_sensitive", task)
        traces = self.observability.get_llm_traces(task_id)
        if include_sensitive:
            return traces
        # Redact prompt/response by default
        for item in traces:
            item["prompt"] = f"<redacted len={len(item['prompt'])}>"
            item["response"] = f"<redacted len={len(item['response'])}>"
        return traces

    def get_task_report(self, task_id: str, *, principal: Principal | None = None) -> dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        principal = principal or task.principal
        self._check_read_permission(principal, task)
        if task.report is None:
            task.report = self.report_engine.generate(task, self.observability)
        return dict(task.report)

    def retry_node(
        self,
        task_id: str,
        node_id: str,
        *,
        principal: Principal | None = None,
    ) -> dict[str, Any]:
        task = self._get_task_or_raise(task_id)
        principal = principal or task.principal
        self.policy_engine.check(principal, "task:retry", task)
        if task.plan is None:
            logger.error("Retry rejected: task has no plan, task_id=%s node_id=%s", task_id, node_id)
            raise ValueError(f"Task {task_id} has no plan")
        node = self._find_node(task.plan, node_id)
        if node is None:
            logger.error("Retry rejected: node not found, task_id=%s node_id=%s", task_id, node_id)
            raise ValueError(f"Node not found: {node_id}")

        mem_records, memory_summary = self.master_agent.retrieve_relevant_memory(task)
        exec_ctx = ExecutionContext(task=task, memory_summary=memory_summary, memory_details=mem_records)
        result = self.execution_engine.execute_node(node, exec_ctx)
        task.node_results[node.id] = result
        self.master_agent.update_memory_from_node_result(task, node, result)
        task.touch()
        task.report = self.report_engine.generate(task, self.observability)
        return {"task_id": task_id, "node_id": node_id, "status": result.status.value, "result": result.to_dict()}

    # Internal execution ---------------------------------------------------

    def _execute_task(self, task: RuntimeTask) -> None:
        if task.status == RuntimeTaskStatus.COMPLETED:
            return

        task.status = RuntimeTaskStatus.PLANNING
        task.touch()
        self.observability.record_event(
            EventRecord(
                trace_id=self.observability.new_trace_id(),
                span_id=self.observability.new_span_id(),
                tenant_id=task.principal.tenant_id,
                task_id=task.task_id,
                event_type="planning_started",
                payload={"prompt": task.prompt},
            )
        )
        plan = self.master_agent.generate_plan(task)
        validate_task_plan(plan)
        task.plan = plan
        logger.info(
            "Task planning completed: %s plan_id=%s plan_task_name=%s top_level_tasks=%d",
            self._task_log_context(task),
            plan.plan_id,
            plan.task_name,
            len(plan.tasks),
        )

        self.observability.record_event(
            EventRecord(
                trace_id=self.observability.new_trace_id(),
                span_id=self.observability.new_span_id(),
                tenant_id=task.principal.tenant_id,
                task_id=task.task_id,
                event_type="planning_completed",
                payload={"plan": plan.to_dict()},
            )
        )

        self._run_plan_cycle(task, plan)

    def _run_plan_cycle(self, task: RuntimeTask, initial_plan: TaskPlan) -> None:
        current_plan = initial_plan
        max_plan_cycles = 2
        logger.info(
            "Task execution loop started: %s plan_id=%s plan_task_name=%s max_cycles=%d",
            self._task_log_context(task),
            current_plan.plan_id,
            current_plan.task_name,
            max_plan_cycles,
        )
        for cycle in range(max_plan_cycles):
            task.status = RuntimeTaskStatus.RUNNING
            task.touch()
            logger.info(
                "Task execution cycle started: %s cycle=%d plan_id=%s",
                self._task_log_context(task),
                cycle,
                current_plan.plan_id,
            )

            mem_records, memory_summary = self.master_agent.retrieve_relevant_memory(task)
            exec_context = ExecutionContext(task=task, memory_summary=memory_summary, memory_details=mem_records)

            def node_executor(node: TaskNode) -> ExecutionResult:
                result = self.execution_engine.execute_node(node, exec_context)
                task.node_results[node.id] = result
                self.master_agent.update_memory_from_node_result(task, node, result)
                task.touch()
                return result

            outcome: ScheduleOutcome = self.scheduler.execute_plan(current_plan, node_executor)
            logger.info(
                "Task execution cycle finished: %s cycle=%d completed=%d failed=%d",
                self._task_log_context(task),
                cycle,
                len(outcome.completed_node_ids),
                len(outcome.failed_node_ids),
            )
            if outcome.all_success:
                task.status = RuntimeTaskStatus.COMPLETED
                task.final_output = self.master_agent.finalize_task_output(task)
                task.report = self.report_engine.generate(task, self.observability)
                task.touch()
                logger.info(
                    "Task execution completed: %s cycle=%d plan_id=%s",
                    self._task_log_context(task),
                    cycle,
                    current_plan.plan_id,
                )
                self.observability.record_event(
                    EventRecord(
                        trace_id=self.observability.new_trace_id(),
                        span_id=self.observability.new_span_id(),
                        tenant_id=task.principal.tenant_id,
                        task_id=task.task_id,
                        event_type="task_completed",
                        payload={"cycle": cycle, "plan_id": current_plan.plan_id},
                    )
                )
                return

            task.errors.extend(
                [
                    f"Node {nid} failed: {task.node_results[nid].summary}"
                    for nid in outcome.failed_node_ids
                    if nid in task.node_results
                ]
            )
            replan = self.master_agent.maybe_replan(task, current_plan)
            if replan is None:
                task.status = RuntimeTaskStatus.FAILED
                task.final_output = self.master_agent.finalize_task_output(task)
                task.report = self.report_engine.generate(task, self.observability)
                task.touch()
                logger.error(
                    "Task execution failed without replan: %s cycle=%d failed_nodes=%s plan_id=%s",
                    self._task_log_context(task),
                    cycle,
                    outcome.failed_node_ids,
                    current_plan.plan_id,
                )
                self.observability.record_event(
                    EventRecord(
                        trace_id=self.observability.new_trace_id(),
                        span_id=self.observability.new_span_id(),
                        tenant_id=task.principal.tenant_id,
                        task_id=task.task_id,
                        event_type="task_failed",
                        payload={"failed_nodes": outcome.failed_node_ids, "plan_id": current_plan.plan_id},
                    )
                )
                return

            current_plan = replan
            task.plan = current_plan
            # clear only failed results so replan can re-run updated nodes; keep successful history
            for failed_id in outcome.failed_node_ids:
                task.node_results.pop(failed_id, None)
            self.observability.record_event(
                EventRecord(
                    trace_id=self.observability.new_trace_id(),
                    span_id=self.observability.new_span_id(),
                    tenant_id=task.principal.tenant_id,
                    task_id=task.task_id,
                    event_type="task_replanned",
                    payload={"cycle": cycle, "new_plan": current_plan.to_dict()},
                )
            )

        task.status = RuntimeTaskStatus.FAILED
        task.errors.append("Exceeded maximum plan cycles")
        task.final_output = self.master_agent.finalize_task_output(task)
        task.report = self.report_engine.generate(task, self.observability)
        task.touch()
        logger.error(
            "Task execution failed: %s reason=max_plan_cycles_exceeded",
            self._task_log_context(task),
        )

    # Helpers --------------------------------------------------------------

    def _get_task_or_raise(self, task_id: str) -> RuntimeTask:
        with self._lock:
            task = self._tasks.get(task_id)
        if task is None:
            logger.error("Task not found in runtime store: task_id=%s", task_id)
            raise ValueError(f"Task not found: {task_id}")
        return task

    def _check_read_permission(self, principal: Principal, task: RuntimeTask) -> None:
        if principal.user_id == task.principal.user_id:
            self.policy_engine.check(principal, "task:read:own", task, resource_attrs={"owner_only": True})
            return
        self.policy_engine.check(principal, "task:read:any", task)

    def _find_node(self, plan: TaskPlan, node_id: str) -> TaskNode | None:
        return self._build_node_lookup(plan).get(node_id)

    def _build_node_lookup(self, plan: TaskPlan) -> dict[str, TaskNode]:
        lookup: dict[str, TaskNode] = {}

        def visit(nodes: list[TaskNode]) -> None:
            for node in nodes:
                lookup[node.id] = node
                if node.children:
                    visit(node.children)

        visit(plan.tasks)
        return lookup
