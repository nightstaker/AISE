"""Tests for ``data_dependency_wiring_static`` predicate and the
data_dependency_contract.schema.json validation.

These cover the regression case from the princess_tower TS run on
2026-05-06: ``assets/floor_*.json`` was declared by the architect but
no source file under ``src/`` referenced it — the gate must catch
this.
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
        deliverable_path=tmp_path / "docs" / "data_dependency_contract.json",
        **kwargs,
    )


def _pred(kind: str, arg=None) -> AcceptancePredicate:
    return AcceptancePredicate(kind=kind, arg=arg)


# -- Schema ---------------------------------------------------------------


class TestSchema:
    def test_valid_minimal(self, tmp_path: Path):
        contract = {
            "version": "1",
            "data_dependencies": [
                {
                    "name": "level_data",
                    "files_glob": "assets/level_*.json",
                    "consumer_module": "src/level/loader.py",
                }
            ],
        }
        (tmp_path / "data_dependency_contract.json").write_text(json.dumps(contract), encoding="utf-8")
        ctx = PredicateContext(
            project_root=tmp_path,
            deliverable_path=tmp_path / "data_dependency_contract.json",
        )
        r = evaluate_predicate(_pred("schema", "schemas/data_dependency_contract.schema.json"), ctx)
        assert r.passed, r.detail

    def test_missing_required_consumer_module(self, tmp_path: Path):
        contract = {"data_dependencies": [{"name": "x", "files_glob": "a/*"}]}  # no consumer_module
        (tmp_path / "data_dependency_contract.json").write_text(json.dumps(contract), encoding="utf-8")
        ctx = PredicateContext(
            project_root=tmp_path,
            deliverable_path=tmp_path / "data_dependency_contract.json",
        )
        r = evaluate_predicate(_pred("schema", "schemas/data_dependency_contract.schema.json"), ctx)
        assert not r.passed and "consumer_module" in r.detail

    def test_optional_skipped_when_absent(self, tmp_path: Path):
        # When the file isn't present, ``schema_optional`` vacuous-passes.
        ctx = PredicateContext(
            project_root=tmp_path,
            deliverable_path=tmp_path / "data_dependency_contract.json",
        )
        r = evaluate_predicate(
            _pred("schema_optional", "schemas/data_dependency_contract.schema.json"),
            ctx,
        )
        assert r.passed and r.skipped


# -- data_dependency_wiring_static ---------------------------------------


class TestWiringStaticPasses:
    def test_consumer_references_glob_prefix(self, tmp_path: Path):
        # Source file references the glob prefix (typical: dynamic loader
        # builds path with f-string template like 'assets/level_<i>.json').
        (tmp_path / "src" / "level").mkdir(parents=True)
        (tmp_path / "src" / "level" / "loader.py").write_text(
            "def load(i): return open(f'assets/level_{i:02d}.json')\n",
            encoding="utf-8",
        )
        # Concrete files exist on disk too.
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "level_01.json").write_text("{}", encoding="utf-8")
        (tmp_path / "assets" / "level_02.json").write_text("{}", encoding="utf-8")

        contract = {
            "data_dependencies": [
                {
                    "name": "level_data",
                    "files_glob": "assets/level_*.json",
                    "consumer_module": "src/level/loader.py",
                }
            ]
        }
        ctx = _ctx(tmp_path, data_dependency_contract=contract)
        r = evaluate_predicate(_pred("data_dependency_wiring_static"), ctx)
        assert r.passed, r.detail

    def test_concrete_filename_match(self, tmp_path: Path):
        # Source hard-codes a single concrete file path.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "i18n.py").write_text(
            "STRINGS = json.load(open('assets/i18n.json'))\n",
            encoding="utf-8",
        )
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "i18n.json").write_text("{}", encoding="utf-8")

        contract = {
            "data_dependencies": [
                {
                    "name": "i18n",
                    "files_glob": "assets/i18n.json",
                    "consumer_module": "src/i18n.py",
                }
            ]
        }
        ctx = _ctx(tmp_path, data_dependency_contract=contract)
        r = evaluate_predicate(_pred("data_dependency_wiring_static"), ctx)
        assert r.passed, r.detail


class TestWiringStaticFails:
    def test_zero_references_flagged(self, tmp_path: Path):
        # Regression for princess_tower TS: floor_*.json on disk, but
        # no source file references it.
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "main.ts").write_text(
            "import 'phaser';\nclass Game { boot() {} }\nnew Game().boot();\n",
            encoding="utf-8",
        )
        (tmp_path / "assets").mkdir()
        for i in range(1, 11):
            (tmp_path / "assets" / f"floor_{i:02d}.json").write_text("{}", encoding="utf-8")

        contract = {
            "data_dependencies": [
                {
                    "name": "floor_data",
                    "files_glob": "assets/floor_*.json",
                    "consumer_module": "src/main.ts",
                    "min_files": 10,
                }
            ]
        }
        ctx = _ctx(tmp_path, data_dependency_contract=contract)
        r = evaluate_predicate(_pred("data_dependency_wiring_static"), ctx)
        assert not r.passed
        assert "floor_data" in r.detail
        assert "no reference" in r.detail

    def test_missing_consumer_module(self, tmp_path: Path):
        contract = {
            "data_dependencies": [
                {
                    "name": "x",
                    "files_glob": "data/*.json",
                    "consumer_module": "src/loader.py",
                }
            ]
        }
        ctx = _ctx(tmp_path, data_dependency_contract=contract)
        r = evaluate_predicate(_pred("data_dependency_wiring_static"), ctx)
        assert not r.passed and "matched no files" in r.detail


class TestWiringStaticVacuousPass:
    def test_no_contract_loaded_skipped(self, tmp_path: Path):
        ctx = _ctx(tmp_path)  # no data_dependency_contract
        r = evaluate_predicate(_pred("data_dependency_wiring_static"), ctx)
        assert r.passed and r.skipped

    def test_empty_array_skipped(self, tmp_path: Path):
        ctx = _ctx(tmp_path, data_dependency_contract={"data_dependencies": []})
        r = evaluate_predicate(_pred("data_dependency_wiring_static"), ctx)
        assert r.passed and r.skipped

    def test_glob_consumer_matches_multiple(self, tmp_path: Path):
        # Consumer glob matches several files; only one needs to contain
        # the reference for the gate to pass.
        (tmp_path / "src" / "level").mkdir(parents=True)
        (tmp_path / "src" / "level" / "loader_a.py").write_text("# nothing here\n", encoding="utf-8")
        (tmp_path / "src" / "level" / "loader_b.py").write_text("open('assets/level_01.json')\n", encoding="utf-8")
        (tmp_path / "assets").mkdir()
        (tmp_path / "assets" / "level_01.json").write_text("{}", encoding="utf-8")

        contract = {
            "data_dependencies": [
                {
                    "name": "level_data",
                    "files_glob": "assets/level_*.json",
                    "consumer_module": "src/level/loader_*.py",
                }
            ]
        }
        ctx = _ctx(tmp_path, data_dependency_contract=contract)
        r = evaluate_predicate(_pred("data_dependency_wiring_static"), ctx)
        assert r.passed, r.detail
