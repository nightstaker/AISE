"""Tests for the acceptance predicate library (commit c2)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from aise.runtime.predicates import (
    DeliverableReport,
    PredicateContext,
    PredicateResult,
    evaluate_deliverable,
    evaluate_predicate,
    is_registered,
    register,
    registered_kinds,
)
from aise.runtime.waterfall_v2_models import AcceptancePredicate, Deliverable

# -- Registry -------------------------------------------------------------


class TestRegistry:
    def test_built_in_predicates_registered(self):
        for kind in [
            "file_exists",
            "min_bytes",
            "contains_sections",
            "regex_count",
            "schema",
            "language_supported",
            "min_scenarios",
            "contains_all_lifecycle_inits",
            "prior_phases_summarized",
            "mermaid_validates_via_skill",
            "language_idiomatic_check",
        ]:
            assert is_registered(kind), f"{kind} should be registered"

    def test_double_register_raises(self):
        # Registering a fresh kind should work; re-registering should raise.
        @register("__test_unique_kind_xyz")
        def _fn(arg, ctx):
            return PredicateResult("__test_unique_kind_xyz", True)

        with pytest.raises(ValueError, match="already registered"):

            @register("__test_unique_kind_xyz")
            def _fn2(arg, ctx):
                return PredicateResult("__test_unique_kind_xyz", True)

    def test_registered_kinds_sorted(self):
        ks = registered_kinds()
        assert ks == sorted(ks)


# -- Helpers --------------------------------------------------------------


def _ctx(tmp_path: Path, rel: str, **kwargs) -> PredicateContext:
    return PredicateContext(
        project_root=tmp_path,
        deliverable_path=tmp_path / rel,
        **kwargs,
    )


def _pred(kind: str, arg=None) -> AcceptancePredicate:
    return AcceptancePredicate(kind=kind, arg=arg)


# -- file_exists ----------------------------------------------------------


class TestFileExists:
    def test_passes_when_present(self, tmp_path: Path):
        (tmp_path / "x.md").write_text("hi", encoding="utf-8")
        ctx = _ctx(tmp_path, "x.md")
        r = evaluate_predicate(_pred("file_exists"), ctx)
        assert r.passed and "present" in r.detail

    def test_fails_when_missing(self, tmp_path: Path):
        ctx = _ctx(tmp_path, "missing.md")
        r = evaluate_predicate(_pred("file_exists"), ctx)
        assert not r.passed and "missing" in r.detail


# -- min_bytes ------------------------------------------------------------


class TestMinBytes:
    def test_passes(self, tmp_path: Path):
        (tmp_path / "a.md").write_text("x" * 100, encoding="utf-8")
        r = evaluate_predicate(_pred("min_bytes", 50), _ctx(tmp_path, "a.md"))
        assert r.passed

    def test_fails_when_too_small(self, tmp_path: Path):
        (tmp_path / "a.md").write_text("x" * 10, encoding="utf-8")
        r = evaluate_predicate(_pred("min_bytes", 50), _ctx(tmp_path, "a.md"))
        assert not r.passed and "10 < 50" in r.detail

    def test_fails_when_missing(self, tmp_path: Path):
        r = evaluate_predicate(_pred("min_bytes", 50), _ctx(tmp_path, "x.md"))
        assert not r.passed

    def test_invalid_arg(self, tmp_path: Path):
        (tmp_path / "x.md").write_text("hi", encoding="utf-8")
        r = evaluate_predicate(_pred("min_bytes", "bad"), _ctx(tmp_path, "x.md"))
        assert not r.passed and "invalid arg" in r.detail


# -- contains_sections ----------------------------------------------------


class TestContainsSections:
    def test_passes_with_h2_chinese_titles(self, tmp_path: Path):
        body = textwrap.dedent(
            """\
            # 项目
            ## 功能需求
            blah
            ## 非功能需求
            more
            ### 1. 用例
            content
            """
        )
        (tmp_path / "req.md").write_text(body, encoding="utf-8")
        r = evaluate_predicate(
            _pred("contains_sections", ["功能需求", "非功能需求", "用例"]),
            _ctx(tmp_path, "req.md"),
        )
        assert r.passed

    def test_reports_missing(self, tmp_path: Path):
        (tmp_path / "req.md").write_text("# 仅有功能需求\n## 功能需求\nfoo", encoding="utf-8")
        r = evaluate_predicate(
            _pred("contains_sections", ["功能需求", "非功能需求"]),
            _ctx(tmp_path, "req.md"),
        )
        assert not r.passed and "非功能需求" in r.detail


# -- regex_count ----------------------------------------------------------


class TestRegexCount:
    def test_counts_matches(self, tmp_path: Path):
        body = "FR-001\nFR-002\nFR-003\nNFR-100"
        (tmp_path / "req.md").write_text(body, encoding="utf-8")
        r = evaluate_predicate(
            _pred("regex_count", {"pattern": r"^FR-\d+", "min": 3}),
            _ctx(tmp_path, "req.md"),
        )
        assert r.passed

    def test_too_few(self, tmp_path: Path):
        (tmp_path / "req.md").write_text("FR-001\n", encoding="utf-8")
        r = evaluate_predicate(
            _pred("regex_count", {"pattern": r"^FR-\d+", "min": 3}),
            _ctx(tmp_path, "req.md"),
        )
        assert not r.passed and "1 < 3" in r.detail


# -- schema ---------------------------------------------------------------


class TestSchemaPredicate:
    """Validates against schemas/*.schema.json bundled with aise."""

    def test_valid_stack_contract(self, tmp_path: Path):
        valid = {
            "language": "python",
            "framework_backend": "fastapi",
            "package_manager": "pip",
            "test_runner": "pytest",
            "entry_point": "src/main.py",
            "run_command": "python -m src.main",
            "subsystems": [
                {
                    "name": "core",
                    "src_dir": "src/core",
                    "components": [{"name": "router", "file": "src/core/router.py"}],
                }
            ],
        }
        (tmp_path / "stack_contract.json").write_text(json.dumps(valid), encoding="utf-8")
        ctx = _ctx(tmp_path, "stack_contract.json")
        r = evaluate_predicate(_pred("schema", "schemas/stack_contract.schema.json"), ctx)
        assert r.passed, r.detail

    def test_invalid_stack_contract_reports_errors(self, tmp_path: Path):
        invalid = {"language": "python"}  # missing 6 required fields
        (tmp_path / "stack_contract.json").write_text(json.dumps(invalid), encoding="utf-8")
        ctx = _ctx(tmp_path, "stack_contract.json")
        r = evaluate_predicate(_pred("schema", "schemas/stack_contract.schema.json"), ctx)
        assert not r.passed
        assert "missing required" in r.detail

    def test_bad_json_reports(self, tmp_path: Path):
        (tmp_path / "x.json").write_text("not json", encoding="utf-8")
        r = evaluate_predicate(
            _pred("schema", "schemas/stack_contract.schema.json"),
            _ctx(tmp_path, "x.json"),
        )
        assert not r.passed and "invalid JSON" in r.detail

    def test_event_loop_owner_null_is_valid(self, tmp_path: Path):
        # Flutter / Bottle-style entry points hand the loop to an external
        # library (`runApp(app)`, `app.run()`), so architect.md tells the
        # producer to set event_loop_owner=null. Schema must accept it —
        # the magic_tower 2026-05-04 e2e halted at architecture because
        # this branch was missing from the schema even though architect.md
        # and safety_net/stack_contract.py both treat null as valid.
        contract = {
            "language": "dart",
            "framework_backend": "",
            "framework_frontend": "flutter",
            "package_manager": "pub",
            "test_runner": "flutter test",
            "entry_point": "lib/main.dart",
            "run_command": "flutter run",
            "subsystems": [
                {
                    "name": "ui",
                    "src_dir": "lib/ui",
                    "components": [{"name": "main_menu", "file": "lib/ui/main_menu.dart"}],
                }
            ],
            "event_loop_owner": None,
        }
        (tmp_path / "stack_contract.json").write_text(json.dumps(contract), encoding="utf-8")
        r = evaluate_predicate(
            _pred("schema", "schemas/stack_contract.schema.json"),
            _ctx(tmp_path, "stack_contract.json"),
        )
        assert r.passed, r.detail

    def test_event_loop_owner_object_still_valid(self, tmp_path: Path):
        # Pygame / Qt-with-custom-loop projects fill in a real lifecycle_init
        # object — the existing branch must keep working after we widen the
        # schema to accept null.
        contract = {
            "language": "python",
            "framework_backend": "pygame",
            "package_manager": "pip",
            "test_runner": "pytest",
            "entry_point": "src/main.py",
            "run_command": "python -m src.main",
            "subsystems": [
                {
                    "name": "core",
                    "src_dir": "src/core",
                    "components": [{"name": "game", "file": "src/core/game.py"}],
                }
            ],
            "event_loop_owner": {
                "attr": "dispatcher",
                "method": "initialize",
                "class": "EventDispatcher",
                "module": "src/core/game.py",
            },
        }
        (tmp_path / "stack_contract.json").write_text(json.dumps(contract), encoding="utf-8")
        r = evaluate_predicate(
            _pred("schema", "schemas/stack_contract.schema.json"),
            _ctx(tmp_path, "stack_contract.json"),
        )
        assert r.passed, r.detail


# -- language_supported ---------------------------------------------------


class TestLanguageSupported:
    def test_passes_with_csharp(self, tmp_path: Path):
        ctx = _ctx(tmp_path, "stack.json", stack_contract={"language": "csharp"})
        r = evaluate_predicate(_pred("language_supported"), ctx)
        assert r.passed

    def test_fails_with_empty(self, tmp_path: Path):
        ctx = _ctx(tmp_path, "stack.json", stack_contract={"language": ""})
        r = evaluate_predicate(_pred("language_supported"), ctx)
        assert not r.passed

    def test_fails_with_no_contract(self, tmp_path: Path):
        ctx = _ctx(tmp_path, "stack.json")
        r = evaluate_predicate(_pred("language_supported"), ctx)
        assert not r.passed


# -- min_scenarios --------------------------------------------------------


class TestMinScenarios:
    def test_passes_with_loaded_contract(self, tmp_path: Path):
        ctx = _ctx(
            tmp_path,
            "behavioral.json",
            behavioral_contract={"scenarios": [{"id": f"s{i}"} for i in range(8)]},
        )
        r = evaluate_predicate(_pred("min_scenarios", 5), ctx)
        assert r.passed

    def test_falls_back_to_file_when_not_loaded(self, tmp_path: Path):
        (tmp_path / "behavioral.json").write_text(
            json.dumps({"scenarios": [{"id": "a"}, {"id": "b"}]}), encoding="utf-8"
        )
        ctx = _ctx(tmp_path, "behavioral.json")
        r = evaluate_predicate(_pred("min_scenarios", 5), ctx)
        assert not r.passed and "2 < 5" in r.detail


# -- contains_all_lifecycle_inits -----------------------------------------


class TestLifecycleInits:
    def test_passes_when_every_init_invoked(self, tmp_path: Path):
        body = textwrap.dedent(
            """\
            class Main:
                def __init__(self):
                    self.screenManager = ScreenManager()
                    self.playerManager = PlayerManager()
                def Start(self):
                    self.screenManager.Initialize();
                    self.playerManager .  Initialize ()
            """
        )
        (tmp_path / "Main.cs").write_text(body, encoding="utf-8")
        ctx = _ctx(
            tmp_path,
            "Main.cs",
            stack_contract={
                "lifecycle_inits": [
                    {"attr": "screenManager", "method": "Initialize", "class": "ScreenManager", "module": "X"},
                    {"attr": "playerManager", "method": "Initialize", "class": "PlayerManager", "module": "Y"},
                ]
            },
        )
        r = evaluate_predicate(_pred("contains_all_lifecycle_inits"), ctx)
        assert r.passed

    def test_reports_missing_invocations(self, tmp_path: Path):
        (tmp_path / "Main.cs").write_text("class Main {}", encoding="utf-8")
        ctx = _ctx(
            tmp_path,
            "Main.cs",
            stack_contract={
                "lifecycle_inits": [
                    {"attr": "scrMgr", "method": "Init", "class": "X", "module": "Y"},
                ]
            },
        )
        r = evaluate_predicate(_pred("contains_all_lifecycle_inits"), ctx)
        assert not r.passed and "scrMgr.Init" in r.detail

    def test_vacuous_pass_when_no_inits(self, tmp_path: Path):
        (tmp_path / "Main.cs").write_text("class Main {}", encoding="utf-8")
        ctx = _ctx(tmp_path, "Main.cs", stack_contract={"lifecycle_inits": []})
        r = evaluate_predicate(_pred("contains_all_lifecycle_inits"), ctx)
        assert r.passed and r.skipped


# -- prior_phases_summarized ----------------------------------------------


class TestPriorPhasesSummarized:
    def test_passes_when_all_canonicals_mentioned(self, tmp_path: Path):
        body = """
        # Delivery Report
        Built per docs/requirement.md and docs/architecture.md.
        Stack contract: docs/stack_contract.json.
        Behavior: docs/behavioral_contract.json.
        """
        (tmp_path / "delivery_report.md").write_text(body, encoding="utf-8")
        r = evaluate_predicate(_pred("prior_phases_summarized", 5), _ctx(tmp_path, "delivery_report.md"))
        assert r.passed

    def test_fails_when_too_few(self, tmp_path: Path):
        (tmp_path / "delivery_report.md").write_text("Only mentions docs/requirement.md", encoding="utf-8")
        r = evaluate_predicate(_pred("prior_phases_summarized", 5), _ctx(tmp_path, "delivery_report.md"))
        assert not r.passed


# -- mermaid_validates_via_skill ------------------------------------------


class TestMermaidValidator:
    def test_skipped_when_no_blocks(self, tmp_path: Path):
        (tmp_path / "doc.md").write_text("# no diagrams here", encoding="utf-8")
        r = evaluate_predicate(_pred("mermaid_validates_via_skill"), _ctx(tmp_path, "doc.md"))
        assert r.passed and r.skipped

    def test_passes_with_known_headers(self, tmp_path: Path):
        body = textwrap.dedent(
            """\
            # title
            ```mermaid
            flowchart LR
              A --> B
            ```
            ```mermaid
            sequenceDiagram
              A->>B: hi
            ```
            ```mermaid
            C4Context
              Person(user, "User")
            ```
            """
        )
        (tmp_path / "doc.md").write_text(body, encoding="utf-8")
        r = evaluate_predicate(_pred("mermaid_validates_via_skill"), _ctx(tmp_path, "doc.md"))
        assert r.passed and not r.skipped

    def test_fails_with_unknown_header(self, tmp_path: Path):
        body = "```mermaid\nflowflowchart LR\n  A --> B\n```"
        (tmp_path / "doc.md").write_text(body, encoding="utf-8")
        r = evaluate_predicate(_pred("mermaid_validates_via_skill"), _ctx(tmp_path, "doc.md"))
        assert not r.passed and "[1]" in r.detail


# -- language_idiomatic_check ---------------------------------------------


class TestLanguageIdiomatic:
    def test_skipped_when_no_contract(self, tmp_path: Path):
        (tmp_path / "x.py").write_text("print(1)", encoding="utf-8")
        r = evaluate_predicate(_pred("language_idiomatic_check"), _ctx(tmp_path, "x.py"))
        assert r.passed and r.skipped

    def test_skipped_when_analyzer_missing(self, tmp_path: Path):
        (tmp_path / "x.py").write_text("print(1)", encoding="utf-8")
        ctx = _ctx(
            tmp_path,
            "x.py",
            stack_contract={"static_analyzer": "definitely-not-a-real-binary-xyz"},
        )
        r = evaluate_predicate(_pred("language_idiomatic_check"), ctx)
        assert r.passed and r.skipped


# -- Unknown predicate ----------------------------------------------------


class TestUnknownPredicate:
    def test_reports_unknown_kind(self, tmp_path: Path):
        r = evaluate_predicate(_pred("totally_unknown"), _ctx(tmp_path, "x"))
        assert not r.passed and "unknown predicate kind" in r.detail


# -- Deliverable-level evaluation -----------------------------------------


class TestEvaluateDeliverable:
    def test_aggregates_predicates(self, tmp_path: Path):
        (tmp_path / "x.md").write_text("hello world" * 50, encoding="utf-8")
        d = Deliverable(
            kind="document",
            path="x.md",
            acceptance=(
                AcceptancePredicate("file_exists"),
                AcceptancePredicate("min_bytes", 100),
            ),
        )
        ctx = _ctx(tmp_path, "x.md")
        report = evaluate_deliverable(d, ctx)
        assert isinstance(report, DeliverableReport)
        assert report.passed
        assert len(report.predicate_results) == 2

    def test_failed_returns_only_failures(self, tmp_path: Path):
        d = Deliverable(
            kind="document",
            path="missing.md",
            acceptance=(
                AcceptancePredicate("file_exists"),
                AcceptancePredicate("min_bytes", 100),
            ),
        )
        report = evaluate_deliverable(d, _ctx(tmp_path, "missing.md"))
        assert not report.passed
        assert len(report.failed) == 2
        assert "FAIL: " in report.summary()

    def test_skipped_predicates_dont_block_pass(self, tmp_path: Path):
        (tmp_path / "x.md").write_text("hi", encoding="utf-8")
        d = Deliverable(
            kind="document",
            path="x.md",
            acceptance=(
                AcceptancePredicate("file_exists"),
                AcceptancePredicate("mermaid_validates_via_skill"),  # skipped (no blocks)
            ),
        )
        report = evaluate_deliverable(d, _ctx(tmp_path, "x.md"))
        assert report.passed
