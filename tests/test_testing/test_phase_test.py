"""Tests for ``aise.testing.phase_test`` — the single-phase contract
test runner.

The actual phase execution requires a real LLM and is therefore not
exercised in CI. We do exercise:

* the case YAML loader (happy path + every error branch)
* the version gate (mismatch raises hard)
* the assertion-evaluation half (synthetic produced files in tmpdir,
  walked through ``_evaluate_assertions``)
* the runner top-level wiring with ``_run_single_phase`` monkey-patched
  to a fake that just writes canned files (validates the input copy,
  the post-run assertion eval, and the report assembly without LLM)
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from aise import __version__ as INSTALLED_AISE_VERSION
from aise.runtime.waterfall_v2_models import AcceptancePredicate
from aise.testing import phase_test as pt

# -- Helpers -------------------------------------------------------------


def _minimal_case_yaml(
    tmp_path: Path,
    *,
    aise_version: str = INSTALLED_AISE_VERSION,
    extra_assertions: list[dict] | None = None,
    project_config: dict | None = None,
) -> Path:
    """Materialize a minimal valid case + input + project_config under
    ``tmp_path`` and return the case.yaml path."""
    case_dir = tmp_path / "case_root"
    case_dir.mkdir()
    (case_dir / "input").mkdir()
    (case_dir / "input" / "docs").mkdir()
    (case_dir / "input" / "docs" / "requirement.md").write_text("# requirement\nhello", encoding="utf-8")

    cfg = project_config or {
        "project_name": "test",
        "development_mode": "local",
        "process_type": "waterfall_v2",
        "default_model": {
            "provider": "Local",
            "model": "test-model",
            "api_key": "",
            "base_url": "http://127.0.0.1:9999/v1",
            "temperature": 0.0,
            "max_tokens": 1024,
        },
        "agents": {
            "architect": {"name": "architect", "enabled": True},
            "code_reviewer": {"name": "code_reviewer", "enabled": True},
        },
    }
    (case_dir / "project_config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")

    case = {
        "aise_version": aise_version,
        "scenario_id": "minimal",
        "phase": "architecture",
        "input_dir": "input/",
        "project_config_file": "project_config.json",
        "requirement": "minimal hello",
        "max_review_iterations": 1,
        "assertions": [
            {
                "name": "arch_md_present",
                "path": "docs/architecture.md",
                "predicate": "file_exists",
            }
        ]
        + (extra_assertions or []),
    }
    case_yaml = case_dir / "case.yaml"
    case_yaml.write_text(yaml.safe_dump(case, sort_keys=False), encoding="utf-8")
    return case_yaml


# -- load_case ------------------------------------------------------------


class TestLoadCase:
    def test_minimal_happy_path(self, tmp_path: Path):
        case_path = _minimal_case_yaml(tmp_path)
        case = pt.load_case(case_path)
        assert case.aise_version == INSTALLED_AISE_VERSION
        assert case.scenario_id == "minimal"
        assert case.phase == "architecture"
        assert case.input_dir == (case_path.parent / "input").resolve()
        assert case.requirement == "minimal hello"
        assert case.max_review_iterations == 1
        assert len(case.assertions) == 1
        assert case.assertions[0].name == "arch_md_present"
        assert case.assertions[0].predicate.kind == "file_exists"
        assert case.case_file == case_path.resolve()

    def test_inline_predicate_with_arg(self, tmp_path: Path):
        case_path = _minimal_case_yaml(
            tmp_path,
            extra_assertions=[
                {
                    "name": "arch_size",
                    "path": "docs/architecture.md",
                    "predicate": {"min_bytes": 1500},
                },
            ],
        )
        case = pt.load_case(case_path)
        # second assertion is the one we added
        assert case.assertions[1].predicate.kind == "min_bytes"
        assert case.assertions[1].predicate.arg == 1500

    def test_severity_warn_recorded(self, tmp_path: Path):
        case_path = _minimal_case_yaml(
            tmp_path,
            extra_assertions=[
                {
                    "name": "soft",
                    "path": "docs/architecture.md",
                    "predicate": "file_exists",
                    "severity": "warn",
                },
            ],
        )
        case = pt.load_case(case_path)
        assert case.assertions[1].severity == "warn"

    def test_requirement_file_resolves_relative_to_case(self, tmp_path: Path):
        case_dir = tmp_path / "case_root"
        case_dir.mkdir()
        (case_dir / "input").mkdir()
        (case_dir / "input" / "docs").mkdir()
        (case_dir / "input" / "docs" / "requirement.md").write_text("x", encoding="utf-8")
        (case_dir / "project_config.json").write_text("{}", encoding="utf-8")
        (case_dir / "req.txt").write_text("from-file requirement", encoding="utf-8")
        case = {
            "aise_version": INSTALLED_AISE_VERSION,
            "scenario_id": "x",
            "phase": "architecture",
            "input_dir": "input/",
            "project_config_file": "project_config.json",
            "requirement_file": "req.txt",
            "assertions": [{"name": "n", "path": "docs/x.md", "predicate": "file_exists"}],
        }
        cy = case_dir / "case.yaml"
        cy.write_text(yaml.safe_dump(case), encoding="utf-8")
        loaded = pt.load_case(cy)
        assert loaded.requirement == "from-file requirement"

    def test_missing_aise_version_errors(self, tmp_path: Path):
        case_path = _minimal_case_yaml(tmp_path)
        # Strip the field
        raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        raw.pop("aise_version")
        case_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ValueError, match="aise_version"):
            pt.load_case(case_path)

    def test_missing_assertions_errors(self, tmp_path: Path):
        case_path = _minimal_case_yaml(tmp_path)
        raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        raw["assertions"] = []
        case_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ValueError, match="assertions"):
            pt.load_case(case_path)

    def test_invalid_predicate_shape_errors(self, tmp_path: Path):
        case_path = _minimal_case_yaml(tmp_path)
        raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        # Two-key dict is illegal — predicate must be a single-key map.
        raw["assertions"][0]["predicate"] = {"min_bytes": 1500, "schema": "x"}
        case_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ValueError, match="single-key"):
            pt.load_case(case_path)

    def test_invalid_severity_errors(self, tmp_path: Path):
        case_path = _minimal_case_yaml(tmp_path)
        raw = yaml.safe_load(case_path.read_text(encoding="utf-8"))
        raw["assertions"][0]["severity"] = "fatal"
        case_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        with pytest.raises(ValueError, match="severity"):
            pt.load_case(case_path)


# -- check_version --------------------------------------------------------


class TestCheckVersion:
    def test_match_passes_silently(self, tmp_path: Path):
        case_path = _minimal_case_yaml(tmp_path)
        case = pt.load_case(case_path)
        pt.check_version(case)  # no raise

    def test_mismatch_raises_hard(self, tmp_path: Path):
        case_path = _minimal_case_yaml(tmp_path, aise_version="9.99.99")
        case = pt.load_case(case_path)
        with pytest.raises(pt.PhaseTestVersionMismatch, match="9.99.99"):
            pt.check_version(case)


# -- _evaluate_assertions ------------------------------------------------


class TestEvaluateAssertions:
    def test_walks_every_assertion(self, tmp_path: Path):
        # Pretend the phase produced two artifacts.
        (tmp_path / "docs").mkdir()
        (tmp_path / "docs" / "architecture.md").write_text("# Arch\n" + "x" * 200, encoding="utf-8")
        (tmp_path / "docs" / "stack_contract.json").write_text(json.dumps({"language": "python"}), encoding="utf-8")
        assertions = (
            pt.AssertionSpec(
                name="present",
                path="docs/architecture.md",
                predicate=AcceptancePredicate("file_exists"),
            ),
            pt.AssertionSpec(
                name="lang",
                path="docs/stack_contract.json",
                predicate=AcceptancePredicate(
                    "json_field_equals",
                    {"field": "language", "expected": "python"},
                ),
            ),
        )
        results = pt._evaluate_assertions(tmp_path, assertions, contracts={})
        assert len(results) == 2
        assert all(r.predicate_result.passed for r in results)

    def test_failing_assertion_recorded(self, tmp_path: Path):
        # No file → file_exists fails.
        assertions = (
            pt.AssertionSpec(
                name="present",
                path="docs/missing.md",
                predicate=AcceptancePredicate("file_exists"),
            ),
        )
        (results,) = pt._evaluate_assertions(tmp_path, assertions, contracts={})
        assert not results.predicate_result.passed
        assert not results.gate_passed  # default severity=error

    def test_warn_severity_does_not_gate(self, tmp_path: Path):
        spec = pt.AssertionSpec(
            name="soft",
            path="docs/missing.md",
            predicate=AcceptancePredicate("file_exists"),
            severity="warn",
        )
        (r,) = pt._evaluate_assertions(tmp_path, (spec,), contracts={})
        assert not r.predicate_result.passed
        assert r.gate_passed  # warn never gates


# -- run_phase_test (with _run_single_phase monkey-patched) ---------------


def _fake_phase_run(
    *,
    written_files: dict[str, str] | None = None,
    status: str = "passed",
    failure_summary: str = "",
):
    """Build a stub for ``_run_single_phase`` that writes canned files
    into ``proj`` and returns a synthetic ``(status, summary, contracts)``
    tuple. Lets us test run_phase_test's plumbing without a real LLM."""

    def _stub(proj, case, on_event):
        for rel, body in (written_files or {}).items():
            target = proj / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body, encoding="utf-8")
        # contracts dict mirrors what _default_contracts_loader would
        # return after the phase wrote its outputs.
        contracts: dict[str, Any] = {
            "stack_contract": None,
            "behavioral_contract": None,
            "requirement_contract": None,
        }
        sc = proj / "docs" / "stack_contract.json"
        if sc.is_file():
            contracts["stack_contract"] = json.loads(sc.read_text(encoding="utf-8"))
        return status, failure_summary, contracts

    return _stub


class TestRunPhaseTestPipeline:
    def test_passing_run_reports_pass(self, tmp_path, monkeypatch):
        case_path = _minimal_case_yaml(
            tmp_path,
            extra_assertions=[
                {
                    "name": "lang_python",
                    "path": "docs/stack_contract.json",
                    "predicate": {"json_field_equals": {"field": "language", "expected": "python"}},
                }
            ],
        )
        case = pt.load_case(case_path)

        # Stub the phase runner to write the expected files.
        monkeypatch.setattr(
            pt,
            "_run_single_phase",
            _fake_phase_run(
                written_files={
                    "docs/architecture.md": "# Architecture\n" + "x" * 100,
                    "docs/stack_contract.json": json.dumps({"language": "python"}),
                }
            ),
        )

        report = pt.run_phase_test(case)
        assert report.passed
        assert report.phase_status == "passed"
        assert len(report.assertion_results) == 2
        assert all(r.gate_passed for r in report.assertion_results)
        assert "PASS" in report.summary()

    def test_failing_assertion_marks_case_failed(self, tmp_path, monkeypatch):
        # Add an assertion the stub will fail.
        case_path = _minimal_case_yaml(
            tmp_path,
            extra_assertions=[
                {
                    "name": "wrong_language",
                    "path": "docs/stack_contract.json",
                    "predicate": {"json_field_equals": {"field": "language", "expected": "rust"}},
                }
            ],
        )
        case = pt.load_case(case_path)

        monkeypatch.setattr(
            pt,
            "_run_single_phase",
            _fake_phase_run(
                written_files={
                    "docs/architecture.md": "# Architecture\n",
                    "docs/stack_contract.json": json.dumps({"language": "python"}),
                }
            ),
        )

        report = pt.run_phase_test(case)
        assert not report.passed
        assert len(report.failed_assertions) == 1
        assert report.failed_assertions[0].spec.name == "wrong_language"
        assert "FAIL" in report.summary()

    def test_phase_halt_marks_case_failed_regardless_of_assertions(self, tmp_path, monkeypatch):
        case_path = _minimal_case_yaml(tmp_path)
        case = pt.load_case(case_path)

        # Even though we write the file (so file_exists passes), the
        # phase reports FAILED — the report must reflect that.
        monkeypatch.setattr(
            pt,
            "_run_single_phase",
            _fake_phase_run(
                written_files={"docs/architecture.md": "x" * 100},
                status="failed",
                failure_summary="AUTO_GATE failed",
            ),
        )
        report = pt.run_phase_test(case)
        assert not report.passed
        assert report.phase_status == "failed"
        assert "AUTO_GATE failed" in report.phase_failure_summary

    def test_keep_workdir_returns_path(self, tmp_path, monkeypatch):
        case_path = _minimal_case_yaml(tmp_path)
        case = pt.load_case(case_path)
        monkeypatch.setattr(
            pt,
            "_run_single_phase",
            _fake_phase_run(written_files={"docs/architecture.md": "x" * 100}),
        )
        report = pt.run_phase_test(case, keep_workdir=True)
        assert report.project_root is not None
        assert report.project_root.is_dir()
        # Snapshot from input/ must have been copied in.
        assert (report.project_root / "docs" / "requirement.md").is_file()
        # Cleanup ourselves so we don't leak into other tests.
        import shutil

        shutil.rmtree(report.project_root, ignore_errors=True)

    def test_version_mismatch_short_circuits(self, tmp_path, monkeypatch):
        case_path = _minimal_case_yaml(tmp_path, aise_version="0.0.0-stale")
        case = pt.load_case(case_path)

        called = {"phase_run": False}

        def _should_not_run(*args, **kw):
            called["phase_run"] = True
            return ("passed", "", {})

        monkeypatch.setattr(pt, "_run_single_phase", _should_not_run)
        with pytest.raises(pt.PhaseTestVersionMismatch):
            pt.run_phase_test(case)
        assert not called["phase_run"], "phase must not run when version mismatches"

    def test_missing_input_dir_raises(self, tmp_path, monkeypatch):
        case_path = _minimal_case_yaml(tmp_path)
        case = pt.load_case(case_path)
        # Wipe the input dir referenced by the loaded case.
        import shutil

        shutil.rmtree(case.input_dir)
        monkeypatch.setattr(pt, "_run_single_phase", _fake_phase_run(written_files={}))
        with pytest.raises(FileNotFoundError, match="input_dir does not exist"):
            pt.run_phase_test(case)


# -- Bundled fixture sanity ----------------------------------------------


class TestBundledFixture:
    """Make sure the python_cli_hello_world × architecture fixture
    parses with the current loader. This is a guard against silent
    drift when someone edits case.yaml or the loader."""

    FIXTURE = Path(__file__).resolve().parents[1] / (
        "fixtures/v2_phase_io/python_cli_hello_world/architecture/case.yaml"
    )

    def test_fixture_loads(self):
        if not self.FIXTURE.is_file():
            pytest.skip(f"bundled fixture missing: {self.FIXTURE}")
        case = pt.load_case(self.FIXTURE)
        assert case.scenario_id == "python_cli_hello_world"
        assert case.phase == "architecture"
        assert case.aise_version == INSTALLED_AISE_VERSION, (
            "fixture aise_version drifted from package version; bump or re-record the snapshot"
        )
        # Sanity: every assertion's predicate kind must be registered.
        from aise.runtime.predicates import is_registered

        for spec in case.assertions:
            assert is_registered(spec.predicate.kind), (
                f"assertion {spec.name!r} uses unregistered predicate kind {spec.predicate.kind!r}"
            )
