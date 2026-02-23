"""Task-level retry state and memory persistence for workflow runs."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import RLock
from typing import Any


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class TaskDocRef:
    role: str
    path: str
    name: str
    exists: bool
    glob: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "role": self.role,
            "path": self.path,
            "name": self.name,
            "exists": bool(self.exists),
        }
        if self.glob:
            payload["glob"] = self.glob
        return payload


class RunTaskStateStore:
    """Persists task attempts and active retry operation per workflow run."""

    def __init__(self, file_path: str | Path, *, project_id: str, run_id: str) -> None:
        self.path = Path(file_path)
        self.project_id = project_id
        self.run_id = run_id
        self._lock = RLock()

    def load(self) -> dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return self._empty()
            try:
                payload = json.loads(self.path.read_text(encoding="utf-8"))
            except Exception:
                return self._empty()
            if not isinstance(payload, dict):
                return self._empty()
            payload.setdefault("version", 1)
            payload.setdefault("project_id", self.project_id)
            payload.setdefault("run_id", self.run_id)
            payload.setdefault("updated_at", utc_now_iso())
            payload.setdefault("active_operation", None)
            payload.setdefault("tasks", {})
            if not isinstance(payload.get("tasks"), dict):
                payload["tasks"] = {}
            return payload

    def save(self, payload: dict[str, Any]) -> None:
        with self._lock:
            body = dict(payload)
            body["version"] = 1
            body["project_id"] = self.project_id
            body["run_id"] = self.run_id
            body["updated_at"] = utc_now_iso()
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(f"{self.path.suffix}.{uuid.uuid4().hex}.tmp")
            tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(self.path)

    def update(self, updater) -> dict[str, Any]:
        with self._lock:
            payload = self.load()
            result = updater(payload)
            self.save(payload)
            return result if isinstance(result, dict) else payload

    def set_active_operation(self, active: dict[str, Any] | None) -> dict[str, Any]:
        def _apply(payload: dict[str, Any]) -> dict[str, Any]:
            payload["active_operation"] = active
            return payload

        return self.update(_apply)

    def start_attempt(
        self,
        *,
        phase_key: str,
        task_key: str,
        display_name: str = "",
        kind: str = "retry",
        mode: str = "current",
        executor: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task_store_key = f"{phase_key}::{task_key}"

        def _apply(payload: dict[str, Any]) -> dict[str, Any]:
            tasks = payload.setdefault("tasks", {})
            record = tasks.get(task_store_key)
            if not isinstance(record, dict):
                record = {
                    "phase_key": phase_key,
                    "task_key": task_key,
                    "display_name": display_name or task_key.rsplit(".", 1)[-1],
                    "latest_status": "pending",
                    "latest_attempt_no": 0,
                    "attempts": [],
                }
                tasks[task_store_key] = record
            attempts = record.setdefault("attempts", [])
            if not isinstance(attempts, list):
                attempts = []
                record["attempts"] = attempts
            attempt_no = int(record.get("latest_attempt_no", 0) or 0) + 1
            attempt = {
                "attempt_no": attempt_no,
                "kind": kind,
                "mode": mode,
                "status": "running",
                "started_at": utc_now_iso(),
                "completed_at": None,
                "error": "",
                "executor": dict(executor or {}),
                "context": {},
                "outputs": {},
            }
            attempts.append(attempt)
            record["latest_attempt_no"] = attempt_no
            record["latest_status"] = "running"
            return {"task_store_key": task_store_key, "attempt": attempt}

        return self.update(_apply)

    def patch_attempt(
        self,
        *,
        phase_key: str,
        task_key: str,
        attempt_no: int,
        context_patch: dict[str, Any] | None = None,
        outputs_patch: dict[str, Any] | None = None,
        status: str | None = None,
        error: str | None = None,
        completed: bool = False,
    ) -> dict[str, Any]:
        task_store_key = f"{phase_key}::{task_key}"

        def _apply(payload: dict[str, Any]) -> dict[str, Any]:
            tasks = payload.setdefault("tasks", {})
            record = tasks.get(task_store_key)
            if not isinstance(record, dict):
                raise KeyError(task_store_key)
            attempts = record.get("attempts", [])
            if not isinstance(attempts, list):
                raise KeyError(task_store_key)
            target: dict[str, Any] | None = None
            for item in attempts:
                if isinstance(item, dict) and int(item.get("attempt_no", 0) or 0) == int(attempt_no):
                    target = item
            if target is None:
                raise KeyError(f"{task_store_key} attempt {attempt_no}")
            if context_patch:
                ctx = target.get("context")
                if not isinstance(ctx, dict):
                    ctx = {}
                    target["context"] = ctx
                ctx.update(context_patch)
            if outputs_patch:
                out = target.get("outputs")
                if not isinstance(out, dict):
                    out = {}
                    target["outputs"] = out
                out.update(outputs_patch)
            if status:
                target["status"] = status
                record["latest_status"] = status
            if error is not None:
                target["error"] = error
            if completed:
                target["completed_at"] = utc_now_iso()
            record["latest_attempt_no"] = max(int(record.get("latest_attempt_no", 0) or 0), int(attempt_no))
            return {"task_store_key": task_store_key, "attempt": target}

        return self.update(_apply)

    def summary(self) -> dict[str, Any]:
        payload = self.load()
        tasks = payload.get("tasks", {})
        if not isinstance(tasks, dict):
            tasks = {}
        out: dict[str, Any] = {}
        for key, value in tasks.items():
            if not isinstance(value, dict):
                continue
            attempts = value.get("attempts", [])
            attempts_list = attempts if isinstance(attempts, list) else []
            latest = attempts_list[-1] if attempts_list and isinstance(attempts_list[-1], dict) else {}
            latest_ctx = latest.get("context", {}) if isinstance(latest, dict) else {}
            latest_out = latest.get("outputs", {}) if isinstance(latest, dict) else {}
            doc_refs = latest_ctx.get("doc_refs", []) if isinstance(latest_ctx, dict) else []
            out[key] = {
                "phase_key": str(value.get("phase_key", "")),
                "task_key": str(value.get("task_key", "")),
                "display_name": str(value.get("display_name", "")),
                "latest_status": str(value.get("latest_status", "")),
                "latest_attempt_no": int(value.get("latest_attempt_no", 0) or 0),
                "attempt_count": len(attempts_list),
                "last_error": str((latest or {}).get("error", "")) if isinstance(latest, dict) else "",
                "doc_ref_count": len(doc_refs) if isinstance(doc_refs, list) else 0,
                "updated_at": str((latest or {}).get("completed_at") or (latest or {}).get("started_at") or ""),
                "generated_file_count": len(latest_out.get("generated_files", []))
                if isinstance(latest_out, dict) and isinstance(latest_out.get("generated_files"), list)
                else 0,
            }
        return {
            "active_operation": payload.get("active_operation"),
            "tasks": out,
        }

    def get_task(self, phase_key: str, task_key: str) -> dict[str, Any] | None:
        payload = self.load()
        tasks = payload.get("tasks", {})
        if not isinstance(tasks, dict):
            return None
        item = tasks.get(f"{phase_key}::{task_key}")
        return item if isinstance(item, dict) else None

    def _empty(self) -> dict[str, Any]:
        return {
            "version": 1,
            "project_id": self.project_id,
            "run_id": self.run_id,
            "updated_at": utc_now_iso(),
            "active_operation": None,
            "tasks": {},
        }


class TaskMemoryRecorder:
    """Recorder passed into skills to persist task attempt memory."""

    def __init__(self, store: RunTaskStateStore) -> None:
        self.store = store

    def record_task_attempt_start(self, **kwargs: Any) -> dict[str, Any]:
        return self.store.start_attempt(**kwargs)

    def record_task_attempt_context(
        self,
        *,
        phase_key: str,
        task_key: str,
        attempt_no: int,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        return self.store.patch_attempt(
            phase_key=phase_key,
            task_key=task_key,
            attempt_no=attempt_no,
            context_patch=context,
        )

    def record_task_attempt_output(
        self,
        *,
        phase_key: str,
        task_key: str,
        attempt_no: int,
        outputs: dict[str, Any],
    ) -> dict[str, Any]:
        return self.store.patch_attempt(
            phase_key=phase_key,
            task_key=task_key,
            attempt_no=attempt_no,
            outputs_patch=outputs,
        )

    def record_task_attempt_end(
        self,
        *,
        phase_key: str,
        task_key: str,
        attempt_no: int,
        status: str,
        error: str = "",
    ) -> dict[str, Any]:
        return self.store.patch_attempt(
            phase_key=phase_key,
            task_key=task_key,
            attempt_no=attempt_no,
            status=status,
            error=error,
            completed=True,
        )
