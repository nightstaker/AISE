"""Memory management for the runtime."""

from __future__ import annotations

from collections import defaultdict
from threading import RLock
from typing import Any

from ..utils.logging import get_logger
from .models import ExecutionResult, MemoryRecord

logger = get_logger(__name__)


class InMemoryMemoryManager:
    """In-memory memory store with summary/detail retrieval."""

    def __init__(self) -> None:
        self._records: dict[str, MemoryRecord] = {}
        self._by_tenant: dict[str, list[str]] = defaultdict(list)
        self._lock = RLock()

    def store(self, record: MemoryRecord) -> MemoryRecord:
        with self._lock:
            existing = self._records.get(record.memory_id)
            if existing is not None:
                record.version = existing.version + 1
                record.created_at = existing.created_at
            record.updated_at = record.updated_at
            self._records[record.memory_id] = record
            if record.memory_id not in self._by_tenant[record.tenant_id]:
                self._by_tenant[record.tenant_id].append(record.memory_id)
        logger.debug(
            "Memory stored: memory_id=%s tenant=%s user=%s type=%s",
            record.memory_id,
            record.tenant_id,
            record.user_id,
            record.memory_type,
        )
        return record

    def create(
        self,
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
    ) -> MemoryRecord:
        record = MemoryRecord.new(
            tenant_id=tenant_id,
            user_id=user_id,
            scope=scope,
            memory_type=memory_type,
            summary=summary,
            topic_tags=topic_tags,
            source_refs=source_refs,
            detail=detail,
            importance=importance,
            metadata=metadata,
        )
        return self.store(record)

    def list_by_tenant(self, tenant_id: str) -> list[MemoryRecord]:
        with self._lock:
            ids = list(self._by_tenant.get(tenant_id, []))
            return [self._records[mid] for mid in ids]

    def retrieve_summaries(
        self,
        *,
        tenant_id: str,
        user_id: str | None = None,
        topic_tags: list[str] | None = None,
        query_text: str = "",
        top_k: int = 5,
    ) -> list[MemoryRecord]:
        topic_tags = topic_tags or []
        query_tokens = {t.lower() for t in query_text.split() if t.strip()}
        candidates = self.list_by_tenant(tenant_id)
        scored: list[tuple[float, MemoryRecord]] = []
        for rec in candidates:
            if user_id and rec.user_id != user_id:
                continue
            if topic_tags and not set(topic_tags).intersection(set(rec.topic_tags)):
                continue
            summary_tokens = set(rec.summary.lower().split())
            token_overlap = len(query_tokens.intersection(summary_tokens))
            tag_overlap = len(set(topic_tags).intersection(set(rec.topic_tags)))
            score = rec.importance + (0.2 * token_overlap) + (0.15 * tag_overlap)
            if not query_tokens and not topic_tags:
                score = rec.importance
            scored.append((score, rec))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [rec for _, rec in scored[:top_k]]

    def load_details(self, memory_ids: list[str]) -> list[MemoryRecord]:
        with self._lock:
            return [self._records[mid] for mid in memory_ids if mid in self._records]

    def summarize_records(self, records: list[MemoryRecord], max_items: int = 10) -> str:
        parts: list[str] = []
        for rec in records[:max_items]:
            tags = ",".join(rec.topic_tags[:3]) if rec.topic_tags else "-"
            parts.append(f"[{rec.memory_id}]({tags}) {rec.summary}")
        return "\n".join(parts)

    def write_execution_memory(
        self,
        *,
        tenant_id: str,
        user_id: str,
        task_id: str,
        node_id: str,
        result: ExecutionResult,
        topic_tags: list[str] | None = None,
    ) -> MemoryRecord:
        summary = result.summary or f"Node {node_id} finished with status={result.status.value}"
        detail = {
            "node_id": node_id,
            "status": result.status.value,
            "output": result.output,
            "metrics": result.metrics,
            "errors": result.errors,
            "tool_calls": [tc.to_dict() for tc in result.tool_calls],
        }
        return self.create(
            tenant_id=tenant_id,
            user_id=user_id,
            scope="task",
            memory_type="summary",
            summary=summary,
            topic_tags=(topic_tags or []) + ["task_execution"],
            source_refs=[task_id, node_id],
            detail=detail,
            importance=0.7 if result.status.value == "success" else 0.9,
        )
