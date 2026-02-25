"""Worker agents and in-process worker adapter implementations."""

from __future__ import annotations

import time
from threading import RLock
from typing import Any
from uuid import uuid4

from ..utils.logging import get_logger
from .exceptions import CapabilityNotFoundError
from .interfaces import CapabilityHandler, LanguageWorkerAdapter, LLMClientProtocol
from .models import (
    CapabilityKind,
    CapabilitySpec,
    ExecutionResult,
    ExecutionStatus,
    LLMTrace,
    TaskNode,
)
from .registry import CapabilityRegistry

logger = get_logger(__name__)


class WorkerAgent(LanguageWorkerAdapter):
    """In-process worker agent with local skill/tool registry."""

    def __init__(
        self,
        *,
        adapter_id: str,
        agent_type: str,
        language: str = "python",
        llm_client: LLMClientProtocol | None = None,
    ) -> None:
        self.adapter_id = adapter_id
        self.agent_type = agent_type
        self.language = language
        self.llm_client = llm_client
        self.capability_registry = CapabilityRegistry()
        self._lock = RLock()

    def register_skill(
        self,
        *,
        capability_id: str,
        name: str,
        description: str,
        func: Any,
        tags: list[str] | None = None,
        permissions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CapabilitySpec:
        return self.capability_registry.register_callable(
            capability_id=capability_id,
            name=name,
            kind=CapabilityKind.SKILL,
            description=description,
            func=func,
            language=self.language,
            owner_agent_types=[self.agent_type],
            tags=tags or [],
            permissions=permissions or [],
            metadata=metadata or {},
        )

    def register_tool(
        self,
        *,
        capability_id: str,
        name: str,
        description: str,
        func: Any,
        tags: list[str] | None = None,
        permissions: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CapabilitySpec:
        return self.capability_registry.register_callable(
            capability_id=capability_id,
            name=name,
            kind=CapabilityKind.TOOL,
            description=description,
            func=func,
            language=self.language,
            owner_agent_types=[self.agent_type],
            tags=tags or [],
            permissions=permissions or [],
            metadata=metadata or {},
        )

    def discover_capabilities(self) -> list[CapabilitySpec]:
        return self.capability_registry.list_specs()

    def health_check(self) -> dict[str, Any]:
        return {
            "adapter_id": self.adapter_id,
            "agent_type": self.agent_type,
            "language": self.language,
            "status": "ok",
            "capability_count": len(self.capability_registry.list_specs()),
        }

    def cancel(self, task_id: str, node_id: str) -> bool:
        # In-process sync worker has nothing to cancel.
        return False

    def execute_task(self, node: TaskNode, context: dict[str, Any]) -> ExecutionResult:
        result = ExecutionResult(node_id=node.id, status=ExecutionStatus.RUNNING, agent_id=self.adapter_id)
        started = time.perf_counter()
        try:
            capabilities = self._select_capabilities(node)
            if not capabilities:
                raise CapabilityNotFoundError(
                    f"No matching capabilities for node={node.id} hints={node.capability_hints}"
                )

            current_input = dict(node.input_data)
            node_outputs: list[dict[str, Any]] = []
            tool_records = []
            for handler in capabilities:
                call_started = time.perf_counter()
                call_ctx = dict(context)
                call_ctx["node"] = node.to_dict()
                call_ctx["worker"] = {
                    "adapter_id": self.adapter_id,
                    "agent_type": self.agent_type,
                    "language": self.language,
                }
                payload = handler(current_input, call_ctx)
                latency_ms = int((time.perf_counter() - call_started) * 1000)
                tool_records.append(self._build_call_record(handler, current_input, payload, latency_ms))
                node_outputs.append(payload)
                # Chain output to next step if provided.
                if isinstance(payload, dict) and "next_input" in payload and isinstance(payload["next_input"], dict):
                    current_input = dict(payload["next_input"])
                elif isinstance(payload, dict) and "output" in payload and isinstance(payload["output"], dict):
                    current_input = dict(payload["output"])

            result.status = ExecutionStatus.SUCCESS
            result.tool_calls = tool_records
            result.output = {
                "steps": node_outputs,
                "final": current_input,
            }
            result.summary = self._summarize_outputs(node, node_outputs)
            for payload in node_outputs:
                if isinstance(payload, dict):
                    for trace_payload in payload.get("llm_traces", []):
                        result.llm_traces.append(
                            LLMTrace(
                                trace_id=trace_payload.get("trace_id", f"trace_{uuid4().hex[:12]}"),
                                prompt=str(trace_payload.get("prompt", "")),
                                response=str(trace_payload.get("response", "")),
                                model=str(trace_payload.get("model", "unknown")),
                                metadata=dict(trace_payload.get("metadata", {})),
                            )
                        )
                    result.artifacts.extend(list(payload.get("artifacts", [])))
            return result
        except Exception as exc:
            result.status = ExecutionStatus.FAILED
            result.errors.append(str(exc))
            result.summary = f"Worker execution failed for node {node.id}: {exc}"
            return result
        finally:
            result.metrics.setdefault("duration_ms", int((time.perf_counter() - started) * 1000))
            result.finish()

    def _select_capabilities(self, node: TaskNode) -> list[CapabilityHandler]:
        specs = self.capability_registry.list_specs()
        if not specs:
            return []
        hints = [h.lower() for h in node.capability_hints]
        scored: list[tuple[float, CapabilitySpec]] = []
        for spec in specs:
            score = 0.0
            name_tokens = spec.name.lower()
            tag_tokens = {t.lower() for t in spec.tags}
            for hint in hints:
                if hint in name_tokens:
                    score += 2.0
                if hint in tag_tokens:
                    score += 1.5
                if hint == spec.capability_id.lower():
                    score += 3.0
            if not hints:
                score += 0.1
            # Prefer skills before tools when scores tie.
            score += 0.2 if spec.kind == CapabilityKind.SKILL else 0.0
            scored.append((score, spec))
        scored.sort(key=lambda item: item[0], reverse=True)
        selected_specs = [spec for score, spec in scored if score > 0]
        if not selected_specs:
            return []
        # Keep a small execution chain to avoid accidental over-execution.
        selected_specs = selected_specs[:3]
        return [
            self.capability_registry.get_handler(spec.capability_id)
            for spec in selected_specs
            if self.capability_registry.get_handler(spec.capability_id) is not None
        ]

    def _build_call_record(
        self,
        handler: CapabilityHandler,
        input_data: dict[str, Any],
        payload: dict[str, Any],
        latency_ms: int,
    ):
        from .models import ToolCallRecord  # local import to avoid circular import at module load

        return ToolCallRecord(
            name=handler.spec.name,
            kind=handler.spec.kind,
            status=ExecutionStatus.SUCCESS,
            latency_ms=latency_ms,
            input_data=dict(input_data),
            output_data=dict(payload) if isinstance(payload, dict) else {"value": payload},
        )

    def _summarize_outputs(self, node: TaskNode, node_outputs: list[dict[str, Any]]) -> str:
        if not node_outputs:
            return f"Node {node.id} completed with no outputs"
        summaries = []
        for item in node_outputs:
            if isinstance(item, dict) and item.get("summary"):
                summaries.append(str(item["summary"]))
        if summaries:
            return " | ".join(summaries[:3])
        return f"Node {node.id} executed {len(node_outputs)} capability step(s)"


def build_default_worker(*, adapter_id: str = "worker_generic_1", agent_type: str = "generic_worker") -> WorkerAgent:
    """Create a generic worker with basic built-in skill/tool capabilities."""

    worker = WorkerAgent(adapter_id=adapter_id, agent_type=agent_type)

    def analyze_capability(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        prompt = str(input_data.get("prompt", ""))
        constraints = dict(input_data.get("constraints", {}))
        bullets = [
            line.strip("- ").strip()
            for line in prompt.replace("。", "\n").replace(".", "\n").splitlines()
            if line.strip()
        ]
        summary = f"提炼需求 {len(bullets)} 条，约束 {len(constraints)} 项"
        return {
            "summary": summary,
            "output": {"requirements": bullets[:20], "constraints": constraints},
        }

    def design_capability(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        prompt = str(input_data.get("prompt", ""))
        return {
            "summary": "生成结构化设计草案",
            "output": {
                "sections": [
                    "目标与范围",
                    "总体架构",
                    "任务规划模型",
                    "执行与监控",
                    "异常恢复",
                ],
                "note": f"Design draft generated for prompt length={len(prompt)}",
            },
        }

    def summarize_capability(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        memory_summary = str(context.get("memory_summary", "")).strip()
        return {
            "summary": "汇总执行结果",
            "output": {
                "final_summary": "任务已完成汇总"
                + (f"；参考记忆摘要 {len(memory_summary)} 字符" if memory_summary else "")
            },
        }

    def generic_tool(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": "工具执行完成",
            "output": {"echo": dict(input_data), "worker": context.get("worker", {})},
        }

    worker.register_skill(
        capability_id="skill.generic.analyze",
        name="analyze_request",
        description="Extract requirements and constraints from user prompt",
        func=analyze_capability,
        tags=["analyze", "requirement", "plan", "generic"],
    )
    worker.register_skill(
        capability_id="skill.generic.design",
        name="design_output",
        description="Create a structured design draft",
        func=design_capability,
        tags=["design", "architecture", "document", "runtime", "generic"],
    )
    worker.register_skill(
        capability_id="skill.generic.summarize",
        name="summarize_result",
        description="Summarize outputs for final response",
        func=summarize_capability,
        tags=["summarize", "report", "finalize", "generic"],
    )
    worker.register_tool(
        capability_id="tool.generic.echo",
        name="echo_tool",
        description="Echo input/output for debugging and tracing",
        func=generic_tool,
        tags=["generic", "execute", "debug"],
    )
    return worker


# Backward-compatible re-export while MasterAgent lives in a dedicated module.
from .master_agent import MasterAgent  # noqa: E402

__all__ = ["WorkerAgent", "build_default_worker", "MasterAgent"]
