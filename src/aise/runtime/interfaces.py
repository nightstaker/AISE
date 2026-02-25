"""Protocol interfaces for runtime extension points."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Protocol

from .models import CapabilitySpec, ExecutionResult, LLMTrace, TaskNode


class LanguageWorkerAdapter(Protocol):
    """Adapter interface for cross-language worker agents."""

    adapter_id: str
    agent_type: str
    language: str

    def discover_capabilities(self) -> list[CapabilitySpec]:
        """Return capabilities provided by this worker."""

    def execute_task(self, node: TaskNode, context: dict[str, Any]) -> ExecutionResult:
        """Execute one task node and return a structured result."""

    def health_check(self) -> dict[str, Any]:
        """Return adapter health status."""

    def cancel(self, task_id: str, node_id: str) -> bool:
        """Cancel an in-flight execution if supported."""


class LLMClientProtocol(Protocol):
    """Minimal LLM client interface used by runtime agents."""

    def complete(self, prompt: str, **kwargs: Any) -> str:
        """Generate a completion from a prompt."""


@dataclass(slots=True)
class CapabilityHandler:
    """Callable handler for a skill/tool capability."""

    spec: CapabilitySpec
    func: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]

    def __call__(self, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        return self.func(input_data, context)


@dataclass(slots=True)
class LLMRecorder:
    """Helper for capturing complete LLM interaction traces."""

    traces: list[LLMTrace] = field(default_factory=list)

    def record(self, trace: LLMTrace) -> None:
        self.traces.append(trace)
