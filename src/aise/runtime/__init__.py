"""Agent Runtime package.

This package provides an in-process MVP runtime for a two-level multi-agent
execution system (Master Agent + Worker Agents) with memory, planning,
scheduling, observability, retry/recovery, and reporting support.
"""

from .agents import WorkerAgent
from .master_agent import MasterAgent
from .memory import InMemoryMemoryManager
from .models import (
    CapabilityKind,
    CapabilitySpec,
    ExecutionResult,
    ExecutionStatus,
    MemoryRecord,
    PlanStrategy,
    Principal,
    RuntimeTask,
    RuntimeTaskStatus,
    TaskNode,
    TaskPlan,
)
from .process import ProcessDefinition, ProcessRepository, ProcessSelection, ProcessStepDefinition
from .runtime import AgentRuntime
from .schema import TASK_PLAN_JSON_SCHEMA, validate_task_plan, validate_task_plan_payload

__all__ = [
    "AgentRuntime",
    "CapabilityKind",
    "CapabilitySpec",
    "ExecutionResult",
    "ExecutionStatus",
    "InMemoryMemoryManager",
    "MasterAgent",
    "MemoryRecord",
    "PlanStrategy",
    "Principal",
    "ProcessDefinition",
    "ProcessRepository",
    "ProcessSelection",
    "ProcessStepDefinition",
    "RuntimeTask",
    "RuntimeTaskStatus",
    "TaskNode",
    "TaskPlan",
    "TASK_PLAN_JSON_SCHEMA",
    "WorkerAgent",
    "validate_task_plan",
    "validate_task_plan_payload",
]
