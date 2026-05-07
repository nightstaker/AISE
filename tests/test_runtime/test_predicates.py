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
            "schema_optional",
            "language_supported",
            "min_scenarios",
            "contains_all_lifecycle_inits",
            "prior_phases_summarized",
            "mermaid_validates_via_skill",
            "language_idiomatic_check",
            "data_dependency_wiring_static",
            "action_contract_wiring_static",
            "lint_integration_test_imports",
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

    def test_schema_optional_passes_when_file_absent(self, tmp_path: Path):
        # Additive contracts (data_dependency_contract.json, action_contract.json)
        # use schema_optional so legacy projects that don't declare them
        # still pass the architecture phase AUTO_GATE.
        ctx = _ctx(tmp_path, "data_dependency_contract.json")
        r = evaluate_predicate(
            _pred("schema_optional", "schemas/data_dependency_contract.schema.json"),
            ctx,
        )
        assert r.passed and r.skipped

    def test_schema_optional_validates_when_file_present(self, tmp_path: Path):
        # When the file exists, schema_optional behaves identically to schema.
        good = {"data_dependencies": [{"name": "x", "files_glob": "a/*", "consumer_module": "src/loader.py"}]}
        (tmp_path / "data_dependency_contract.json").write_text(json.dumps(good), encoding="utf-8")
        r = evaluate_predicate(
            _pred("schema_optional", "schemas/data_dependency_contract.schema.json"),
            _ctx(tmp_path, "data_dependency_contract.json"),
        )
        assert r.passed, r.detail

    def test_schema_optional_rejects_invalid_when_present(self, tmp_path: Path):
        bad = {"data_dependencies": [{"name": "x"}]}  # missing required fields
        (tmp_path / "data_dependency_contract.json").write_text(json.dumps(bad), encoding="utf-8")
        r = evaluate_predicate(
            _pred("schema_optional", "schemas/data_dependency_contract.schema.json"),
            _ctx(tmp_path, "data_dependency_contract.json"),
        )
        assert not r.passed and "files_glob" in r.detail

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


# -- qa_report.schema.json (added 2026-05-05) ---------------------------


class TestQaReportSchema:
    """Validates docs/qa_report.json against the bundled schema. The
    schema was promoted from prose-only to AUTO_GATE-enforced after
    the 2026-05-05 phase-test matrix found qa_engineer skipping the
    report on toolchain-missing branches."""

    def test_minimal_valid_report_passes(self, tmp_path: Path):
        # Smallest legal qa_report — toolchain present, no UI, ran=true.
        report = {
            "phase": "qa",
            "completed_at": "2026-05-05T00:00:00Z",
            "toolchain_check": {"pytest": "present"},
            "pytest": {
                "command": "python -m pytest -q",
                "ran": True,
                "passed": 12,
                "failed": 0,
                "skipped": 0,
                "failed_tests": [],
            },
        }
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(
            _pred("schema", "schemas/qa_report.schema.json"),
            _ctx(tmp_path, "qa_report.json"),
        )
        assert r.passed, r.detail

    def test_runner_missing_branch_passes(self, tmp_path: Path):
        # The exact branch the prompt MUST cover but historically
        # didn't: toolchain missing → ran=false → counts omitted.
        # The schema accepts this without inventing pass/fail numbers.
        report = {
            "phase": "qa",
            "toolchain_check": {"vitest": "missing", "npx": "missing"},
            "pytest": {
                "command": "npx vitest run",
                "ran": False,
                "reason": "vitest not on PATH",
            },
        }
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(
            _pred("schema", "schemas/qa_report.schema.json"),
            _ctx(tmp_path, "qa_report.json"),
        )
        assert r.passed, r.detail

    def test_ui_validation_branch_passes(self, tmp_path: Path):
        # Flutter / pygame projects: ui_validation block populated.
        report = {
            "phase": "qa",
            "toolchain_check": {"flutter": "missing"},
            "pytest": {"command": "flutter test", "ran": False, "reason": "flutter missing"},
            "ui_validation": {
                "required": True,
                "verdict": "SKIPPED_HEADLESS_ONLY",
                "reason": "no display server",
                "pixel_smoke": {
                    "non_bg_samples": 0,
                    "threshold": 1000,
                    "frame_path": "artifacts/smoke_frame_0.png",
                    "verdict": "SKIPPED",
                },
            },
        }
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(
            _pred("schema", "schemas/qa_report.schema.json"),
            _ctx(tmp_path, "qa_report.json"),
        )
        assert r.passed, r.detail

    def test_missing_phase_field_fails(self, tmp_path: Path):
        # ``phase`` is required at the top level — schema must reject.
        report = {"toolchain_check": {"pytest": "present"}}
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(
            _pred("schema", "schemas/qa_report.schema.json"),
            _ctx(tmp_path, "qa_report.json"),
        )
        assert not r.passed
        assert "phase" in r.detail

    def test_missing_toolchain_check_fails(self, tmp_path: Path):
        # toolchain_check is required: phase 6 reads it to decide
        # whether reported pass/fail counts can be trusted.
        report = {"phase": "qa"}
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(
            _pred("schema", "schemas/qa_report.schema.json"),
            _ctx(tmp_path, "qa_report.json"),
        )
        assert not r.passed
        assert "toolchain_check" in r.detail

    def test_pytest_missing_ran_field_fails(self, tmp_path: Path):
        # When the ``pytest`` object is present, ``ran`` is required
        # so phase 6 can branch on it.
        report = {
            "phase": "qa",
            "toolchain_check": {"pytest": "present"},
            "pytest": {"command": "pytest"},
        }
        (tmp_path / "qa_report.json").write_text(json.dumps(report), encoding="utf-8")
        r = evaluate_predicate(
            _pred("schema", "schemas/qa_report.schema.json"),
            _ctx(tmp_path, "qa_report.json"),
        )
        assert not r.passed
        assert "ran" in r.detail


# -- language_supported ---------------------------------------------------


class TestLanguageSupported:
    def test_passes_with_cpp(self, tmp_path: Path):
        ctx = _ctx(tmp_path, "stack.json", stack_contract={"language": "cpp"})
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


# -- json_field_equals (phase-test catalog) -------------------------------


def _write_json(tmp_path: Path, name: str, data: dict | list) -> None:
    (tmp_path / name).write_text(json.dumps(data), encoding="utf-8")


class TestJsonFieldEquals:
    def test_passes_on_match(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"language": "python"})
        r = evaluate_predicate(
            _pred("json_field_equals", {"field": "language", "expected": "python"}),
            _ctx(tmp_path, "stack.json"),
        )
        assert r.passed and "python" in r.detail

    def test_fails_on_mismatch(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"language": "go"})
        r = evaluate_predicate(
            _pred("json_field_equals", {"field": "language", "expected": "python"}),
            _ctx(tmp_path, "stack.json"),
        )
        assert not r.passed and "'go'" in r.detail and "'python'" in r.detail

    def test_resolves_dotted_path(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"subsystems": [{"name": "core"}]})
        r = evaluate_predicate(
            _pred("json_field_equals", {"field": "subsystems.0.name", "expected": "core"}),
            _ctx(tmp_path, "stack.json"),
        )
        assert r.passed

    def test_null_expected_matches_python_none(self, tmp_path: Path):
        # Regression for the same Flutter-event_loop_owner issue PR #139
        # fixed in the schema: null must round-trip from YAML through JSON
        # and compare equal to Python None.
        _write_json(tmp_path, "stack.json", {"event_loop_owner": None})
        r = evaluate_predicate(
            _pred("json_field_equals", {"field": "event_loop_owner", "expected": None}),
            _ctx(tmp_path, "stack.json"),
        )
        assert r.passed

    def test_fails_on_unresolvable_field(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"language": "python"})
        r = evaluate_predicate(
            _pred("json_field_equals", {"field": "missing.field", "expected": "x"}),
            _ctx(tmp_path, "stack.json"),
        )
        assert not r.passed and "not resolvable" in r.detail

    def test_fails_on_invalid_arg(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {})
        r = evaluate_predicate(_pred("json_field_equals", "bad"), _ctx(tmp_path, "stack.json"))
        assert not r.passed and "invalid arg" in r.detail


# -- json_field_one_of ----------------------------------------------------


class TestJsonFieldOneOf:
    def test_passes_when_in_allowed(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"package_manager": "poetry"})
        r = evaluate_predicate(
            _pred(
                "json_field_one_of",
                {"field": "package_manager", "allowed": ["pip", "poetry", "uv"]},
            ),
            _ctx(tmp_path, "stack.json"),
        )
        assert r.passed

    def test_fails_when_not_in_allowed(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"package_manager": "npm"})
        r = evaluate_predicate(
            _pred(
                "json_field_one_of",
                {"field": "package_manager", "allowed": ["pip", "poetry"]},
            ),
            _ctx(tmp_path, "stack.json"),
        )
        assert not r.passed and "expected one of" in r.detail

    def test_fails_on_non_list_allowed(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"x": 1})
        r = evaluate_predicate(
            _pred("json_field_one_of", {"field": "x", "allowed": "not-a-list"}),
            _ctx(tmp_path, "stack.json"),
        )
        assert not r.passed


# -- contains_keywords ----------------------------------------------------


class TestContainsKeywords:
    def test_all_of_passes_case_insensitive(self, tmp_path: Path):
        (tmp_path / "arch.md").write_text("# Architecture\n\nWe use Python and pip with pytest.", encoding="utf-8")
        r = evaluate_predicate(
            _pred("contains_keywords", {"all_of": ["python", "PIP", "pytest"]}),
            _ctx(tmp_path, "arch.md"),
        )
        assert r.passed

    def test_all_of_reports_missing(self, tmp_path: Path):
        (tmp_path / "arch.md").write_text("just python", encoding="utf-8")
        r = evaluate_predicate(
            _pred("contains_keywords", {"all_of": ["python", "flutter"]}),
            _ctx(tmp_path, "arch.md"),
        )
        assert not r.passed and "flutter" in r.detail

    def test_any_of_passes_when_at_least_one(self, tmp_path: Path):
        (tmp_path / "arch.md").write_text("we picked Bloc", encoding="utf-8")
        r = evaluate_predicate(
            _pred("contains_keywords", {"any_of": ["Riverpod", "Bloc", "Provider"]}),
            _ctx(tmp_path, "arch.md"),
        )
        assert r.passed

    def test_any_of_fails_when_none(self, tmp_path: Path):
        (tmp_path / "arch.md").write_text("plain markdown", encoding="utf-8")
        r = evaluate_predicate(
            _pred("contains_keywords", {"any_of": ["Riverpod", "Bloc"]}),
            _ctx(tmp_path, "arch.md"),
        )
        assert not r.passed and "none of" in r.detail

    def test_case_sensitive_mode(self, tmp_path: Path):
        (tmp_path / "arch.md").write_text("Python is great", encoding="utf-8")
        r = evaluate_predicate(
            _pred(
                "contains_keywords",
                {"all_of": ["python"], "case_sensitive": True},  # lowercase, won't match
            ),
            _ctx(tmp_path, "arch.md"),
        )
        assert not r.passed


# -- forbidden_patterns ---------------------------------------------------


class TestForbiddenPatterns:
    def test_passes_when_clean(self, tmp_path: Path):
        (tmp_path / "arch.md").write_text("Python project under src/", encoding="utf-8")
        r = evaluate_predicate(
            _pred("forbidden_patterns", {"patterns": ["pubspec\\.yaml", "lib/main\\.dart"]}),
            _ctx(tmp_path, "arch.md"),
        )
        assert r.passed

    def test_fails_when_pattern_present(self, tmp_path: Path):
        (tmp_path / "arch.md").write_text("see pubspec.yaml", encoding="utf-8")
        r = evaluate_predicate(
            _pred("forbidden_patterns", {"patterns": ["pubspec\\.yaml"]}),
            _ctx(tmp_path, "arch.md"),
        )
        assert not r.passed and "pubspec" in r.detail

    def test_fails_when_any_pattern_matches(self, tmp_path: Path):
        # Two patterns; only second matches — still fails.
        (tmp_path / "arch.md").write_text("Flutter is here", encoding="utf-8")
        r = evaluate_predicate(
            _pred("forbidden_patterns", {"patterns": ["Cargo\\.toml", "Flutter"]}),
            _ctx(tmp_path, "arch.md"),
        )
        assert not r.passed and "Flutter" in r.detail


# -- count_at_least / count_at_most --------------------------------------


class TestCountAtLeast:
    def test_passes(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"subsystems": [1, 2, 3, 4]})
        r = evaluate_predicate(
            _pred("count_at_least", {"field": "subsystems", "min": 3}),
            _ctx(tmp_path, "stack.json"),
        )
        assert r.passed

    def test_fails_below_min(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"subsystems": [1]})
        r = evaluate_predicate(
            _pred("count_at_least", {"field": "subsystems", "min": 3}),
            _ctx(tmp_path, "stack.json"),
        )
        assert not r.passed and "1 < 3" in r.detail

    def test_fails_when_value_not_list(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"language": "python"})
        r = evaluate_predicate(
            _pred("count_at_least", {"field": "language", "min": 1}),
            _ctx(tmp_path, "stack.json"),
        )
        assert not r.passed and "expected list" in r.detail


class TestCountAtMost:
    def test_passes(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"subsystems": [1, 2]})
        r = evaluate_predicate(
            _pred("count_at_most", {"field": "subsystems", "max": 5}),
            _ctx(tmp_path, "stack.json"),
        )
        assert r.passed

    def test_fails_above_max(self, tmp_path: Path):
        _write_json(tmp_path, "stack.json", {"subsystems": list(range(15))})
        r = evaluate_predicate(
            _pred("count_at_most", {"field": "subsystems", "max": 10}),
            _ctx(tmp_path, "stack.json"),
        )
        assert not r.passed and "15 > 10" in r.detail
