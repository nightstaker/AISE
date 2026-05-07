"""Tests for unresolved_review_listed predicate + reviewer feedback
persistence.

Regression: project_4-ts-tower had 4/5 phases finish
'passed_with_unresolved_review' but no reviewer feedback was visible
in delivery_report.md. The new predicate cross-checks every persisted
REVISE/REJECT feedback against delivery_report content.
"""

from __future__ import annotations

import json
from pathlib import Path

from aise.runtime.predicates import (
    PredicateContext,
    evaluate_predicate,
)
from aise.runtime.reviewer import (
    ReviewerFeedback,
    parse_gap_list,
    persist_feedback,
)
from aise.runtime.waterfall_v2_models import AcceptancePredicate


def _ctx(tmp_path: Path) -> PredicateContext:
    return PredicateContext(
        project_root=tmp_path,
        deliverable_path=tmp_path / "docs" / "delivery_report.md",
    )


def _pred() -> AcceptancePredicate:
    return AcceptancePredicate(kind="unresolved_review_listed", arg=None)


def _seed_feedback(
    project_root: Path,
    *,
    phase_id: str,
    reviewer_role: str,
    iteration: int,
    verdict: str,
    gap_list: list[dict] | None = None,
    feedback_text: str = "",
) -> Path | None:
    fb = ReviewerFeedback(
        reviewer_role=reviewer_role,
        verdict=verdict,
        feedback_text=feedback_text,
        raw_response="",
        gap_list=tuple(gap_list or []),
    )
    return persist_feedback(project_root, phase_id, iteration, fb)


# -- Persistence helper itself -------------------------------------------


class TestPersist:
    def test_writes_json_file(self, tmp_path: Path):
        out = _seed_feedback(
            tmp_path,
            phase_id="architecture",
            reviewer_role="developer",
            iteration=1,
            verdict="REVISE",
            gap_list=[
                {
                    "severity": "blocker",
                    "location": {"file": "src/<x>", "line": 42},
                    "issue": "<issue>",
                    "fix_suggestion": "<fix>",
                }
            ],
        )
        assert out is not None
        assert out.is_file()
        data = json.loads(out.read_text())
        assert data["verdict"] == "REVISE"
        assert data["phase_id"] == "architecture"
        assert data["iteration"] == 1
        assert len(data["gap_list"]) == 1

    def test_unsafe_role_filename_sanitised(self, tmp_path: Path):
        out = _seed_feedback(
            tmp_path,
            phase_id="phase/.id",
            reviewer_role="role::weird",
            iteration=0,
            verdict="REJECT",
        )
        assert out is not None
        # Slashes and colons replaced with underscores
        assert "/" not in out.name and ":" not in out.name


# -- parse_gap_list -------------------------------------------------------


class TestParseGapList:
    def test_fenced_json(self):
        body = """Here is my review.

```json
{"summary": "issues", "gap_list": [
  {"severity": "blocker", "issue": "x"},
  {"severity": "minor",   "issue": "y"}
]}
```

Done."""
        gl = parse_gap_list(body)
        assert len(gl) == 2
        assert gl[0]["severity"] == "blocker"

    def test_inline_substring(self):
        body = 'note: "gap_list": [{"severity": "major", "issue": "z"}] tail'
        gl = parse_gap_list(body)
        assert len(gl) == 1
        assert gl[0]["severity"] == "major"

    def test_freeform_returns_empty(self):
        body = "I disagree with the design but cannot articulate why."
        assert parse_gap_list(body) == ()


# -- unresolved_review_listed predicate ----------------------------------


class TestPredicate:
    def test_no_feedback_dir_skipped(self, tmp_path: Path):
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "delivery_report.md").write_text("body", encoding="utf-8")
        r = evaluate_predicate(_pred(), _ctx(tmp_path))
        assert r.passed and r.skipped

    def test_no_unresolved_skipped(self, tmp_path: Path):
        # Only PASS feedback exists.
        _seed_feedback(
            tmp_path,
            phase_id="architecture",
            reviewer_role="developer",
            iteration=0,
            verdict="PASS",
        )
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "delivery_report.md").write_text("body", encoding="utf-8")
        r = evaluate_predicate(_pred(), _ctx(tmp_path))
        assert r.passed and r.skipped

    def test_unresolved_referenced_via_file(self, tmp_path: Path):
        _seed_feedback(
            tmp_path,
            phase_id="main_entry",
            reviewer_role="qa_engineer",
            iteration=2,
            verdict="REVISE",
            gap_list=[
                {
                    "severity": "blocker",
                    "location": {"file": "src/<consumer>", "line": 12},
                    "issue": "decorative reference only",
                }
            ],
        )
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "delivery_report.md").write_text(
            "## 已知 issue\n- src/<consumer>: decorative reference only\n",
            encoding="utf-8",
        )
        r = evaluate_predicate(_pred(), _ctx(tmp_path))
        assert r.passed, r.detail

    def test_unresolved_omitted_fails(self, tmp_path: Path):
        # Project_4 regression: REVISE feedback exists, delivery_report
        # claims everything's fine.
        _seed_feedback(
            tmp_path,
            phase_id="main_entry",
            reviewer_role="qa_engineer",
            iteration=2,
            verdict="REVISE",
            gap_list=[
                {
                    "severity": "blocker",
                    "location": {"file": "src/<consumer>"},
                    "issue": "missing reference",
                }
            ],
        )
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "delivery_report.md").write_text("## 已知 issue\n无重大问题\n", encoding="utf-8")
        r = evaluate_predicate(_pred(), _ctx(tmp_path))
        assert not r.passed
        assert "main_entry_qa_engineer" in r.detail or "missing reference" in r.detail.lower()

    def test_freeform_fallback_via_phase_role_signature(self, tmp_path: Path):
        # When the reviewer responded freeform (no gap_list), the
        # fallback signature is phase_id + reviewer_role.
        _seed_feedback(
            tmp_path,
            phase_id="implementation",
            reviewer_role="qa_engineer",
            iteration=1,
            verdict="REJECT",
            feedback_text="general dissatisfaction",
        )
        (tmp_path / "docs").mkdir()
        # Mention both phase_id and reviewer in the report.
        (tmp_path / "docs" / "delivery_report.md").write_text(
            "## 已知 issue\n- implementation phase qa_engineer feedback unresolved\n",
            encoding="utf-8",
        )
        r = evaluate_predicate(_pred(), _ctx(tmp_path))
        assert r.passed, r.detail
