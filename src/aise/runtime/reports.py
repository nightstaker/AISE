"""Task result analysis and report generation."""

from __future__ import annotations

from statistics import mean
from typing import Any

from .models import ExecutionStatus, RuntimeTask
from .observability import ObservabilityCenter


class ReportEngine:
    """Generates JSON-friendly task execution reports."""

    def generate(self, task: RuntimeTask, observability: ObservabilityCenter) -> dict[str, Any]:
        results = list(task.node_results.values())
        total_nodes = len(results)
        success_nodes = [r for r in results if r.status == ExecutionStatus.SUCCESS]
        failed_nodes = [r for r in results if r.status == ExecutionStatus.FAILED]
        durations = [int(r.metrics.get("duration_ms", 0)) for r in results]
        token_cost = sum(int(r.metrics.get("token_in", 0)) + int(r.metrics.get("token_out", 0)) for r in results)
        tool_calls = sum(len(r.tool_calls) for r in results)
        retries = sum(1 for e in observability.get_events(task.task_id) if e["event_type"] == "node_retry")
        critical_path_ms = sum(durations)

        return {
            "report_id": f"rep_{task.task_id}",
            "task_id": task.task_id,
            "summary": {
                "status": task.status.value,
                "total_nodes": total_nodes,
                "success_nodes": len(success_nodes),
                "failed_nodes": len(failed_nodes),
                "retried_nodes": retries,
                "total_duration_ms": critical_path_ms,
            },
            "efficiency": {
                "parallelism_avg": 1.0,  # in-memory scheduler does not persist true concurrency stats yet
                "critical_path_ms": critical_path_ms,
                "token_cost": token_cost,
                "avg_node_duration_ms": int(mean(durations)) if durations else 0,
                "tool_calls": tool_calls,
            },
            "quality": {
                "artifact_checks_passed": sum(1 for r in results if r.artifacts),
                "artifact_checks_failed": len(failed_nodes),
            },
            "llm_traces": {
                "count": len(observability.get_llm_traces(task.task_id)),
            },
        }
