"""Tests for the contains_all_lifecycle_inits predicate's dispatch-loop
recognition (PR #145 follow-up surfaced by project_7 e2e on 2026-05-07).

The original predicate enforced literal ``attr.method(`` call sites.
``developer.md`` officially recommends the dispatch-loop pattern
(iterate the contract's lifecycle_inits[] and call each method
dynamically), but that pattern doesn't emit literal call sites — so
the predicate falsely rejected correct code.

The updated predicate accepts EITHER:
  1. literal call site ``attr.method(`` (legacy), OR
  2. dispatch loop indicators present + attr appears as a quoted
     string literal somewhere in the file.
"""

from __future__ import annotations

from pathlib import Path

from aise.runtime.predicates import (
    PredicateContext,
    evaluate_predicate,
)
from aise.runtime.waterfall_v2_models import AcceptancePredicate


def _ctx(tmp_path: Path, **kwargs) -> PredicateContext:
    return PredicateContext(
        project_root=tmp_path,
        deliverable_path=tmp_path / "src" / "main.ts",
        **kwargs,
    )


def _pred() -> AcceptancePredicate:
    return AcceptancePredicate(kind="contains_all_lifecycle_inits", arg=None)


_INITS = [
    {
        "attr": "heroStats",
        "method": "initialize",
        "class": "HeroStats",
        "module": "src/core/hero_stats.ts",
    },
    {
        "attr": "combatEngine",
        "method": "initialize",
        "class": "CombatEngine",
        "module": "src/core/combat_engine.ts",
    },
]


# -- Branch 1: literal call sites (legacy behaviour) ---------------------


class TestLiteralCallSites:
    def test_pass_when_each_attr_method_called(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text(
            "this.heroStats.initialize();\nthis.combatEngine.initialize();\n",
            encoding="utf-8",
        )
        ctx = _ctx(tmp_path, stack_contract={"lifecycle_inits": _INITS})
        r = evaluate_predicate(_pred(), ctx)
        assert r.passed, r.detail

    def test_fail_when_one_call_missing_and_no_loop(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text(
            "this.heroStats.initialize();\n// combatEngine missing\n",
            encoding="utf-8",
        )
        ctx = _ctx(tmp_path, stack_contract={"lifecycle_inits": _INITS})
        r = evaluate_predicate(_pred(), ctx)
        assert not r.passed and "combatEngine.initialize" in r.detail


# -- Branch 2: dispatch loop pattern (project_7 regression) --------------


class TestDispatchLoop:
    def test_pass_via_for_of_loop(self, tmp_path: Path):
        # The exact shape developer wrote in project_7 main_entry — a
        # for-of loop over lifecycleInits[] dispatching dynamically.
        body = """
        private readonly lifecycleInits = [
          { attr: 'heroStats',    method: 'initialize' },
          { attr: 'combatEngine', method: 'initialize' },
        ];
        initializeAll(): void {
          for (const entry of this.lifecycleInits) {
            const target = (this as Record<string, unknown>)[entry.attr];
            const method = (target as Record<string, unknown>)[entry.method];
            method.call(target);
          }
        }
        """
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text(body, encoding="utf-8")
        ctx = _ctx(tmp_path, stack_contract={"lifecycle_inits": _INITS})
        r = evaluate_predicate(_pred(), ctx)
        assert r.passed, r.detail
        assert "via dispatch loop" in r.detail

    def test_pass_via_python_getattr_loop(self, tmp_path: Path):
        # Cross-language: developer.md's Python example. Same principle.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text(
            "lifecycle_inits = [{'attr': 'heroStats', 'method': 'initialize'},"
            " {'attr': 'combatEngine', 'method': 'initialize'}]\n"
            "for entry in lifecycle_inits:\n"
            "    target = getattr(self, entry['attr'])\n"
            "    getattr(target, entry['method'])()\n",
            encoding="utf-8",
        )
        ctx = _ctx(tmp_path, stack_contract={"lifecycle_inits": _INITS})
        r = evaluate_predicate(_pred(), ctx)
        assert r.passed, r.detail

    def test_fail_when_dispatch_loop_present_but_attr_missing_string(self, tmp_path: Path):
        # Loop indicators present, but combatEngine attr never appears
        # in the file as a string literal — gate must still fail.
        body = """
        private readonly lifecycleInits = [
          { attr: 'heroStats', method: 'initialize' },
        ];
        for (const entry of this.lifecycleInits) {
          target[entry.attr][entry.method]();
        }
        """
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text(body, encoding="utf-8")
        ctx = _ctx(tmp_path, stack_contract={"lifecycle_inits": _INITS})
        r = evaluate_predicate(_pred(), ctx)
        assert not r.passed and "combatEngine.initialize" in r.detail

    def test_pass_when_loop_plus_literal_calls(self, tmp_path: Path):
        # Defensive: developer might list both — should still pass.
        body = """
        private readonly lifecycleInits = [
          { attr: 'heroStats', method: 'initialize' },
          { attr: 'combatEngine', method: 'initialize' },
        ];
        for (const entry of this.lifecycleInits) {
          target[entry.attr][entry.method]();
        }
        // Belt & braces:
        this.heroStats.initialize();
        this.combatEngine.initialize();
        """
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text(body, encoding="utf-8")
        ctx = _ctx(tmp_path, stack_contract={"lifecycle_inits": _INITS})
        r = evaluate_predicate(_pred(), ctx)
        assert r.passed, r.detail
