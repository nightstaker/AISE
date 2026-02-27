"""Worker agents and in-process worker adapter implementations."""

from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from threading import RLock
from typing import Any
from uuid import uuid4

import json
import re

from ..agents.prompts import load_agent_prompt_section, resolve_agent_prompt_md_path
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

DEFAULT_RUNTIME_AGENT_TYPES: tuple[str, ...] = ("generic_worker",)


@lru_cache(maxsize=128)
def _load_agent_instruction(agent_type: str) -> str:
    """Load agent instruction text from ``src/aise/agents/<agent>_agent.md``."""
    name = str(agent_type or "").strip()
    if not name:
        return ""
    try:
        section = load_agent_prompt_section(name, heading="System Prompt", level=2).strip()
        if section:
            return section
    except Exception:
        pass

    # Fallback to top slice of markdown for agents without a dedicated System Prompt section.
    try:
        path = resolve_agent_prompt_md_path(name)
        if path is not None and path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text[:2000]
    except Exception:
        pass
    return ""


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
            # Fallback to a single default capability so execution remains md-driven.
            selected_specs = [scored[0][1]] if scored else []
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


def discover_runtime_agent_types_from_markdown() -> list[str]:
    """Discover runtime agent types from ``src/aise/agents/*agent.md`` filenames."""
    agent_dir = Path(__file__).resolve().parents[1] / "agents"
    discovered: list[str] = []
    try:
        files = sorted(agent_dir.glob("*agent.md"))
    except Exception:
        files = []
    for path in files:
        stem = path.stem.strip().lower()  # e.g. "product_manager_agent"
        if not stem.endswith("_agent"):
            continue
        name = stem[: -len("_agent")].strip().replace("-", "_").replace(" ", "_")
        if not name:
            continue
        discovered.append(name)
    # Keep deterministic order, unique values, and always include generic fallback.
    ordered: list[str] = []
    seen: set[str] = set()
    for item in ["generic_worker", *discovered]:
        if item in seen:
            continue
        seen.add(item)
        ordered.append(item)
    return ordered


def build_default_worker(
    *,
    adapter_id: str = "worker_generic_1",
    agent_type: str = "generic_worker",
    llm_client: LLMClientProtocol | None = None,
) -> WorkerAgent:
    """Create an md-driven worker with a generic execution capability."""

    worker = WorkerAgent(adapter_id=adapter_id, agent_type=agent_type, llm_client=llm_client)

    def _slug(value: str) -> str:
        text = re.sub(r"[^a-zA-Z0-9]+", "-", str(value).strip().lower()).strip("-")
        return text or "output"

    def _extract_first_json(text: str) -> Any | None:
        raw = str(text or "").strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            pass
        m = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw, flags=re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            if candidate:
                try:
                    return json.loads(candidate)
                except Exception:
                    pass
        start = raw.find("{")
        if start < 0:
            return None
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
                    try:
                        return json.loads(raw[start : idx + 1])
                    except Exception:
                        return None
        return None

    def _safe_write_files(context: dict[str, Any], node_ctx: dict[str, Any], artifacts: list[dict[str, Any]]) -> list[str]:
        generated: list[str] = []
        task_constraints = context.get("task_constraints", {})
        project_root = (
            str(task_constraints.get("project_root", "")).strip() if isinstance(task_constraints, dict) else ""
        )
        if not project_root:
            return generated
        root = Path(project_root).resolve()
        root.mkdir(parents=True, exist_ok=True)

        for item in artifacts:
            if not isinstance(item, dict):
                continue
            rel = str(item.get("path", "")).strip().replace("\\", "/")
            content = str(item.get("content", ""))
            if not rel:
                continue
            target = (root / rel).resolve()
            if root not in target.parents and target != root:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            generated.append(str(target.relative_to(root)))

        if generated:
            return generated

        # Fallback: always persist one markdown note per executed node.
        node_id = str(node_ctx.get("id", "")).strip() or "task"
        node_name = str(node_ctx.get("name", "")).strip() or node_id
        fallback_rel = f"docs/{worker.agent_type}-{_slug(node_id)}.md"
        target = (root / fallback_rel).resolve()
        if root in target.parents or target == root:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(
                f"# {node_name}\n\n- agent: {worker.agent_type}\n- node_id: {node_id}\n\n"
                f"Execution output has been recorded in runtime result.\n",
                encoding="utf-8",
            )
            generated.append(fallback_rel)
        return generated

    def _llm_complete(prompt: str, context: dict[str, Any], fallback: str) -> str:
        client = worker.llm_client
        if client is None:
            return fallback
        set_ctx = getattr(client, "set_call_context", None)
        clear_ctx = getattr(client, "clear_call_context", None)
        try:
            agent_instruction = _load_agent_instruction(worker.agent_type)
            effective_prompt = (
                f"Agent Instruction:\n{agent_instruction}\n\nTask Input:\n{prompt}"
                if agent_instruction
                else prompt
            )
            if callable(set_ctx):
                task_constraints = context.get("task_constraints", {})
                trace_dir = ""
                project_root = (
                    str(task_constraints.get("project_root", "")).strip() if isinstance(task_constraints, dict) else ""
                )
                if project_root:
                    trace_dir = str((Path(project_root) / "trace").resolve())
                else:
                    project_id = (
                        str(task_constraints.get("project_id", "")).strip()
                        if isinstance(task_constraints, dict)
                        else ""
                    )
                    if project_id:
                        trace_dir = f"projects/{project_id}/trace"
                set_ctx(
                    {
                        "agent": f"runtime_worker:{worker.agent_type}",
                        "role": worker.agent_type,
                        "skill": "default_capability",
                        "project_root": project_root,
                        "trace_dir": trace_dir,
                    }
                )
            response = str(client.complete(effective_prompt)).strip()
            return response or fallback
        except Exception:
            logger.exception("Default worker LLM fallback triggered: adapter=%s", worker.adapter_id)
            return fallback
        finally:
            if callable(clear_ctx):
                try:
                    clear_ctx()
                except Exception:
                    pass

    def agent_execute_capability(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        task_prompt = (
            str(input_data.get("prompt", "")).strip()
            or str(input_data.get("task", "")).strip()
            or str(input_data.get("description", "")).strip()
        )
        if not task_prompt:
            task_prompt = json.dumps(input_data, ensure_ascii=False)

        node_ctx = context.get("node", {}) if isinstance(context.get("node", {}), dict) else {}
        process_ctx = context.get("process_context", {})
        step_ctx = context.get("process_step_context", {})
        requirements = context.get("effective_agent_requirements", [])
        memory_summary = str(context.get("memory_summary", "")).strip()

        llm_prompt = (
            "Execute the assigned task according to Agent Instruction.\n"
            "Return JSON only with keys: summary(string), artifacts(array), result(any).\n"
            "Each artifact item must include path(relative path under project root) and content(string).\n"
            "If task requires document/code/test/review outputs, artifacts must contain concrete files.\n\n"
            f"Task Prompt:\n{task_prompt}\n\n"
            f"Node Context(JSON):\n{json.dumps(node_ctx, ensure_ascii=False)}\n\n"
            f"Input Data(JSON):\n{json.dumps(input_data, ensure_ascii=False)}\n\n"
            f"Process Context(JSON):\n{json.dumps(process_ctx, ensure_ascii=False)}\n\n"
            f"Process Step Context(JSON):\n{json.dumps(step_ctx, ensure_ascii=False)}\n\n"
            f"Effective Requirements(JSON):\n{json.dumps(requirements, ensure_ascii=False)}\n\n"
            f"Memory Summary:\n{memory_summary}"
        )
        llm_text = _llm_complete(llm_prompt, context, "")
        parsed = _extract_first_json(llm_text) if llm_text else None
        artifacts = parsed.get("artifacts", []) if isinstance(parsed, dict) else []
        generated_files = _safe_write_files(context, node_ctx, artifacts if isinstance(artifacts, list) else [])
        summary = ""
        if isinstance(parsed, dict):
            summary = str(parsed.get("summary", "")).strip()
        if not summary:
            summary = llm_text.splitlines()[0].strip() if llm_text.strip() else f"Executed task: {worker.agent_type}"
        return {
            "summary": summary,
            "output": (
                {"result": parsed, "result_text": llm_text, "generated_files": generated_files}
                if parsed is not None
                else {"result_text": llm_text, "task_prompt": task_prompt, "generated_files": generated_files}
            ),
        }

    def generic_tool(input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return {
            "summary": "Tool execution completed",
            "output": {"echo": dict(input_data), "worker": context.get("worker", {})},
        }

    worker.register_skill(
        capability_id=f"skill.{worker.agent_type}.execute",
        name="agent_execute",
        description="Execute task strictly guided by the agent markdown prompt",
        func=agent_execute_capability,
        tags=[
            "execute",
            "agent",
            "md-driven",
            "requirement",
            "design",
            "implementation",
            "testing",
            "review",
            "generic",
        ],
    )
    worker.register_tool(
        capability_id="tool.generic.echo",
        name="echo_tool",
        description="Echo input/output for debugging and tracing",
        func=generic_tool,
        tags=["generic", "execute", "debug"],
    )
    return worker


def build_default_worker_fleet(
    *,
    llm_client: LLMClientProtocol | None = None,
    agent_types: list[str] | None = None,
) -> list[WorkerAgent]:
    fleet_types = agent_types or discover_runtime_agent_types_from_markdown() or list(DEFAULT_RUNTIME_AGENT_TYPES)
    out: list[WorkerAgent] = []
    for idx, raw_type in enumerate(fleet_types, start=1):
        agent_type = str(raw_type).strip().lower().replace(" ", "_")
        if not agent_type:
            continue
        out.append(
            build_default_worker(
                adapter_id=f"worker_{agent_type}_{idx}",
                agent_type=agent_type,
                llm_client=llm_client,
            )
        )
    return out


# Backward-compatible re-export while MasterAgent lives in a dedicated module.
from .master_agent import MasterAgent  # noqa: E402

__all__ = [
    "WorkerAgent",
    "build_default_worker",
    "build_default_worker_fleet",
    "discover_runtime_agent_types_from_markdown",
    "MasterAgent",
]
