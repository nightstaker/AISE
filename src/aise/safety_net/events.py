"""Telemetry event emitter — writes ``trace/safety_net_events.jsonl``."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger

logger = get_logger(__name__)


def _events_path(project_root: Path) -> Path:
    """Where the structured events land. ``trace/`` is already on the
    baseline ``.gitignore`` so events stay out of commits by default.
    """
    return project_root / "trace" / "safety_net_events.jsonl"


def _emit_event(project_root: Path, payload: dict[str, Any]) -> bool:
    """Append a JSON event to the project's safety-net log. Returns
    ``True`` if the line was written, ``False`` on any IO error. Errors
    are logged but not raised — the safety net must not block on
    telemetry."""
    path = _events_path(project_root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False))
            fp.write("\n")
        return True
    except OSError as exc:
        logger.warning("safety_net: failed to emit event: path=%s err=%s", path, exc)
        return False


def _make_event(
    *,
    step_id: str,
    layer: str,
    expected: str,
    actual: str,
    repair_action: str,
    repair_status: str,
    detail: str = "",
) -> dict[str, Any]:
    """Build the canonical telemetry event. Schema is stable; the
    dashboard (issue #122) parses these as-is."""
    return {
        "event_type": "llm_fallback_triggered",
        "step_id": step_id,
        "layer": layer,
        "expected": expected,
        "actual": actual,
        "repair_action": repair_action,
        "repair_status": repair_status,
        "detail": detail[:500] if detail else "",
        "ts": datetime.now(timezone.utc).isoformat(),
    }
