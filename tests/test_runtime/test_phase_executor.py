"""Tests for PhaseExecutor (commit c3)."""

from __future__ import annotations

import json
from pathlib import Path

from aise.runtime.phase_executor import (
    ConcurrentRunner,
    PhaseExecutor,
    PhaseResult,
    PhaseStatus,
)
from aise.runtime.waterfall_v2_loader import (
    default_waterfall_v2_path,
    load_waterfall_v2,
)

# -- Helpers --------------------------------------------------------------


def _make_stack_contract(tmp_path: Path) -> dict:
    sc = {
        "language": "python",
        "framework_backend": "none",
        "package_manager": "pip",
        "test_runner": "pytest",
        "entry_point": "src/main.py",
        "run_command": "python -m src.main",
        "ui_required": False,
        "subsystems": [
            {
                "name": "core",
                "src_dir": "src/core",
                "components": [
                    {"name": "router", "file": "src/core/router.py"},
                    {"name": "store", "file": "src/core/store.py"},
                ],
            }
        ],
        "lifecycle_inits": [],
    }
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "stack_contract.json").write_text(json.dumps(sc), encoding="utf-8")
    return sc


def _make_behavioral_contract(tmp_path: Path, *, n: int = 5) -> dict:
    """Default n=5 to satisfy waterfall_v2's min_scenarios=5 acceptance."""
    bc = {
        "scenarios": [
            {
                "id": f"sc_{i}",
                "name": f"Scenario {i}",
                "trigger": {"x": i},
                "effect": {"y": i},
            }
            for i in range(n)
        ]
    }
    (tmp_path / "docs" / "behavioral_contract.json").write_text(json.dumps(bc), encoding="utf-8")
    return bc


def _writes_to(tmp_path: Path, *, files: dict[str, str]):
    """Returns a produce_fn that, when called, writes all given files
    relative to tmp_path. ``files`` is a dict of relpath → content.
    Non-trivial content size (>= 200 bytes per file) so min_bytes
    predicates pass."""

    def produce(role, prompt, expected):
        for rel, content in files.items():
            target = tmp_path / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return f"produced ({role})"

    return produce


# -- Single-writer phase end-to-end ---------------------------------------


class TestSingleWriterPhase:
    def test_passes_when_deliverables_meet_acceptance(self, tmp_path: Path):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        req_phase = spec.phase_by_id("requirements")
        # Materialize a passing requirement.md and requirement_contract.json
        body = (
            "# 项目\n\n## 功能需求\nFR-001 something\n\n"
            "## 非功能需求\nNFR-001 perf\n\n## 用例\nUC-001\n" + "x" * 2500  # min_bytes=2000
        )
        contract = {
            "functional_requirements": [{"id": "FR-001", "title": "t", "description": "d"}],
            "non_functional_requirements": [],
        }
        produce = _writes_to(
            tmp_path,
            files={
                "docs/requirement.md": body,
                "docs/requirement_contract.json": json.dumps(contract),
            },
        )
        # Reviewer always PASSes
        executor = PhaseExecutor(
            spec=spec,
            project_root=tmp_path,
            produce_fn=produce,
            dispatch_reviewer=lambda role, prompt: "PASS\nlgtm",
        )
        result = executor.execute_phase(req_phase, "Build a thing")
        assert isinstance(result, PhaseResult)
        assert result.status == PhaseStatus.PASSED
        assert result.producer_attempts == 1
        # All deliverable reports passed
        assert all(r.passed for r in result.deliverable_reports)

    def test_auto_gate_failure_re_invokes_producer(self, tmp_path: Path):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        req_phase = spec.phase_by_id("requirements")
        # First call: writes too-small file. Second call: writes proper one.
        attempt = {"n": 0}

        def produce(role, prompt, expected):
            attempt["n"] += 1
            (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
            if attempt["n"] == 1:
                # Tiny file → fails min_bytes
                (tmp_path / "docs" / "requirement.md").write_text("hi", encoding="utf-8")
                (tmp_path / "docs" / "requirement_contract.json").write_text(
                    json.dumps(
                        {
                            "functional_requirements": [{"id": "FR-001", "title": "t", "description": "d"}],
                            "non_functional_requirements": [],
                        }
                    ),
                    encoding="utf-8",
                )
            else:
                body = "## 功能需求\nFR-001\n## 非功能需求\nNFR-001\n## 用例\n" + "x" * 2500
                (tmp_path / "docs" / "requirement.md").write_text(body, encoding="utf-8")
                (tmp_path / "docs" / "requirement_contract.json").write_text(
                    json.dumps(
                        {
                            "functional_requirements": [{"id": "FR-001", "title": "t", "description": "d"}],
                            "non_functional_requirements": [],
                        }
                    ),
                    encoding="utf-8",
                )
            return "ok"

        executor = PhaseExecutor(
            spec=spec,
            project_root=tmp_path,
            produce_fn=produce,
            dispatch_reviewer=lambda role, prompt: "PASS",
        )
        result = executor.execute_phase(req_phase, "x")
        assert result.status == PhaseStatus.PASSED
        assert result.producer_attempts == 2

    def test_auto_gate_exhausted_returns_failed(self, tmp_path: Path):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        req_phase = spec.phase_by_id("requirements")

        # Producer never writes anything passable
        def produce(role, prompt, expected):
            (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
            (tmp_path / "docs" / "requirement.md").write_text("tiny", encoding="utf-8")
            return "fail"

        executor = PhaseExecutor(
            spec=spec,
            project_root=tmp_path,
            produce_fn=produce,
            dispatch_reviewer=lambda role, prompt: "PASS",
        )
        result = executor.execute_phase(req_phase, "x")
        assert result.status == PhaseStatus.FAILED
        assert result.producer_attempts == 3
        assert "AUTO_GATE failed" in result.failure_summary


# -- Reviewer revise loop ------------------------------------------------


class TestReviewerInteraction:
    def test_passed_with_unresolved_review_when_budget_exhausted(self, tmp_path: Path):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        req_phase = spec.phase_by_id("requirements")
        body = "## 功能需求\nFR-001\n## 非功能需求\nNFR\n## 用例\n" + "x" * 2500
        contract = {
            "functional_requirements": [{"id": "FR-001", "title": "t", "description": "d"}],
            "non_functional_requirements": [],
        }
        produce = _writes_to(
            tmp_path,
            files={
                "docs/requirement.md": body,
                "docs/requirement_contract.json": json.dumps(contract),
            },
        )
        # Reviewer always REVISE → exhaust budget
        executor = PhaseExecutor(
            spec=spec,
            project_root=tmp_path,
            produce_fn=produce,
            dispatch_reviewer=lambda role, prompt: "REVISE\nstill bad",
        )
        result = executor.execute_phase(req_phase, "x")
        assert result.status == PhaseStatus.PASSED_WITH_UNRESOLVED_REVIEW
        # Tag uses short suffix per decision (a)
        assert result.phase_tag(0).endswith("done_review_pending")

    def test_dual_reviewer_consensus(self, tmp_path: Path):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        arch_phase = spec.phase_by_id("architecture")
        # Materialize architecture deliverables
        (tmp_path / "docs").mkdir(exist_ok=True)
        (tmp_path / "docs" / "architecture.md").write_text("# arch\n" + "x" * 5500, encoding="utf-8")
        sc = _make_stack_contract(tmp_path)
        bc = _make_behavioral_contract(tmp_path)

        produce = _writes_to(
            tmp_path,
            files={
                "docs/architecture.md": "# arch\n" + "x" * 5500,
                "docs/stack_contract.json": json.dumps(sc),
                "docs/behavioral_contract.json": json.dumps(bc),
            },
        )

        # dev says PASS; qa says PASS → consensus pass
        executor = PhaseExecutor(
            spec=spec,
            project_root=tmp_path,
            produce_fn=produce,
            dispatch_reviewer=lambda role, prompt: "PASS",
            stack_contract=sc,
            behavioral_contract=bc,
        )
        result = executor.execute_phase(arch_phase, "x")
        assert result.status == PhaseStatus.PASSED
        assert result.review_result is not None
        assert len(result.review_result.final_consensus.feedbacks) == 2  # dev + qa

    def test_phase_tag_format(self, tmp_path: Path):
        result = PhaseResult(phase_id="architecture", status=PhaseStatus.PASSED)
        assert result.phase_tag(1) == "phase_2_architecture_done"

        result_pending = PhaseResult(phase_id="implementation", status=PhaseStatus.PASSED_WITH_UNRESOLVED_REVIEW)
        assert result_pending.phase_tag(2) == "phase_3_implementation_done_review_pending"


# -- Fanout (subsystem_dag) ----------------------------------------------


class TestSubsystemDagFanout:
    def test_passes_when_all_components_produced(self, tmp_path: Path):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        impl_phase = spec.phase_by_id("implementation")
        sc = _make_stack_contract(tmp_path)

        # Producer writes the .py file requested in expected_artifacts
        def produce(role, prompt, expected):
            for rel in expected or ():
                p = tmp_path / rel.lstrip("/")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("# " + "x" * 200, encoding="utf-8")
            return "ok"

        executor = PhaseExecutor(
            spec=spec,
            project_root=tmp_path,
            produce_fn=produce,
            dispatch_reviewer=lambda role, prompt: "PASS",
            stack_contract=sc,
        )
        result = executor.execute_phase(impl_phase, "Build core")
        assert result.status == PhaseStatus.PASSED, result.failure_summary
        # Fanout DagResult passed both stages
        assert result.fanout_result.passed

    def test_fanout_failure_returns_failed_status(self, tmp_path: Path):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        impl_phase = spec.phase_by_id("implementation")
        sc = _make_stack_contract(tmp_path)

        # Producer never writes anything → every fanout subtask fails its
        # acceptance check → ALL_PASS halts → producer hard fail
        def produce(role, prompt, expected):
            return "(no files written)"

        executor = PhaseExecutor(
            spec=spec,
            project_root=tmp_path,
            produce_fn=produce,
            dispatch_reviewer=lambda role, prompt: "PASS",
            stack_contract=sc,
        )
        result = executor.execute_phase(impl_phase, "x")
        assert result.status == PhaseStatus.FAILED
        assert "halted at stage" in result.failure_summary


# -- Verification phase (scenario_parallel fanout) ------------------------


class TestScenarioParallelFanout:
    def test_writes_one_test_per_scenario(self, tmp_path: Path):
        spec = load_waterfall_v2(default_waterfall_v2_path())
        ver_phase = spec.phase_by_id("verification")
        sc = _make_stack_contract(tmp_path)
        # Use only 2 scenarios for this fanout test (min_scenarios=5 is
        # only enforced in the architecture phase, not verification)
        bc = _make_behavioral_contract(tmp_path, n=2)

        produced: list[str] = []

        def produce(role, prompt, expected):
            produced.extend(expected or ())
            for rel in expected or ():
                p = tmp_path / rel.lstrip("/")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text("# valid\n" + "x" * 250, encoding="utf-8")
            # docs/qa_report.json is a phase-level ``document`` deliverable,
            # not part of the per-scenario fanout's ``expected``. The
            # real qa_engineer writes it on its own initiative
            # (qa_engineer.md STOPPING RULE); the test mock does the same
            # so AUTO_GATE's schema check passes.
            qa_report = tmp_path / "docs" / "qa_report.json"
            if not qa_report.exists():
                qa_report.parent.mkdir(parents=True, exist_ok=True)
                qa_report.write_text(
                    json.dumps(
                        {
                            "phase": "qa",
                            "toolchain_check": {"pytest": "present"},
                            "pytest": {
                                "command": "pytest",
                                "ran": True,
                                "passed": 1,
                                "failed": 0,
                                "skipped": 0,
                                "failed_tests": [],
                            },
                        }
                    ),
                    encoding="utf-8",
                )
            return "ok"

        executor = PhaseExecutor(
            spec=spec,
            project_root=tmp_path,
            produce_fn=produce,
            dispatch_reviewer=lambda role, prompt: "PASS",
            stack_contract=sc,
            behavioral_contract=bc,
        )
        result = executor.execute_phase(ver_phase, "verify")
        assert result.status == PhaseStatus.PASSED
        # 2 scenarios → 2 .py files (Python from stack_contract)
        assert "tests/scenarios/sc_0.py" in produced
        assert "tests/scenarios/sc_1.py" in produced


# -- Wiring sanity --------------------------------------------------------


class TestPhaseExecutorWiring:
    def test_runner_is_injectable(self, tmp_path: Path):
        # Use a stub runner that records calls
        recorded = {"dag_called": False}
        from aise.runtime.concurrent_executor import DagResult, StageResult

        def fake_dag(stages, fn):
            recorded["dag_called"] = True
            # Return passing empty result so the rest of the phase proceeds
            return DagResult(stage_results=tuple(StageResult(stage_id=s.id, results=()) for s in stages))

        runner = ConcurrentRunner(run_dag=fake_dag)
        spec = load_waterfall_v2(default_waterfall_v2_path())
        impl_phase = spec.phase_by_id("implementation")
        sc = _make_stack_contract(tmp_path)

        # Producer writes expected component files so AUTO_GATE passes
        # even though run_dag returned empty (stage results vacuously pass
        # via length-0 → not pass → that would fail; so use stack_contract
        # with no components instead)
        sc["subsystems"] = []
        (tmp_path / "docs" / "stack_contract.json").write_text(json.dumps(sc), encoding="utf-8")

        executor = PhaseExecutor(
            spec=spec,
            project_root=tmp_path,
            produce_fn=lambda r, p, e: "ok",
            dispatch_reviewer=lambda role, prompt: "PASS",
            runner=runner,
            stack_contract=sc,
        )
        # No subsystems → no fanout work → fanout result has empty stages
        # which our _fanout_passed treats as False (StageResult with 0
        # results is not passed). So this returns FAILED. We're only
        # asserting the runner WAS called.
        executor.execute_phase(impl_phase, "x")
        assert recorded["dag_called"]
