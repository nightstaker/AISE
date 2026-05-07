"""Tests for the lint-only ``lint_integration_test_imports`` predicate.

Predicate is intentionally non-blocking — always returns gate_passed
(skipped=True) regardless of whether suspect files were found. The
detail string carries the warning so AUTO_GATE logs surface it.
"""

from __future__ import annotations

from pathlib import Path

from aise.runtime.predicates import (
    PredicateContext,
    evaluate_predicate,
)
from aise.runtime.waterfall_v2_models import AcceptancePredicate


def _ctx(tmp_path: Path) -> PredicateContext:
    return PredicateContext(
        project_root=tmp_path,
        deliverable_path=tmp_path / "docs" / "qa_report.json",
    )


def _pred(arg) -> AcceptancePredicate:
    return AcceptancePredicate(kind="lint_integration_test_imports", arg=arg)


class TestLintIntegrationTestImports:
    def test_clean_when_tests_reference_source(self, tmp_path: Path):
        (tmp_path / "tests" / "integration").mkdir(parents=True)
        (tmp_path / "tests" / "integration" / "happy.ts").write_text(
            "import { x } from '../../src/core';\nx();\n", encoding="utf-8"
        )
        (tmp_path / "src").mkdir()
        r = evaluate_predicate(
            _pred({"globs": ["tests/integration/**"], "source_globs": ["src/"]}),
            _ctx(tmp_path),
        )
        assert r.gate_passed and r.skipped
        assert "0 contain no reference" in r.detail

    def test_warn_surfaces_suspect_file(self, tmp_path: Path):
        # Princess_tower regression: tests/integration/mainline.test.ts
        # has zero src/ refs.
        (tmp_path / "tests" / "integration").mkdir(parents=True)
        (tmp_path / "tests" / "integration" / "mainline.test.ts").write_text(
            "let x = 1;\nexpect(x).toBe(1);\n", encoding="utf-8"
        )
        (tmp_path / "src").mkdir()
        r = evaluate_predicate(
            _pred({"globs": ["tests/integration/**"], "source_globs": ["src/"]}),
            _ctx(tmp_path),
        )
        # Always gate-passed — lint, not a hard gate.
        assert r.gate_passed and r.skipped
        # But detail must surface the suspect filename.
        assert "mainline.test.ts" in r.detail
        assert "1 contain no reference" in r.detail

    def test_skipped_when_no_test_files(self, tmp_path: Path):
        r = evaluate_predicate(
            _pred({"globs": ["tests/integration/**"], "source_globs": ["src/"]}),
            _ctx(tmp_path),
        )
        assert r.gate_passed and r.skipped
        assert "no integration test files" in r.detail

    def test_invalid_arg_silently_passes(self, tmp_path: Path):
        # Lint must never block a phase — even on misconfiguration.
        r = evaluate_predicate(_pred("not-a-dict"), _ctx(tmp_path))
        assert r.gate_passed and r.skipped

    def test_lib_directory_detected(self, tmp_path: Path):
        # Flutter / dart layouts use lib/ — the lint accepts a list of
        # source-prefix globs.
        (tmp_path / "tests" / "scenarios").mkdir(parents=True)
        (tmp_path / "tests" / "scenarios" / "boot.dart").write_text("import '../../lib/main.dart';\n", encoding="utf-8")
        (tmp_path / "lib").mkdir()
        r = evaluate_predicate(
            _pred(
                {
                    "globs": ["tests/scenarios/**"],
                    "source_globs": ["src/", "lib/"],
                }
            ),
            _ctx(tmp_path),
        )
        assert r.gate_passed and r.skipped
        assert "0 contain no reference" in r.detail
