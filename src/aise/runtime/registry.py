"""Capability and worker registries."""

from __future__ import annotations

from dataclasses import dataclass, field
from threading import RLock
from typing import Any

from ..utils.logging import get_logger
from .interfaces import CapabilityHandler, LanguageWorkerAdapter
from .models import CapabilityKind, CapabilitySpec

logger = get_logger(__name__)


@dataclass(slots=True)
class CapabilityQuery:
    kind: CapabilityKind | None = None
    tags: list[str] = field(default_factory=list)
    names: list[str] = field(default_factory=list)
    owner_agent_type: str | None = None
    permissions: list[str] = field(default_factory=list)


class CapabilityRegistry:
    """Stores capability metadata and executable handlers."""

    def __init__(self) -> None:
        self._specs: dict[str, CapabilitySpec] = {}
        self._handlers: dict[str, CapabilityHandler] = {}
        self._lock = RLock()

    def register(self, handler: CapabilityHandler) -> None:
        with self._lock:
            self._specs[handler.spec.capability_id] = handler.spec
            self._handlers[handler.spec.capability_id] = handler
        logger.debug(
            "Capability registered: id=%s kind=%s name=%s",
            handler.spec.capability_id,
            handler.spec.kind.value,
            handler.spec.name,
        )

    def register_callable(
        self,
        *,
        capability_id: str,
        name: str,
        kind: CapabilityKind,
        description: str,
        func: Any,
        language: str = "python",
        version: str = "1.0.0",
        tags: list[str] | None = None,
        owner_agent_types: list[str] | None = None,
        permissions: list[str] | None = None,
        input_schema: dict[str, Any] | None = None,
        output_schema: dict[str, Any] | None = None,
        cost_profile: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> CapabilitySpec:
        spec = CapabilitySpec(
            capability_id=capability_id,
            name=name,
            kind=kind,
            description=description,
            language=language,
            version=version,
            tags=tags or [],
            owner_agent_types=owner_agent_types or [],
            permissions=permissions or [],
            input_schema=input_schema or {},
            output_schema=output_schema or {},
            cost_profile=cost_profile or {},
            metadata=metadata or {},
        )
        self.register(CapabilityHandler(spec=spec, func=func))
        return spec

    def get_spec(self, capability_id: str) -> CapabilitySpec | None:
        with self._lock:
            return self._specs.get(capability_id)

    def get_handler(self, capability_id: str) -> CapabilityHandler | None:
        with self._lock:
            return self._handlers.get(capability_id)

    def list_specs(self) -> list[CapabilitySpec]:
        with self._lock:
            return list(self._specs.values())

    def query(self, query: CapabilityQuery) -> list[CapabilitySpec]:
        with self._lock:
            specs = list(self._specs.values())
        filtered: list[CapabilitySpec] = []
        for spec in specs:
            if query.kind and spec.kind != query.kind:
                continue
            if query.names and spec.name not in query.names and spec.capability_id not in query.names:
                continue
            if query.owner_agent_type and query.owner_agent_type not in spec.owner_agent_types:
                continue
            if query.tags and not set(query.tags).issubset(set(spec.tags)):
                continue
            if query.permissions and not set(query.permissions).issubset(set(spec.permissions)):
                continue
            filtered.append(spec)
        return filtered

    def execute(self, capability_id: str, input_data: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
        handler = self.get_handler(capability_id)
        if handler is None:
            raise KeyError(f"Capability not found: {capability_id}")
        return handler(input_data, context)


class WorkerRegistry:
    """Registry of worker adapters/agents visible to the master."""

    def __init__(self) -> None:
        self._workers: dict[str, LanguageWorkerAdapter] = {}
        self._lock = RLock()

    def register(self, worker: LanguageWorkerAdapter) -> None:
        with self._lock:
            self._workers[worker.adapter_id] = worker
        logger.debug(
            "Worker registered: id=%s type=%s language=%s",
            worker.adapter_id,
            worker.agent_type,
            worker.language,
        )

    def get(self, adapter_id: str) -> LanguageWorkerAdapter | None:
        with self._lock:
            return self._workers.get(adapter_id)

    def list_all(self) -> list[LanguageWorkerAdapter]:
        with self._lock:
            return list(self._workers.values())

    def list_by_type(self, agent_type: str) -> list[LanguageWorkerAdapter]:
        with self._lock:
            return [w for w in self._workers.values() if w.agent_type == agent_type]

    def scan_capabilities(self) -> dict[str, list[CapabilitySpec]]:
        result: dict[str, list[CapabilitySpec]] = {}
        for worker in self.list_all():
            try:
                result[worker.adapter_id] = worker.discover_capabilities()
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("Worker capability scan failed: worker=%s error=%s", worker.adapter_id, exc)
                result[worker.adapter_id] = []
        return result
