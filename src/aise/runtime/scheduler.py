"""Task plan scheduler with DAG dependency handling and nested execution."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import Callable

from ..utils.logging import get_logger
from .exceptions import SchedulingError
from .models import ExecutionResult, ExecutionStatus, TaskMode, TaskNode, TaskPlan

logger = get_logger(__name__)


NodeExecutor = Callable[[TaskNode], ExecutionResult]


@dataclass(slots=True)
class ScheduleOutcome:
    results: dict[str, ExecutionResult]
    failed_node_ids: list[str]
    completed_node_ids: list[str]

    @property
    def all_success(self) -> bool:
        return not self.failed_node_ids


class TaskScheduler:
    """Executes task plans honoring dependencies and serial/parallel modes."""

    def execute_plan(self, plan: TaskPlan, executor: NodeExecutor) -> ScheduleOutcome:
        results = self._execute_nodes(plan.tasks, TaskMode.PARALLEL, plan.strategy.max_parallelism, executor)
        failed = [nid for nid, res in results.items() if res.status == ExecutionStatus.FAILED]
        completed = [nid for nid, res in results.items() if res.status == ExecutionStatus.SUCCESS]
        return ScheduleOutcome(results=results, failed_node_ids=failed, completed_node_ids=completed)

    def _execute_nodes(
        self,
        nodes: list[TaskNode],
        mode: TaskMode,
        max_parallelism: int,
        executor: NodeExecutor,
    ) -> dict[str, ExecutionResult]:
        if not nodes:
            return {}
        self._validate_graph(nodes)
        return (
            self._execute_nodes_parallel(nodes, max_parallelism, executor)
            if mode == TaskMode.PARALLEL
            else self._execute_nodes_serial(nodes, max_parallelism, executor)
        )

    def _execute_nodes_serial(
        self,
        nodes: list[TaskNode],
        max_parallelism: int,
        executor: NodeExecutor,
    ) -> dict[str, ExecutionResult]:
        results: dict[str, ExecutionResult] = {}
        pending = {node.id: node for node in nodes}
        while pending:
            ready = self._ready_nodes(pending, results)
            if not ready:
                raise SchedulingError("No ready nodes in serial execution; possible cyclic dependency")
            node = self._sort_nodes(ready)[0]
            results.update(self._execute_single_node(node, max_parallelism, executor))
            pending.pop(node.id, None)
        return results

    def _execute_nodes_parallel(
        self,
        nodes: list[TaskNode],
        max_parallelism: int,
        executor: NodeExecutor,
    ) -> dict[str, ExecutionResult]:
        results: dict[str, ExecutionResult] = {}
        pending = {node.id: node for node in nodes}
        in_flight: dict[Future[dict[str, ExecutionResult]], TaskNode] = {}

        pool_size = max(1, max_parallelism)
        with ThreadPoolExecutor(max_workers=pool_size, thread_name_prefix="runtime-node") as pool:
            while pending or in_flight:
                ready = self._sort_nodes(self._ready_nodes(pending, results))
                while ready and len(in_flight) < pool_size:
                    node = ready.pop(0)
                    future = pool.submit(self._execute_single_node, node, max_parallelism, executor)
                    in_flight[future] = node
                    pending.pop(node.id, None)
                    # recompute ready after removing pending node to avoid duplicate submits
                    ready = self._sort_nodes(self._ready_nodes(pending, results))

                if not in_flight:
                    if pending:
                        raise SchedulingError("No runnable nodes while pending remains")
                    break

                done, _ = wait(list(in_flight.keys()), return_when=FIRST_COMPLETED)
                for fut in done:
                    node = in_flight.pop(fut)
                    try:
                        results.update(fut.result())
                    except Exception as exc:  # pragma: no cover - defensive wrapper
                        logger.exception("Parallel node execution failed: node=%s error=%s", node.id, exc)
                        raise
        return results

    def _execute_single_node(
        self,
        node: TaskNode,
        max_parallelism: int,
        executor: NodeExecutor,
    ) -> dict[str, ExecutionResult]:
        result_map: dict[str, ExecutionResult] = {}
        if node.execute_self:
            result = executor(node)
        else:
            result = ExecutionResult(
                node_id=node.id,
                status=ExecutionStatus.SUCCESS,
                summary=f"Group node {node.id} completed",
            )
            result.finish()
        result_map[node.id] = result

        if result.status == ExecutionStatus.FAILED:
            return result_map
        if node.children:
            child_results = self._execute_nodes(node.children, node.mode, max_parallelism, executor)
            result_map.update(child_results)
        return result_map

    def _validate_graph(self, nodes: list[TaskNode]) -> None:
        node_ids = {n.id for n in nodes}
        if len(node_ids) != len(nodes):
            raise SchedulingError("Duplicate node ids detected")
        for node in nodes:
            missing = [dep for dep in node.dependencies if dep not in node_ids]
            if missing:
                raise SchedulingError(f"Node {node.id} has missing dependencies: {missing}")

    def _ready_nodes(
        self,
        pending: dict[str, TaskNode],
        results: dict[str, ExecutionResult],
    ) -> list[TaskNode]:
        ready: list[TaskNode] = []
        for node in pending.values():
            if all(dep in results and results[dep].status == ExecutionStatus.SUCCESS for dep in node.dependencies):
                ready.append(node)
        return ready

    def _sort_nodes(self, nodes: list[TaskNode]) -> list[TaskNode]:
        priority_rank = {"high": 0, "medium": 1, "low": 2}
        return sorted(nodes, key=lambda n: (priority_rank.get(n.priority, 9), n.id))
