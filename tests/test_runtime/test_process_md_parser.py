"""Tests for process.md parser."""

from pathlib import Path

import pytest

from aise.runtime.process_md_parser import parse_process_md

LEGACY_BULLET_PROCESS = """\
# Waterfall Software Development Process
- process_id: waterfall_standard_v1
- name: Sequential Waterfall Lifecycle
- work_type: structured_development
- keywords: waterfall, sequential, design-first
- summary: A linear approach

## Steps
### phase_1_requirement: Requirement Specification
#### step_raw_requirement: Raw Requirement Expansion
- agents: product_designer
- description: Expand the raw requirement.
#### step_sys_requirement: Requirement Analysis
- agents: product_designer, product_reviewer
- description: Analyse the expanded requirement.

### phase_3_implementation: Development
- agents: developer, committer
- description: Build the system from the design.

### phase_4_verification: Integration & Testing
- agents: qa_engineer
- description: Run integration tests.
"""

FRONTMATTER_PROCESS = """\
---
process_id: tdd_loop_v1
name: TDD Loop
work_type: structured_development
keywords: tdd, test-first
summary: Repeats write-test then implement.
caps:
  max_dispatches: 20
  max_continuations: 8
terminal_step: deliver_report
required_phases:
  - phase_implement
  - phase_verify
---

## Steps
### phase_implement: Implementation
#### step_write_tests
- agents: developer
- description: Write failing unit tests first.
- deliverables: tests/
#### step_implement
- agents: developer
- description: Make tests pass.
- deliverables: src/
- on_failure: retry_with_output
- max_retries: 3
- verification_command: python -m pytest tests/ -q

### phase_verify: Verification
#### deliver_report
- agents: project_manager
- description: Produce the final delivery report.
- deliverables: docs/delivery_report.md
"""


class TestParseProcessMd:
    def test_legacy_bullet_format(self):
        proc = parse_process_md(LEGACY_BULLET_PROCESS)
        assert proc.process_id == "waterfall_standard_v1"
        assert proc.name == "Sequential Waterfall Lifecycle"
        assert proc.work_type == "structured_development"
        assert "waterfall" in proc.keywords

    def test_legacy_phases(self):
        proc = parse_process_md(LEGACY_BULLET_PROCESS)
        ids = [ph.id for ph in proc.phases]
        assert ids == [
            "phase_1_requirement",
            "phase_3_implementation",
            "phase_4_verification",
        ]

    def test_legacy_steps(self):
        proc = parse_process_md(LEGACY_BULLET_PROCESS)
        phase1 = proc.phases[0]
        # Two explicit steps
        assert len(phase1.steps) == 2
        assert phase1.steps[0].id == "step_raw_requirement"
        assert phase1.steps[0].agents == ["product_designer"]
        assert phase1.steps[1].agents == ["product_designer", "product_reviewer"]

    def test_legacy_synthetic_step_from_phase_bullets(self):
        """A phase with bullets but no #### step heading becomes one synthetic step."""
        proc = parse_process_md(LEGACY_BULLET_PROCESS)
        phase3 = proc.phases[1]
        assert phase3.id == "phase_3_implementation"
        assert len(phase3.steps) == 1
        synthetic = phase3.steps[0]
        assert synthetic.id == "phase_3_implementation"
        assert synthetic.agents == ["developer", "committer"]

    def test_frontmatter_metadata(self):
        proc = parse_process_md(FRONTMATTER_PROCESS)
        assert proc.process_id == "tdd_loop_v1"
        assert proc.terminal_step == "deliver_report"
        assert proc.caps.max_dispatches == 20
        assert proc.caps.max_continuations == 8
        assert proc.required_phases == ["phase_implement", "phase_verify"]

    def test_frontmatter_step_extras(self):
        proc = parse_process_md(FRONTMATTER_PROCESS)
        impl = proc.phases[0]
        # 2 steps in phase_implement
        assert len(impl.steps) == 2
        impl_step = impl.steps[1]
        assert impl_step.id == "step_implement"
        assert impl_step.deliverables == ["src/"]
        assert impl_step.on_failure == "retry_with_output"
        assert impl_step.max_retries == 3
        assert impl_step.verification_command == "python -m pytest tests/ -q"

    def test_all_step_ids(self):
        proc = parse_process_md(FRONTMATTER_PROCESS)
        assert proc.all_step_ids() == ["step_write_tests", "step_implement", "deliver_report"]

    def test_header_dict_round_trip(self):
        proc = parse_process_md(FRONTMATTER_PROCESS)
        h = proc.header_dict()
        assert h["process_id"] == "tdd_loop_v1"
        assert h["name"] == "TDD Loop"
        assert h["keywords"] == "tdd, test-first"

    def test_missing_process_id_raises(self):
        bad = "# Something\n- name: missing id\n"
        with pytest.raises(ValueError, match="process_id"):
            parse_process_md(bad)

    def test_parse_from_file(self, tmp_path: Path):
        pf = tmp_path / "tdd.process.md"
        pf.write_text(FRONTMATTER_PROCESS)
        proc = parse_process_md(pf)
        assert proc.process_id == "tdd_loop_v1"

    def test_parses_real_waterfall(self):
        """The bundled waterfall.process.md must parse without error."""
        repo_root = Path(__file__).resolve().parent.parent.parent
        pf = repo_root / "src" / "aise" / "processes" / "waterfall.process.md"
        proc = parse_process_md(pf)
        assert proc.process_id == "waterfall_standard_v1"
        assert len(proc.phases) >= 3

    def test_parses_real_agile(self):
        repo_root = Path(__file__).resolve().parent.parent.parent
        pf = repo_root / "src" / "aise" / "processes" / "agile.process.md"
        proc = parse_process_md(pf)
        assert proc.process_id  # whatever it is, it must exist
        assert len(proc.phases) >= 1
