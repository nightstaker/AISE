"""Tests for ``action_contract_wiring_static`` predicate and the
action_contract.schema.json validation.

Regression: princess_tower TS run had ``input.onAttack(() => { ...
gameRef._currentScreen = 'battle'; })`` — never called
``combat.calculateBattle()``. Action contract should declare
``handler_must_call: ["combat.calculateBattle"]`` and the gate
must catch the missing call site.
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
        deliverable_path=tmp_path / "src" / "main.ts",  # entry_point file as the deliverable
        **kwargs,
    )


def _pred(kind: str, arg=None) -> AcceptancePredicate:
    return AcceptancePredicate(kind=kind, arg=arg)


# -- Schema --------------------------------------------------------------


class TestSchema:
    def test_valid_minimal(self, tmp_path: Path):
        contract = {
            "actions": [
                {
                    "name": "primary_attack",
                    "trigger": {"kind": "key", "value": "Space"},
                    "expected_change": {
                        "kind": "state_field_changes",
                        "field": "currentScreen",
                    },
                    "handler_must_call": ["combat.calculateBattle"],
                }
            ]
        }
        (tmp_path / "action_contract.json").write_text(json.dumps(contract), encoding="utf-8")
        ctx = PredicateContext(
            project_root=tmp_path,
            deliverable_path=tmp_path / "action_contract.json",
        )
        r = evaluate_predicate(_pred("schema", "schemas/action_contract.schema.json"), ctx)
        assert r.passed, r.detail

    def test_invalid_trigger_kind(self, tmp_path: Path):
        contract = {
            "actions": [
                {
                    "name": "x",
                    "trigger": {"kind": "telepathy"},
                    "expected_change": {"kind": "state_field_changes"},
                }
            ]
        }
        (tmp_path / "action_contract.json").write_text(json.dumps(contract), encoding="utf-8")
        ctx = PredicateContext(
            project_root=tmp_path,
            deliverable_path=tmp_path / "action_contract.json",
        )
        r = evaluate_predicate(_pred("schema", "schemas/action_contract.schema.json"), ctx)
        assert not r.passed and "telepathy" in r.detail


# -- action_contract_wiring_static -- pass cases ------------------------


class TestPassCases:
    def test_handler_calls_all_required(self, tmp_path: Path):
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text(
            """
            input.onAttack(() => {
              const result = combat.calculateBattle(player, monster);
              player.applyBattleResult(result);
            });
            """,
            encoding="utf-8",
        )
        contract = {
            "actions": [
                {
                    "name": "primary_attack",
                    "trigger": {"kind": "key", "value": "Space"},
                    "expected_change": {"kind": "state_field_changes", "field": "currentScreen"},
                    "handler_must_call": [
                        "combat.calculateBattle",
                        "player.applyBattleResult",
                    ],
                }
            ]
        }
        ctx = _ctx(
            tmp_path,
            action_contract=contract,
            stack_contract={"entry_point": "src/main.ts"},
        )
        r = evaluate_predicate(_pred("action_contract_wiring_static"), ctx)
        assert r.passed, r.detail

    def test_dotted_symbol_matches_method_call(self, tmp_path: Path):
        # Even when the symbol is written 'a.b.c', we accept a call to
        # the bare last token 'c(' too.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text("function go() { calculateBattle(p, m); }\n", encoding="utf-8")
        contract = {
            "actions": [
                {
                    "name": "x",
                    "trigger": {"kind": "key", "value": "Space"},
                    "expected_change": {"kind": "any_observable_change"},
                    "handler_must_call": ["combat.calculateBattle"],
                }
            ]
        }
        ctx = _ctx(
            tmp_path,
            action_contract=contract,
            stack_contract={"entry_point": "src/main.ts"},
        )
        r = evaluate_predicate(_pred("action_contract_wiring_static"), ctx)
        assert r.passed, r.detail


# -- action_contract_wiring_static -- fail cases ------------------------


class TestFailCases:
    def test_regression_handler_calls_zero_required(self, tmp_path: Path):
        # Princess_tower regression: handler only changes state field,
        # never calls combat.calculateBattle.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text(
            """
            input.onAttack(() => {
              if (this._currentScreen === 'playing') {
                this._currentScreen = 'battle';   // wired to nothing
              }
            });
            """,
            encoding="utf-8",
        )
        contract = {
            "actions": [
                {
                    "name": "primary_attack",
                    "trigger": {"kind": "key", "value": "Space"},
                    "expected_change": {"kind": "state_field_changes"},
                    "handler_must_call": [
                        "combat.calculateBattle",
                        "player.applyBattleResult",
                    ],
                }
            ]
        }
        ctx = _ctx(
            tmp_path,
            action_contract=contract,
            stack_contract={"entry_point": "src/main.ts"},
        )
        r = evaluate_predicate(_pred("action_contract_wiring_static"), ctx)
        assert not r.passed
        assert "primary_attack" in r.detail
        assert "missing call sites" in r.detail
        # Both missing symbols must be named in the failure detail.
        assert "combat.calculateBattle" in r.detail
        assert "player.applyBattleResult" in r.detail

    def test_handler_module_override(self, tmp_path: Path):
        # When action.handler_module is set, the gate uses it instead of
        # stack_contract.entry_point.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text("// nothing\n", encoding="utf-8")
        (tmp_path / "src" / "controllers").mkdir()
        (tmp_path / "src" / "controllers" / "input.ts").write_text(
            "function onAttack() { combat.calculateBattle(p, m); }\n",
            encoding="utf-8",
        )
        contract = {
            "actions": [
                {
                    "name": "primary_attack",
                    "trigger": {"kind": "key", "value": "Space"},
                    "expected_change": {"kind": "state_field_changes"},
                    "handler_module": "src/controllers/input.ts",
                    "handler_must_call": ["combat.calculateBattle"],
                }
            ]
        }
        ctx = _ctx(
            tmp_path,
            action_contract=contract,
            stack_contract={"entry_point": "src/main.ts"},
        )
        r = evaluate_predicate(_pred("action_contract_wiring_static"), ctx)
        assert r.passed, r.detail

    def test_handler_module_missing_file_fails(self, tmp_path: Path):
        contract = {
            "actions": [
                {
                    "name": "x",
                    "trigger": {"kind": "key"},
                    "expected_change": {"kind": "any_observable_change"},
                    "handler_module": "src/missing.ts",
                    "handler_must_call": ["foo"],
                }
            ]
        }
        ctx = _ctx(
            tmp_path,
            action_contract=contract,
            stack_contract={"entry_point": "src/main.ts"},
        )
        r = evaluate_predicate(_pred("action_contract_wiring_static"), ctx)
        assert not r.passed and "does not exist" in r.detail


# -- action_contract_wiring_static -- vacuous pass ----------------------


class TestVacuousPass:
    def test_no_contract_loaded_skipped(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        r = evaluate_predicate(_pred("action_contract_wiring_static"), ctx)
        assert r.passed and r.skipped

    def test_actions_without_handler_must_call_skipped(self, tmp_path: Path):
        contract = {
            "actions": [
                {
                    "name": "x",
                    "trigger": {"kind": "key"},
                    "expected_change": {"kind": "any_observable_change"},
                }
            ]
        }
        ctx = _ctx(
            tmp_path,
            action_contract=contract,
            stack_contract={"entry_point": "src/main.ts"},
        )
        r = evaluate_predicate(_pred("action_contract_wiring_static"), ctx)
        # No graded actions → skipped.
        assert r.passed and r.skipped
