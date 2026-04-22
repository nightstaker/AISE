"""Aggregator for safety-net telemetry events emitted by
:mod:`aise.runtime.safety_net`.

Events live per-project at ``<project_root>/trace/safety_net_events.jsonl``.
This service scans every project's file at request time, applies the
caller's filters, and returns an aggregated summary shaped for the
``/analytics/safety-net`` dashboard.

Non-goals (explicit to keep the service simple):

- No caching. At realistic scale (dozens of projects, thousands of
  events) the per-request scan is cheap. If this later becomes a
  hot path, a TTL'd in-memory aggregation is an easy follow-up.
- No indexing / search. Filters are applied by a linear pass; the
  dashboard UI is meant for operators poking at capability trends,
  not for ad-hoc BI queries.
- No write path. This service only reads — events are written by
  :func:`aise.runtime.safety_net.run_post_step_check`.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger

logger = get_logger(__name__)


_EVENT_FILE_RELPATH = Path("trace") / "safety_net_events.jsonl"


@dataclass
class _RawEvent:
    """Lightweight internal shape — one parsed line with the project
    it came from. Never exposed; the service returns dicts over HTTP.
    """

    project_id: str
    payload: dict[str, Any]

    @property
    def ts(self) -> str:
        return str(self.payload.get("ts", ""))


@dataclass
class EventSummary:
    """Everything the dashboard renders on one load.

    Counts are integer totals; ``top_*`` lists are ``(key, count)``
    pairs in descending order. ``recent`` carries the freshest events
    with ``project_id`` injected for cross-project drill-down.
    """

    total: int = 0
    by_status: dict[str, int] = field(default_factory=dict)
    by_layer: dict[str, int] = field(default_factory=dict)
    top_step_ids: list[tuple[str, int]] = field(default_factory=list)
    top_repair_actions: list[tuple[str, int]] = field(default_factory=list)
    top_expected: list[tuple[str, int]] = field(default_factory=list)
    recent: list[dict[str, Any]] = field(default_factory=list)
    project_ids_seen: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """JSON-friendly shape. Tuples become 2-element lists; field
        names kept terse to line up with the React consumer."""
        return {
            "total": self.total,
            "by_status": dict(self.by_status),
            "by_layer": dict(self.by_layer),
            "top_step_ids": [{"key": k, "count": c} for k, c in self.top_step_ids],
            "top_repair_actions": [{"key": k, "count": c} for k, c in self.top_repair_actions],
            "top_expected": [{"key": k, "count": c} for k, c in self.top_expected],
            "recent": list(self.recent),
            "project_ids_seen": list(self.project_ids_seen),
        }


class SafetyNetEventsService:
    """Reads safety-net events from every project under ``projects_root``
    and summarizes them for the dashboard.
    """

    def __init__(self, projects_root: str | Path) -> None:
        self._projects_root = Path(projects_root).resolve()

    def list_project_ids(self) -> list[str]:
        """All project directories that currently exist under the
        configured projects_root. Used by the dashboard to populate
        the project-filter dropdown — includes projects that never
        emitted events (so operators can confirm "nothing to see
        here" is a real empty state, not a missing project)."""
        if not self._projects_root.is_dir():
            return []
        return sorted(p.name for p in self._projects_root.iterdir() if p.is_dir())

    def summarize(
        self,
        *,
        project_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
    ) -> EventSummary:
        """Return an aggregated :class:`EventSummary`.

        Filters:

        - ``project_id``: folder name under ``projects_root``. When
          set, only that project's events are read.
        - ``since`` / ``until``: ISO-8601 timestamp strings. Inclusive
          on both ends. Parsed via :func:`datetime.fromisoformat`;
          malformed values are ignored (logged, not raised).
        - ``limit``: maximum number of ``recent`` events to return.
          Aggregated counts are NOT subject to the limit.

        Returns an empty ``EventSummary`` when the events file is
        missing or empty — that's the expected state for a fresh
        deployment, not an error.
        """
        since_dt = _parse_iso(since)
        until_dt = _parse_iso(until)
        limit = max(1, min(limit, 1000))

        targets = self._target_projects(project_id)
        events: list[_RawEvent] = []
        for pid in targets:
            events.extend(self._read_events(pid))

        # Apply time filters BEFORE counting so the counters reflect
        # only the requested window — otherwise a user filtering to
        # "last hour" would see yearly totals in the pills.
        filtered: list[_RawEvent] = []
        for ev in events:
            ts_dt = _parse_iso(ev.ts)
            if since_dt and ts_dt and ts_dt < since_dt:
                continue
            if until_dt and ts_dt and ts_dt > until_dt:
                continue
            filtered.append(ev)

        summary = EventSummary()
        summary.total = len(filtered)
        summary.project_ids_seen = sorted({ev.project_id for ev in filtered})
        summary.by_status = dict(Counter(str(ev.payload.get("repair_status", "")) or "unknown" for ev in filtered))
        summary.by_layer = dict(Counter(str(ev.payload.get("layer", "")) or "unknown" for ev in filtered))
        summary.top_step_ids = Counter(str(ev.payload.get("step_id", "")) or "unknown" for ev in filtered).most_common(
            10
        )
        summary.top_repair_actions = Counter(
            str(ev.payload.get("repair_action", "")) or "unknown" for ev in filtered
        ).most_common(10)
        summary.top_expected = Counter(str(ev.payload.get("expected", "")) or "unknown" for ev in filtered).most_common(
            10
        )

        # Recent first — sort by ts descending, then take the limit.
        # Events without a parseable timestamp sink to the bottom so
        # they don't dominate the view.
        def _sort_key(ev: _RawEvent) -> tuple[int, str]:
            return (0, ev.ts) if ev.ts else (1, "")

        filtered.sort(key=_sort_key, reverse=True)
        summary.recent = [{"project_id": ev.project_id, **ev.payload} for ev in filtered[:limit]]
        return summary

    # -- internals ---------------------------------------------------------

    def _target_projects(self, project_id: str | None) -> list[str]:
        """Resolve the scan list. When ``project_id`` is set, scope
        to that one directory (even if it doesn't exist yet — we'll
        just skip it); otherwise scan everything under projects_root.
        """
        if project_id:
            return [project_id]
        return self.list_project_ids()

    def _read_events(self, project_id: str) -> list[_RawEvent]:
        """Load every JSON line from a project's events file.

        Malformed JSON lines are skipped with a warning — we'd rather
        show partial data than crash the whole dashboard if someone
        appended corrupt content.
        """
        path = self._projects_root / project_id / _EVENT_FILE_RELPATH
        if not path.is_file():
            return []
        events: list[_RawEvent] = []
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.warning("safety_net_events: failed to read %s: %s", path, exc)
            return []
        for lineno, raw in enumerate(text.splitlines(), start=1):
            stripped = raw.strip()
            if not stripped:
                continue
            try:
                payload = json.loads(stripped)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "safety_net_events: bad JSON in %s:%d — %s",
                    path,
                    lineno,
                    exc,
                )
                continue
            if not isinstance(payload, dict):
                continue
            events.append(_RawEvent(project_id=project_id, payload=payload))
        return events


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning ``None`` on anything
    that doesn't parse. Accepts ``Z`` suffix (``datetime.fromisoformat``
    in Python 3.11+ handles it natively, but we normalize to be
    explicit about the contract).
    """
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00") if value.endswith("Z") else value
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        logger.debug("safety_net_events: unparseable ISO timestamp %r", value)
        return None
