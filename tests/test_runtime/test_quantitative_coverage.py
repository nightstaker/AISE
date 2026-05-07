"""Tests for quantitative_coverage predicate + requirement_contract schema's
quantitative_constraints / standard_formulas additions.

Regression: project_4-ts-tower 2026-05-06 e2e shipped 5 instead of the
required 50 of an artifact because the architect silently shrunk a
quantified constraint. The new predicate evaluates each
verifiable_via expression and rejects when the actual value violates
the operator/value rule.
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
        deliverable_path=tmp_path / "docs" / "requirement_contract.json",
        **kwargs,
    )


def _pred(kind: str, arg=None) -> AcceptancePredicate:
    return AcceptancePredicate(kind=kind, arg=arg)


# -- Schema: quantitative_constraints + standard_formulas ----------------


class TestSchemaQuantitative:
    def test_valid_quantitative_constraint(self, tmp_path: Path):
        contract = {
            "functional_requirements": [{"id": "FR-001", "title": "x", "description": "y"}],
            "non_functional_requirements": [],
            "quantitative_constraints": [
                {
                    "id": "FR-001.q1",
                    "owns_requirement": "FR-001",
                    "operator": "min_count",
                    "target": "playable_units",
                    "value": 50,
                    "unit": "unit",
                    "verifiable_via": "count(assets/data_*.json)",
                }
            ],
        }
        (tmp_path / "rc.json").write_text(json.dumps(contract), encoding="utf-8")
        ctx = PredicateContext(
            project_root=tmp_path,
            deliverable_path=tmp_path / "rc.json",
        )
        r = evaluate_predicate(
            _pred("schema", "schemas/requirement_contract.schema.json"),
            ctx,
        )
        assert r.passed, r.detail

    def test_invalid_operator_rejected(self, tmp_path: Path):
        contract = {
            "functional_requirements": [{"id": "FR-001", "title": "x", "description": "y"}],
            "non_functional_requirements": [],
            "quantitative_constraints": [
                {
                    "id": "FR-001.q1",
                    "owns_requirement": "FR-001",
                    "operator": "way_more_than",  # not in enum
                    "target": "things",
                    "value": 1,
                }
            ],
        }
        (tmp_path / "rc.json").write_text(json.dumps(contract), encoding="utf-8")
        ctx = PredicateContext(
            project_root=tmp_path,
            deliverable_path=tmp_path / "rc.json",
        )
        r = evaluate_predicate(
            _pred("schema", "schemas/requirement_contract.schema.json"),
            ctx,
        )
        assert not r.passed and "way_more_than" in r.detail

    def test_standard_formula_requires_two_examples(self, tmp_path: Path):
        contract = {
            "functional_requirements": [{"id": "FR-001", "title": "x", "description": "y"}],
            "non_functional_requirements": [],
            "standard_formulas": [
                {
                    "name": "demo",
                    "formula": "y = max(0, x)",
                    "examples": [
                        {"inputs": {"x": 5}, "expected_output": 5},
                    ],
                }
            ],
        }
        (tmp_path / "rc.json").write_text(json.dumps(contract), encoding="utf-8")
        ctx = PredicateContext(
            project_root=tmp_path,
            deliverable_path=tmp_path / "rc.json",
        )
        r = evaluate_predicate(
            _pred("schema", "schemas/requirement_contract.schema.json"),
            ctx,
        )
        assert not r.passed and "minItems" in r.detail


# -- quantitative_coverage predicate -------------------------------------


class TestPasses:
    def test_count_glob_satisfied(self, tmp_path: Path):
        # Constraint says 'at least 5 files'; we ship 6 — pass.
        (tmp_path / "assets" / "data").mkdir(parents=True)
        for i in range(1, 7):
            (tmp_path / "assets" / "data" / f"row_{i}.json").write_text("{}", encoding="utf-8")
        contract = {
            "quantitative_constraints": [
                {
                    "id": "FR-001.q1",
                    "owns_requirement": "FR-001",
                    "operator": "min_count",
                    "target": "data_rows",
                    "value": 5,
                    "verifiable_via": "count(assets/data/row_*.json)",
                }
            ]
        }
        ctx = _ctx(tmp_path, requirement_contract=contract)
        r = evaluate_predicate(_pred("quantitative_coverage"), ctx)
        assert r.passed, r.detail

    def test_len_dotted_path_satisfied(self, tmp_path: Path):
        contract = {
            "quantitative_constraints": [
                {
                    "id": "FR-001.q1",
                    "owns_requirement": "FR-001",
                    "operator": "min_count",
                    "target": "subsystems",
                    "value": 3,
                    "verifiable_via": "len(stack_contract.subsystems)",
                }
            ]
        }
        stack = {"subsystems": [{"name": f"s{i}"} for i in range(4)]}
        ctx = _ctx(tmp_path, requirement_contract=contract, stack_contract=stack)
        r = evaluate_predicate(_pred("quantitative_coverage"), ctx)
        assert r.passed


class TestFailures:
    def test_regression_underdelivered_count(self, tmp_path: Path):
        # Project_4 regression: requirement says 50, actual 5.
        (tmp_path / "assets" / "data").mkdir(parents=True)
        for i in range(1, 6):
            (tmp_path / "assets" / "data" / f"row_{i}.json").write_text("{}", encoding="utf-8")
        contract = {
            "quantitative_constraints": [
                {
                    "id": "FR-001.q1",
                    "owns_requirement": "FR-001",
                    "operator": "min_count",
                    "target": "playable_units",
                    "value": 50,
                    "verifiable_via": "count(assets/data/row_*.json)",
                }
            ]
        }
        ctx = _ctx(tmp_path, requirement_contract=contract)
        r = evaluate_predicate(_pred("quantitative_coverage"), ctx)
        assert not r.passed
        assert "FR-001.q1" in r.detail
        assert "5" in r.detail and "50" in r.detail

    def test_unresolvable_expression_violates(self, tmp_path: Path):
        contract = {
            "quantitative_constraints": [
                {
                    "id": "FR-001.q1",
                    "owns_requirement": "FR-001",
                    "operator": "min_count",
                    "target": "things",
                    "value": 1,
                    "verifiable_via": "len(stack_contract.bogus)",
                }
            ]
        }
        ctx = _ctx(tmp_path, requirement_contract=contract, stack_contract={})
        r = evaluate_predicate(_pred("quantitative_coverage"), ctx)
        assert not r.passed and "FR-001.q1" in r.detail

    def test_max_count_exceeded(self, tmp_path: Path):
        contract = {
            "quantitative_constraints": [
                {
                    "id": "NFR-002.q1",
                    "owns_requirement": "NFR-002",
                    "operator": "max_count",
                    "target": "dirs",
                    "value": 2,
                    "verifiable_via": "len(stack_contract.subsystems)",
                }
            ]
        }
        stack = {"subsystems": [{"name": f"s{i}"} for i in range(7)]}
        ctx = _ctx(tmp_path, requirement_contract=contract, stack_contract=stack)
        r = evaluate_predicate(_pred("quantitative_coverage"), ctx)
        assert not r.passed
        assert "max_count" in r.detail


class TestVacuousPass:
    def test_no_contract_skipped(self, tmp_path: Path):
        ctx = _ctx(tmp_path)
        r = evaluate_predicate(_pred("quantitative_coverage"), ctx)
        assert r.passed and r.skipped

    def test_empty_constraints_skipped(self, tmp_path: Path):
        ctx = _ctx(tmp_path, requirement_contract={"quantitative_constraints": []})
        r = evaluate_predicate(_pred("quantitative_coverage"), ctx)
        assert r.passed and r.skipped
