"""Tests for the safety-net events aggregator (issue #122 backend).

The service reads JSONL events written by
:mod:`aise.safety_net` across every project directory and
shapes them for the dashboard. These tests pin the aggregation
contract so the React consumer can rely on the JSON shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from aise.web.safety_net_events_service import SafetyNetEventsService


def _seed_events(projects_root: Path, project_id: str, events: list[dict]) -> None:
    """Write a JSONL file mimicking the safety-net's output format."""
    events_path = projects_root / project_id / "trace" / "safety_net_events.jsonl"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    with events_path.open("w", encoding="utf-8") as fp:
        for event in events:
            fp.write(json.dumps(event, ensure_ascii=False))
            fp.write("\n")


def _event(
    *,
    ts: str,
    step_id: str = "scaffold",
    layer: str = "B",
    expected: str = "git_repo",
    repair_action: str = "missing_git_repo",
    repair_status: str = "success",
    detail: str = "",
) -> dict:
    """Build a canonical event with safe defaults — keeps the test
    bodies focused on the axis each case cares about."""
    return {
        "event_type": "llm_fallback_triggered",
        "step_id": step_id,
        "layer": layer,
        "expected": expected,
        "actual": "repaired",
        "repair_action": repair_action,
        "repair_status": repair_status,
        "detail": detail,
        "ts": ts,
    }


class TestEmptyAndMissing:
    def test_missing_projects_root_returns_empty(self, tmp_path: Path) -> None:
        svc = SafetyNetEventsService(tmp_path / "nonexistent")
        summary = svc.summarize()
        assert summary.total == 0
        assert summary.recent == []
        assert summary.project_ids_seen == []
        assert svc.list_project_ids() == []

    def test_empty_projects_root_returns_empty(self, tmp_path: Path) -> None:
        (tmp_path / "projects").mkdir()
        svc = SafetyNetEventsService(tmp_path / "projects")
        summary = svc.summarize()
        assert summary.total == 0
        assert svc.list_project_ids() == []

    def test_project_without_events_file_is_silent(self, tmp_path: Path) -> None:
        (tmp_path / "projects" / "project_0-x" / "trace").mkdir(parents=True)
        svc = SafetyNetEventsService(tmp_path / "projects")
        summary = svc.summarize()
        assert summary.total == 0
        # Project still appears in the dropdown list — the operator
        # should be able to see "here it is, no events yet" rather
        # than guess whether it exists.
        assert svc.list_project_ids() == ["project_0-x"]


class TestAggregation:
    def test_basic_counts_across_two_projects(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _seed_events(
            root,
            "project_0",
            [
                _event(ts="2026-04-22T10:00:00+00:00", layer="B", repair_status="success"),
                _event(ts="2026-04-22T10:01:00+00:00", layer="A", repair_status="success"),
                _event(ts="2026-04-22T10:02:00+00:00", layer="B", repair_status="failed"),
            ],
        )
        _seed_events(
            root,
            "project_1",
            [
                _event(ts="2026-04-22T11:00:00+00:00", layer="B", repair_status="skipped"),
            ],
        )
        svc = SafetyNetEventsService(root)
        summary = svc.summarize()
        assert summary.total == 4
        assert summary.by_status == {"success": 2, "failed": 1, "skipped": 1}
        assert summary.by_layer == {"B": 3, "A": 1}
        assert set(summary.project_ids_seen) == {"project_0", "project_1"}
        # Recent is ts-descending.
        assert [ev["ts"] for ev in summary.recent] == [
            "2026-04-22T11:00:00+00:00",
            "2026-04-22T10:02:00+00:00",
            "2026-04-22T10:01:00+00:00",
            "2026-04-22T10:00:00+00:00",
        ]

    def test_top_lists_rank_by_count_descending(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _seed_events(
            root,
            "project_0",
            [
                _event(ts=f"2026-04-22T10:{i:02}:00+00:00", step_id="scaffold", repair_action="missing_git_repo")
                for i in range(5)
            ]
            + [
                _event(ts=f"2026-04-22T11:{i:02}:00+00:00", step_id="phase_1", repair_action="uncommitted_changes")
                for i in range(3)
            ]
            + [
                _event(ts=f"2026-04-22T12:{i:02}:00+00:00", step_id="phase_2", repair_action="missing_phase_tag")
                for i in range(1)
            ],
        )
        svc = SafetyNetEventsService(root)
        summary = svc.summarize()
        assert summary.top_step_ids[:3] == [("scaffold", 5), ("phase_1", 3), ("phase_2", 1)]
        assert summary.top_repair_actions[:3] == [
            ("missing_git_repo", 5),
            ("uncommitted_changes", 3),
            ("missing_phase_tag", 1),
        ]

    def test_recent_respects_limit(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _seed_events(root, "project_0", [_event(ts=f"2026-04-22T10:{i:02}:00+00:00") for i in range(15)])
        svc = SafetyNetEventsService(root)
        summary = svc.summarize(limit=5)
        assert summary.total == 15  # total is NOT capped by limit
        assert len(summary.recent) == 5
        # Newest first.
        assert summary.recent[0]["ts"] > summary.recent[-1]["ts"]

    def test_recent_includes_project_id(self, tmp_path: Path) -> None:
        """The table shows events from multiple projects; each row
        must be tagged with its project so the operator can drill in."""
        root = tmp_path / "projects"
        _seed_events(root, "project_0", [_event(ts="2026-04-22T10:00:00+00:00")])
        _seed_events(root, "project_1", [_event(ts="2026-04-22T11:00:00+00:00")])
        svc = SafetyNetEventsService(root)
        summary = svc.summarize()
        by_ts = {ev["ts"]: ev for ev in summary.recent}
        assert by_ts["2026-04-22T10:00:00+00:00"]["project_id"] == "project_0"
        assert by_ts["2026-04-22T11:00:00+00:00"]["project_id"] == "project_1"


class TestFilters:
    def test_project_id_filter_scopes_to_one(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _seed_events(root, "project_0", [_event(ts="2026-04-22T10:00:00+00:00")])
        _seed_events(root, "project_1", [_event(ts="2026-04-22T11:00:00+00:00")])
        svc = SafetyNetEventsService(root)
        summary = svc.summarize(project_id="project_1")
        assert summary.total == 1
        assert summary.project_ids_seen == ["project_1"]

    def test_nonexistent_project_id_returns_empty(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _seed_events(root, "project_0", [_event(ts="2026-04-22T10:00:00+00:00")])
        svc = SafetyNetEventsService(root)
        summary = svc.summarize(project_id="does-not-exist")
        assert summary.total == 0

    def test_project_id_path_traversal_is_rejected(self, tmp_path: Path) -> None:
        """The ``project_id`` filter comes straight from the query
        string; it must not be able to escape ``projects_root``. A
        bait file is planted as a sibling of ``projects_root`` at the
        exact path a traversal would resolve to — if the guard is
        missing, the service would read it.
        """
        root = tmp_path / "projects"
        _seed_events(root, "legit_project", [_event(ts="2026-04-22T10:00:00+00:00")])
        bait = tmp_path / "leaked" / "trace" / "safety_net_events.jsonl"
        bait.parent.mkdir(parents=True)
        bait.write_text(json.dumps(_event(ts="2099-01-01T00:00:00+00:00")) + "\n", encoding="utf-8")

        svc = SafetyNetEventsService(root)
        assert svc.summarize(project_id="../leaked").total == 0
        assert svc.summarize(project_id="/etc").total == 0
        assert svc.summarize(project_id="legit_project/../../leaked").total == 0

    def test_since_filter_excludes_older_events(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _seed_events(
            root,
            "project_0",
            [
                _event(ts="2026-04-22T09:00:00+00:00"),
                _event(ts="2026-04-22T10:00:00+00:00"),
                _event(ts="2026-04-22T11:00:00+00:00"),
            ],
        )
        svc = SafetyNetEventsService(root)
        summary = svc.summarize(since="2026-04-22T10:00:00+00:00")
        assert summary.total == 2
        assert [ev["ts"] for ev in summary.recent] == [
            "2026-04-22T11:00:00+00:00",
            "2026-04-22T10:00:00+00:00",
        ]

    def test_until_filter_excludes_newer_events(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _seed_events(
            root,
            "project_0",
            [
                _event(ts="2026-04-22T09:00:00+00:00"),
                _event(ts="2026-04-22T10:00:00+00:00"),
                _event(ts="2026-04-22T11:00:00+00:00"),
            ],
        )
        svc = SafetyNetEventsService(root)
        summary = svc.summarize(until="2026-04-22T10:00:00+00:00")
        assert summary.total == 2

    def test_since_and_until_combine_as_inclusive_range(self, tmp_path: Path) -> None:
        root = tmp_path / "projects"
        _seed_events(
            root,
            "project_0",
            [
                _event(ts="2026-04-22T09:00:00+00:00"),
                _event(ts="2026-04-22T10:00:00+00:00"),
                _event(ts="2026-04-22T11:00:00+00:00"),
                _event(ts="2026-04-22T12:00:00+00:00"),
            ],
        )
        svc = SafetyNetEventsService(root)
        summary = svc.summarize(
            since="2026-04-22T10:00:00+00:00",
            until="2026-04-22T11:00:00+00:00",
        )
        assert summary.total == 2

    def test_malformed_since_is_ignored_not_raised(self, tmp_path: Path) -> None:
        """Don't block the dashboard on a bad query string — the
        filter degrades to "no time bound" and the operator sees
        everything. Logged at debug-level."""
        root = tmp_path / "projects"
        _seed_events(root, "project_0", [_event(ts="2026-04-22T09:00:00+00:00")])
        svc = SafetyNetEventsService(root)
        summary = svc.summarize(since="not-a-timestamp")
        assert summary.total == 1


class TestParserResilience:
    def test_malformed_jsonl_line_is_skipped(self, tmp_path: Path, caplog) -> None:
        """A truncated / corrupt line must not crash the whole
        dashboard — parse what we can, log the bad line, move on."""
        events_path = tmp_path / "projects" / "project_0" / "trace" / "safety_net_events.jsonl"
        events_path.parent.mkdir(parents=True)
        events_path.write_text(
            json.dumps(_event(ts="2026-04-22T10:00:00+00:00"))
            + "\n"
            + "{not a complete json\n"
            + json.dumps(_event(ts="2026-04-22T11:00:00+00:00"))
            + "\n",
            encoding="utf-8",
        )
        with caplog.at_level("WARNING"):
            svc = SafetyNetEventsService(tmp_path / "projects")
            summary = svc.summarize()
        assert summary.total == 2
        assert "bad JSON" in caplog.text

    def test_non_dict_payload_is_skipped(self, tmp_path: Path) -> None:
        """``json.loads`` can return list / int / str — we only
        want dicts. Anything else is filtered silently."""
        events_path = tmp_path / "projects" / "project_0" / "trace" / "safety_net_events.jsonl"
        events_path.parent.mkdir(parents=True)
        events_path.write_text(
            json.dumps(_event(ts="2026-04-22T10:00:00+00:00")) + "\n" + "[1,2,3]\n" + '"a string"\n',
            encoding="utf-8",
        )
        svc = SafetyNetEventsService(tmp_path / "projects")
        assert svc.summarize().total == 1


class TestSerialization:
    def test_to_dict_shape_matches_frontend_contract(self, tmp_path: Path) -> None:
        """Pin the wire format the React consumer expects. Breaking
        this shape breaks the dashboard."""
        root = tmp_path / "projects"
        _seed_events(root, "project_0", [_event(ts="2026-04-22T10:00:00+00:00")])
        svc = SafetyNetEventsService(root)
        data = svc.summarize().to_dict()
        assert set(data.keys()) == {
            "total",
            "by_status",
            "by_layer",
            "top_step_ids",
            "top_repair_actions",
            "top_expected",
            "recent",
            "project_ids_seen",
        }
        # Top lists are arrays of {key, count} objects — not tuples,
        # since JSON can't represent tuples.
        assert all("key" in item and "count" in item for item in data["top_step_ids"])
        assert data["recent"][0]["project_id"] == "project_0"
