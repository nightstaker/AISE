"""Core data models for the agent runtime."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any
from uuid import uuid4


def _now() -> datetime:
    return datetime.now(UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class CapabilityKind(str, Enum):
    SKILL = "skill"
    TOOL = "tool"


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial_success"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class RuntimeTaskStatus(str, Enum):
    CREATED = "created"
    PLANNING = "planning"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class TaskMode(str, Enum):
    SERIAL = "serial"
    PARALLEL = "parallel"


@dataclass(slots=True)
class Principal:
    """Authenticated user/service principal."""

    user_id: str
    tenant_id: str
    roles: list[str] = field(default_factory=list)
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class CapabilitySpec:
    """Metadata for a skill/tool capability."""

    capability_id: str
    name: str
    kind: CapabilityKind
    description: str
    language: str = "python"
    version: str = "1.0.0"
    tags: list[str] = field(default_factory=list)
    owner_agent_types: list[str] = field(default_factory=list)
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    permissions: list[str] = field(default_factory=list)
    cost_profile: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "name": self.name,
            "kind": self.kind.value,
            "description": self.description,
            "language": self.language,
            "version": self.version,
            "tags": list(self.tags),
            "owner_agent_types": list(self.owner_agent_types),
            "input_schema": dict(self.input_schema),
            "output_schema": dict(self.output_schema),
            "permissions": list(self.permissions),
            "cost_profile": dict(self.cost_profile),
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class PlanStrategy:
    max_parallelism: int = 4
    budget: dict[str, Any] = field(default_factory=lambda: {"tokens": 200_000, "time_sec": 1800})
    replan_policy: str = "on_failure_or_new_evidence"

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_parallelism": self.max_parallelism,
            "budget": dict(self.budget),
            "replan_policy": self.replan_policy,
        }


@dataclass(slots=True)
class TaskNode:
    """A node in a task plan DAG, optionally with nested child tasks."""

    id: str
    name: str
    mode: TaskMode = TaskMode.SERIAL
    assigned_agent_type: str | None = None
    dependencies: list[str] = field(default_factory=list)
    priority: str = "medium"
    input_data: dict[str, Any] = field(default_factory=dict)
    capability_hints: list[str] = field(default_factory=list)
    memory_policy: dict[str, Any] = field(default_factory=dict)
    success_criteria: list[str] = field(default_factory=list)
    children: list["TaskNode"] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    execute_self: bool = True

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskNode":
        mode = TaskMode(str(payload.get("mode", "serial")))
        children = [cls.from_dict(child) for child in payload.get("children", [])]
        return cls(
            id=str(payload["id"]),
            name=str(payload["name"]),
            mode=mode,
            assigned_agent_type=payload.get("assigned_agent_type"),
            dependencies=list(payload.get("dependencies", [])),
            priority=str(payload.get("priority", "medium")),
            input_data=dict(payload.get("input_data", {})),
            capability_hints=list(payload.get("capability_hints", [])),
            memory_policy=dict(payload.get("memory_policy", {})),
            success_criteria=list(payload.get("success_criteria", [])),
            children=children,
            metadata=dict(payload.get("metadata", {})),
            execute_self=bool(payload.get("execute_self", True)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "mode": self.mode.value,
            "assigned_agent_type": self.assigned_agent_type,
            "dependencies": list(self.dependencies),
            "priority": self.priority,
            "input_data": dict(self.input_data),
            "capability_hints": list(self.capability_hints),
            "memory_policy": dict(self.memory_policy),
            "success_criteria": list(self.success_criteria),
            "children": [child.to_dict() for child in self.children],
            "metadata": dict(self.metadata),
            "execute_self": self.execute_self,
        }


@dataclass(slots=True)
class TaskPlan:
    """Master-generated JSON-compatible plan."""

    task_name: str
    tasks: list[TaskNode]
    plan_id: str = field(default_factory=lambda: _new_id("plan"))
    version: int = 1
    strategy: PlanStrategy = field(default_factory=PlanStrategy)
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "TaskPlan":
        strategy_payload = payload.get("strategy", {})
        strategy = PlanStrategy(
            max_parallelism=int(strategy_payload.get("max_parallelism", 4)),
            budget=dict(strategy_payload.get("budget", {"tokens": 200_000, "time_sec": 1800})),
            replan_policy=str(strategy_payload.get("replan_policy", "on_failure_or_new_evidence")),
        )
        return cls(
            plan_id=str(payload.get("plan_id", _new_id("plan"))),
            task_name=str(payload["task_name"]),
            version=int(payload.get("version", 1)),
            strategy=strategy,
            tasks=[TaskNode.from_dict(item) for item in payload.get("tasks", [])],
            metadata=dict(payload.get("metadata", {})),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "plan_id": self.plan_id,
            "task_name": self.task_name,
            "version": self.version,
            "strategy": self.strategy.to_dict(),
            "tasks": [node.to_dict() for node in self.tasks],
            "metadata": dict(self.metadata),
        }


@dataclass(slots=True)
class LLMTrace:
    trace_id: str
    prompt: str
    response: str
    model: str = "unknown"
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)


@dataclass(slots=True)
class ToolCallRecord:
    name: str
    kind: CapabilityKind
    status: ExecutionStatus
    latency_ms: int = 0
    input_data: dict[str, Any] = field(default_factory=dict)
    output_data: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "status": self.status.value,
            "latency_ms": self.latency_ms,
            "input_data": dict(self.input_data),
            "output_data": dict(self.output_data),
            "error": self.error,
        }


@dataclass(slots=True)
class ExecutionResult:
    node_id: str
    status: ExecutionStatus
    summary: str = ""
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    output: dict[str, Any] = field(default_factory=dict)
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    llm_traces: list[LLMTrace] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    agent_id: str | None = None
    started_at: datetime = field(default_factory=_now)
    finished_at: datetime | None = None

    def finish(self) -> None:
        self.finished_at = _now()
        if "duration_ms" not in self.metrics:
            self.metrics["duration_ms"] = int((self.finished_at - self.started_at).total_seconds() * 1000)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "status": self.status.value,
            "summary": self.summary,
            "artifacts": list(self.artifacts),
            "output": dict(self.output),
            "tool_calls": [record.to_dict() for record in self.tool_calls],
            "llm_traces": [trace.trace_id for trace in self.llm_traces],
            "metrics": dict(self.metrics),
            "errors": list(self.errors),
            "agent_id": self.agent_id,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }


@dataclass(slots=True)
class MemoryRecord:
    memory_id: str
    tenant_id: str
    user_id: str
    scope: str
    memory_type: str
    topic_tags: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)
    summary: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    importance: float = 0.5
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    version: int = 1

    @classmethod
    def new(
        cls,
        *,
        tenant_id: str,
        user_id: str,
        scope: str,
        memory_type: str,
        summary: str,
        topic_tags: list[str] | None = None,
        source_refs: list[str] | None = None,
        detail: dict[str, Any] | None = None,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> "MemoryRecord":
        return cls(
            memory_id=_new_id("mem"),
            tenant_id=tenant_id,
            user_id=user_id,
            scope=scope,
            memory_type=memory_type,
            summary=summary,
            topic_tags=topic_tags or [],
            source_refs=source_refs or [],
            detail=detail or {},
            importance=importance,
            metadata=metadata or {},
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "memory_id": self.memory_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "scope": self.scope,
            "memory_type": self.memory_type,
            "topic_tags": list(self.topic_tags),
            "source_refs": list(self.source_refs),
            "summary": self.summary,
            "detail": dict(self.detail),
            "importance": self.importance,
            "metadata": dict(self.metadata),
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "version": self.version,
        }


@dataclass(slots=True)
class RuntimeTask:
    """Task submitted by a user to the runtime."""

    principal: Principal
    prompt: str
    task_id: str = field(default_factory=lambda: _new_id("task"))
    status: RuntimeTaskStatus = RuntimeTaskStatus.CREATED
    created_at: datetime = field(default_factory=_now)
    updated_at: datetime = field(default_factory=_now)
    task_name: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
    plan: TaskPlan | None = None
    node_results: dict[str, ExecutionResult] = field(default_factory=dict)
    final_output: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    report: dict[str, Any] | None = None

    def touch(self) -> None:
        self.updated_at = _now()

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "prompt": self.prompt,
            "tenant_id": self.principal.tenant_id,
            "user_id": self.principal.user_id,
            "roles": list(self.principal.roles),
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "task_name": self.task_name,
            "constraints": dict(self.constraints),
            "metadata": dict(self.metadata),
            "plan": self.plan.to_dict() if self.plan else None,
            "node_results": {k: v.to_dict() for k, v in self.node_results.items()},
            "final_output": dict(self.final_output),
            "errors": list(self.errors),
            "report": dict(self.report) if self.report else None,
        }
