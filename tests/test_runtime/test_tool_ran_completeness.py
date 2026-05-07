"""Tests for tool_ran_completeness predicate + qa_report.schema.json
static_analysis / build_check additions.

Regression: project_4-ts-tower 2026-05-06 e2e probed several toolchain
binaries as 'present' (typechecker, build script) but qa_engineer only
ran the test runner. The new predicate fails when any tool probed as
present has no corresponding ran field.
"""

from __future__ import annotations

import json
from pathlib import Path

from aise.runtime.predicates import (
    PredicateContext,
    evaluate_predicate,
)
from aise.runtime.waterfall_v2_models import AcceptancePredicate


def _ctx(tmp_path: Path, **kwargs) -> PredicateContext:
    return PredicateContext(
        project_root=tmp_path,
        deliverable_path=tmp_path / "qa_report.json",
        **kwargs,
    )


def _pred(kind: str, arg=None) -> AcceptancePredicate:
    return AcceptancePredicate(kind=kind, arg=arg)


class TestCompletenessPasses:
    def test_only_one_tool_with_ran(self, tmp_path: Path):
        report = {
            "phase": "qa",
            "toolchain_check": {"pytest": "present"},
            "pytest": {"command": "pytest", "ran": True, "passed": 5, "failed": 0},
        }
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(_pred("tool_ran_completeness"), _ctx(tmp_path))
        assert r.passed, r.detail

    def test_static_analysis_block_satisfies(self, tmp_path: Path):
        report = {
            "phase": "qa",
            "toolchain_check": {
                "test_runner_x": "present",
                "typechecker_y": "present",
            },
            "test_runner_x": {"ran": True, "passed": 1},
            "static_analysis": {
                "typechecker_y": {"ran": True, "errors": 0},
            },
        }
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(_pred("tool_ran_completeness"), _ctx(tmp_path))
        assert r.passed, r.detail

    def test_build_check_satisfies_build_tool(self, tmp_path: Path):
        report = {
            "phase": "qa",
            "toolchain_check": {"npm": "present", "tsc": "present"},
            "build_check": {"command": "npm run build", "ran": True, "exit_code": 0},
        }
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(_pred("tool_ran_completeness"), _ctx(tmp_path))
        assert r.passed, r.detail

    def test_ran_false_with_reason_passes(self, tmp_path: Path):
        report = {
            "phase": "qa",
            "toolchain_check": {"vitest": "present"},
            "vitest": {"ran": False, "reason": "OOM during run"},
        }
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(_pred("tool_ran_completeness"), _ctx(tmp_path))
        assert r.passed, r.detail


class TestCompletenessFailures:
    def test_missing_ran_for_present_tool(self, tmp_path: Path):
        # Project_4 regression: tsc probed present, never ran.
        report = {
            "phase": "qa",
            "toolchain_check": {"vitest": "present", "tsc": "present"},
            "vitest": {"ran": True, "passed": 5},
            # tsc has neither top-level entry nor static_analysis entry
        }
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(_pred("tool_ran_completeness"), _ctx(tmp_path))
        assert not r.passed
        assert "tsc" in r.detail and "no ran=" in r.detail

    def test_ran_false_without_reason_fails(self, tmp_path: Path):
        report = {
            "phase": "qa",
            "toolchain_check": {"vitest": "present"},
            "vitest": {"ran": False},  # no reason field
        }
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(_pred("tool_ran_completeness"), _ctx(tmp_path))
        assert not r.passed and "no reason" in r.detail


class TestVacuousPass:
    def test_empty_toolchain_check_skipped(self, tmp_path: Path):
        report = {"phase": "qa", "toolchain_check": {}}
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(_pred("tool_ran_completeness"), _ctx(tmp_path))
        assert r.passed and r.skipped

    def test_only_missing_tools_skipped(self, tmp_path: Path):
        # Tools probed as missing aren't expected to have a ran record.
        report = {
            "phase": "qa",
            "toolchain_check": {"vitest": "missing"},
        }
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(_pred("tool_ran_completeness"), _ctx(tmp_path))
        assert r.passed
