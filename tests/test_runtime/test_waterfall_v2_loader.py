"""Tests for waterfall_v2_loader + json_schema_lite (commit c1)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from aise.runtime.json_schema_lite import validate
from aise.runtime.waterfall_v2_loader import (
    ProcessSpecError,
    default_waterfall_v2_path,
    load_waterfall_v2,
)
from aise.runtime.waterfall_v2_models import WaterfallV2Spec

# -- json_schema_lite -----------------------------------------------------


class TestJsonSchemaLite:
    def test_required_field_missing(self):
        schema = {"type": "object", "required": ["name"]}
        errors = validate({}, schema)
        assert any("missing required property 'name'" in e for e in errors)

    def test_type_check(self):
        schema = {"type": "string"}
        assert validate("ok", schema) == []
        errs = validate(42, schema)
        assert any("expected type 'string'" in e for e in errs)

    def test_minlength(self):
        schema = {"type": "string", "minLength": 5}
        assert validate("hello", schema) == []
        assert any("minLength" in e for e in validate("hi", schema))

    def test_pattern(self):
        schema = {"type": "string", "pattern": "^FR-\\d+$"}
        assert validate("FR-001", schema) == []
        errs = validate("FR-X", schema)
        assert any("pattern" in e for e in errs)

    def test_enum(self):
        schema = {"enum": ["a", "b"]}
        assert validate("a", schema) == []
        assert any("must be one of" in e for e in validate("c", schema))

    def test_array_minitems(self):
        schema = {"type": "array", "minItems": 2}
        assert validate([1, 2], schema) == []
        assert any("minItems" in e for e in validate([1], schema))

    def test_oneof_exactly_one(self):
        schema = {"oneOf": [{"type": "string"}, {"type": "integer"}]}
        assert validate("x", schema) == []
        assert validate(7, schema) == []
        # bool matches neither (we exclude bool from int)
        errs = validate(True, schema)
        assert any("oneOf" in e for e in errs)

    def test_ref_resolution(self):
        schema = {
            "type": "object",
            "properties": {"row": {"$ref": "#/definitions/row"}},
            "definitions": {"row": {"type": "string", "minLength": 3}},
        }
        assert validate({"row": "abc"}, schema) == []
        errs = validate({"row": "ab"}, schema)
        assert any("minLength" in e for e in errs)

    def test_const(self):
        schema = {"const": 2}
        assert validate(2, schema) == []
        assert any("must equal 2" in e for e in validate(3, schema))

    def test_additional_properties_false(self):
        schema = {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "additionalProperties": False,
        }
        assert validate({"a": "x"}, schema) == []
        errs = validate({"a": "x", "b": 1}, schema)
        assert any("additional properties not allowed" in e for e in errs)

    def test_object_minproperties(self):
        schema = {"type": "object", "minProperties": 1}
        errs = validate({}, schema)
        assert any("minProperties" in e for e in errs)


# -- waterfall_v2_loader: bundled file ------------------------------------


class TestLoadBundledWaterfallV2:
    def test_loads_default_file_without_error(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        assert isinstance(spec, WaterfallV2Spec)
        assert spec.process_id == "waterfall_v2"
        assert spec.schema_version == 2

    def test_six_phases_in_order(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        ids = [p.id for p in spec.phases]
        assert ids == [
            "requirements",
            "architecture",
            "implementation",
            "main_entry",
            "verification",
            "delivery",
        ]

    def test_phase_producer_reviewer_assignment(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        # architecture has dual reviewer
        arch = spec.phase_by_id("architecture")
        assert arch is not None
        assert arch.producer == "architect"
        assert arch.reviewer == ("developer", "qa_engineer")
        # delivery's reviewer is rd_director
        dlv = spec.phase_by_id("delivery")
        assert dlv is not None
        assert dlv.reviewer == ("rd_director",)

    def test_review_budget_3_everywhere(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        for ph in spec.phases:
            assert ph.review is not None, ph.id
            assert ph.review.revise_budget == 3, ph.id
            assert ph.review.consensus == "ALL_PASS", ph.id
            assert ph.review.on_revise_exhausted == "continue_with_marker", ph.id

    def test_implementation_fanout_subsystem_dag_two_stages(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        impl = spec.phase_by_id("implementation")
        assert impl is not None and impl.fanout is not None
        assert impl.fanout.strategy == "subsystem_dag"
        assert [s.id for s in impl.fanout.stages] == ["skeleton", "component"]
        sk, cp = impl.fanout.stages
        assert sk.tier == "T1"
        assert cp.tier == "T2"
        assert cp.depends_on == "skeleton"
        assert cp.group_by == "subsystem"
        for stage in (sk, cp):
            assert stage.concurrency.join_policy == "ALL_PASS"
            assert stage.concurrency.per_task_retries == 3
            assert stage.concurrency.on_task_failure_after_retries == "phase_halt"

    def test_verification_runner_unavailable_mode(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        ver = spec.phase_by_id("verification")
        assert ver is not None and ver.fanout is not None
        ((stage,)) = ver.fanout.stages
        assert stage.mode_when_runner_unavailable == "write_only"

    def test_verification_has_qa_report_deliverable(self):
        """Regression: 2026-05-05 phase-test matrix found qa_engineer
        skipping docs/qa_report.json on TS / Go / C++ runs because the
        artifact was REQUIRED only in qa_engineer.md prose, not in
        the process spec. The fix promoted it to an AUTO_GATE
        deliverable with file_exists + schema acceptance. This test
        guards against silent removal."""
        spec = load_waterfall_v2(default_waterfall_v2_path())
        ver = spec.phase_by_id("verification")
        assert ver is not None
        qa_report_dlv = [d for d in ver.deliverables if d.kind == "document" and d.path == "docs/qa_report.json"]
        assert qa_report_dlv, (
            "verification phase must declare docs/qa_report.json as a "
            "document deliverable; otherwise qa_engineer can skip writing it "
            "and phase 6 (delivery) reads garbage"
        )
        kinds = [a.kind for a in qa_report_dlv[0].acceptance]
        assert "file_exists" in kinds
        assert "schema" in kinds, (
            "qa_report.json deliverable must carry a schema-validation "
            "predicate so toolchain-missing branches that fabricate counts "
            "still get caught at AUTO_GATE"
        )
        # The schema arg points at the bundled JSON-Schema file.
        schema_arg = [a for a in qa_report_dlv[0].acceptance if a.kind == "schema"][0].arg
        assert schema_arg == "schemas/qa_report.schema.json"

    def test_acceptance_predicates_parsed(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        req = spec.phase_by_id("requirements")
        assert req is not None
        # First deliverable: docs/requirement.md
        d0 = req.deliverables[0]
        assert d0.kind == "document"
        assert d0.path == "docs/requirement.md"
        kinds = [a.kind for a in d0.acceptance]
        assert "file_exists" in kinds
        assert "min_bytes" in kinds
        assert "contains_sections" in kinds
        # The min_bytes predicate carries its int arg
        min_bytes = [a for a in d0.acceptance if a.kind == "min_bytes"][0]
        assert min_bytes.arg == 2000
        # contains_sections carries the section list
        sections = [a for a in d0.acceptance if a.kind == "contains_sections"][0]
        assert sections.arg == ["功能需求", "非功能需求", "用例"]

    def test_derived_deliverable_carries_from_and_rule(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        impl = spec.phase_by_id("implementation")
        assert impl is not None
        derived = [d for d in impl.deliverables if d.kind == "derived"]
        assert len(derived) == 2
        rules = sorted(d.rule for d in derived)
        assert rules == ["every_component.file", "every_component.test_file"]
        for d in derived:
            assert d.from_ == "stack_contract"

    def test_phase_navigation_helpers(self):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        assert spec.phase_index("architecture") == 1
        nxt = spec.next_phase("architecture")
        assert nxt is not None and nxt.id == "implementation"
        assert spec.next_phase("delivery") is None
        assert spec.terminal_phase == "delivery"


# -- waterfall_v2_loader: error paths -------------------------------------


class TestLoaderErrorPaths:
    def test_no_frontmatter_raises(self):
        with pytest.raises(ProcessSpecError, match="frontmatter"):
            load_waterfall_v2("# Just a heading, no frontmatter\n")

    def test_wrong_schema_version_raises(self):
        text = textwrap.dedent(
            """\
            ---
            process_id: foo
            schema_version: 1
            phases: []
            ---
            """
        )
        with pytest.raises(ProcessSpecError, match="schema_version"):
            load_waterfall_v2(text)

    def test_missing_required_phase_field_reports_via_schema(self):
        text = textwrap.dedent(
            """\
            ---
            process_id: foo
            schema_version: 2
            phases:
              - id: p1
                # missing producer + deliverables
            ---
            """
        )
        with pytest.raises(ProcessSpecError, match="schema validation"):
            load_waterfall_v2(text)

    def test_acceptance_dict_must_have_one_key(self, tmp_path: Path):
        # write a minimal valid-ish process whose deliverable has a
        # bad acceptance entry; schema lets it through (oneOf branch
        # for object only checks min/maxProperties, but the loader
        # post-check rejects len != 1)
        text = textwrap.dedent(
            """\
            ---
            process_id: bad
            schema_version: 2
            phases:
              - id: p1
                producer: dev
                deliverables:
                  - kind: document
                    path: docs/x.md
                    acceptance:
                      - {a: 1, b: 2}
            ---
            """
        )
        with pytest.raises(ProcessSpecError):
            load_waterfall_v2(text)


# -- Companion: validate the bundled JSON schemas are themselves valid ----


class TestSchemaFilesAreValid:
    """Each schemas/*.json must at least be valid JSON and declare $id."""

    @pytest.fixture
    def schemas_dir(self) -> Path:
        # tests/test_runtime/test_waterfall_v2_loader.py → up 2 → repo
        return Path(__file__).resolve().parent.parent.parent / "src" / "aise" / "schemas"

    def test_all_schema_files_parse(self, schemas_dir: Path):
        files = list(schemas_dir.glob("*.schema.json"))
        assert len(files) >= 4
        for f in files:
            data = json.loads(f.read_text(encoding="utf-8"))
            assert "$id" in data, f"{f.name} missing $id"
            assert data["$schema"].startswith("http://json-schema.org/")
