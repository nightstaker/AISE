"""Tests for the consume_call upgrade to data_dependency_wiring_static.

Regression: project_4-ts-tower 2026-05-06 e2e shipped 5+ consumer
modules each with an inert path constant (e.g.
``const FILES = ["a", "b"]; void FILES;``) that satisfied the legacy
substring check but had no actual runtime consumption. The new
contract field ``consume_call`` upgrades the gate to require the path
to appear at a call-site context.

These tests assert the upgraded gate is language-agnostic — the call-site
heuristic checks for ``(``/``,``/quote/import-keyword markers that
appear in most mainstream stacks.
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
        deliverable_path=tmp_path / "docs" / "data_dependency_contract.json",
        **kwargs,
    )


def _pred() -> AcceptancePredicate:
    return AcceptancePredicate(kind="data_dependency_wiring_static", arg=None)


# Helpers


def _make_consumer(tmp_path: Path, rel: str, body: str) -> None:
    p = tmp_path / rel.lstrip("/")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")


def _make_data(tmp_path: Path, rel: str) -> None:
    p = tmp_path / rel.lstrip("/")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("{}", encoding="utf-8")


# ----------------------------------------------------------------------


class TestPasses:
    def test_call_argument(self, tmp_path: Path):
        # Path passed as a call argument — passes call-site check.
        _make_data(tmp_path, "data/items.json")
        _make_consumer(
            tmp_path,
            "src/loader",
            'fn boot() { read_text("data/items.json"); }\n',
        )
        contract = {
            "data_dependencies": [
                {
                    "name": "items",
                    "files_glob": "data/items.json",
                    "consumer_module": "src/loader",
                    "consume_call": "runtime_io_read",
                }
            ]
        }
        ctx = _ctx(tmp_path, data_dependency_contract=contract)
        r = evaluate_predicate(_pred(), ctx)
        assert r.passed, r.detail

    def test_import_statement(self, tmp_path: Path):
        # Bundler-style import counts as a call-site equivalent.
        _make_data(tmp_path, "config/settings.json")
        _make_consumer(
            tmp_path,
            "src/cfg",
            'import config from "config/settings.json";\n',
        )
        contract = {
            "data_dependencies": [
                {
                    "name": "cfg",
                    "files_glob": "config/settings.json",
                    "consumer_module": "src/cfg",
                    "consume_call": "bundler_static_import",
                }
            ]
        }
        ctx = _ctx(tmp_path, data_dependency_contract=contract)
        r = evaluate_predicate(_pred(), ctx)
        assert r.passed, r.detail

    def test_template_literal_inside_call(self, tmp_path: Path):
        # Path appears in a template literal that is itself a call arg.
        _make_data(tmp_path, "data/level_1.json")
        _make_consumer(
            tmp_path,
            "src/level",
            "fn load(i) { fetch(`data/level_${i}.json`); }\n",
        )
        contract = {
            "data_dependencies": [
                {
                    "name": "lvl",
                    "files_glob": "data/level_*.json",
                    "consumer_module": "src/level",
                    "consume_call": "runtime_io_read",
                }
            ]
        }
        ctx = _ctx(tmp_path, data_dependency_contract=contract)
        r = evaluate_predicate(_pred(), ctx)
        assert r.passed, r.detail

    def test_embedded_resource_bypasses_call_check(self, tmp_path: Path):
        # consume_call=embedded_resource — bypass: the file is bundled
        # via a build manifest outside the consumer source.
        _make_data(tmp_path, "assets/sprite.png")
        _make_consumer(tmp_path, "src/assets", "// nothing here\n")
        contract = {
            "data_dependencies": [
                {
                    "name": "sprite",
                    "files_glob": "assets/sprite.png",
                    "consumer_module": "src/assets",
                    "consume_call": "embedded_resource",
                }
            ]
        }
        ctx = _ctx(tmp_path, data_dependency_contract=contract)
        r = evaluate_predicate(_pred(), ctx)
        assert r.passed, r.detail


class TestFails:
    def test_decorative_const_rejected_when_consume_call_set(self, tmp_path: Path):
        # The exact regression: path in a top-level constant, value
        # never used anywhere — gate-gaming pattern.
        _make_data(tmp_path, "data/items.json")
        _make_consumer(
            tmp_path,
            "src/loader",
            'const FILES = ["data/items.json"];\n_ = FILES;\n',
        )
        contract = {
            "data_dependencies": [
                {
                    "name": "items",
                    "files_glob": "data/items.json",
                    "consumer_module": "src/loader",
                    "consume_call": "runtime_io_read",
                }
            ]
        }
        ctx = _ctx(tmp_path, data_dependency_contract=contract)
        r = evaluate_predicate(_pred(), ctx)
        assert not r.passed
        assert "bare declaration" in r.detail or "items" in r.detail

    def test_decorative_const_passes_legacy_when_no_consume_call(self, tmp_path: Path):
        # When consume_call is omitted, the legacy substring check
        # still passes for backward compatibility.
        _make_data(tmp_path, "data/items.json")
        _make_consumer(
            tmp_path,
            "src/loader",
            'const FILES = ["data/items.json"];\n',
        )
        contract = {
            "data_dependencies": [
                {
                    "name": "items",
                    "files_glob": "data/items.json",
                    "consumer_module": "src/loader",
                }
            ]
        }
        ctx = _ctx(tmp_path, data_dependency_contract=contract)
        r = evaluate_predicate(_pred(), ctx)
        assert r.passed, r.detail
