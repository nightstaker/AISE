"""End-to-end mock-LLM integration test for waterfall_v2 (commit c14).

Exercises the full PRODUCE / AUTO_GATE / REVIEWER / DECISION /
PHASE_HALT flow across all 6 phases without requiring a real LLM
backend. The "LLM" is a deterministic dispatcher that returns
canned-but-realistic responses for each (role, phase) pair.

Coverage:
* Happy path: 6 phases, all PASS, no halt, all tags emitted
* Revise loop: reviewer says REVISE on first round, PASS on second
* Producer hard fail: phase halts, halt state saved, driver returns
* Resume: pre-seeded halt → driver picks up at the halted phase

This test is the user-visible behavior contract for the PR — if the
test fails, the design isn't doing what the design discussion agreed.
"""

from __future__ import annotations

import json
from pathlib import Path

from aise.runtime.halt_resume import HaltState, is_halted, save_halt_state
from aise.runtime.waterfall_v2_driver import WaterfallV2Driver

# -- MockLLM -------------------------------------------------------------


class MockLLM:
    """Deterministic stand-in for the producer/reviewer dispatch.

    Responds based on role + observed prompt content. Maintains
    per-(role, phase) call counts so tests can assert "the architect
    was called twice in revise loop"."""

    def __init__(self, *, project_root: Path, reviewer_responses: dict | None = None):
        self.project_root = project_root
        self.reviewer_responses = reviewer_responses or {}
        self.call_log: list[tuple[str, str]] = []  # (role, classifier)

    def produce(self, role: str, prompt: str, expected: tuple) -> str:
        self.call_log.append((role, "produce"))
        # Materialize artifacts based on role (deterministic happy-path)
        if role == "product_manager":
            self._write_phase_1()
        elif role == "architect":
            self._write_phase_2()
        elif role == "developer":
            # Could be implementation, main_entry, or verification fanout
            for path in expected:
                p = self.project_root / path.lstrip("/")
                p.parent.mkdir(parents=True, exist_ok=True)
                if not p.exists():
                    p.write_text(f"# stub for {path}\n" + "x" * 250, encoding="utf-8")
        elif role == "qa_engineer":
            for path in expected:
                p = self.project_root / path.lstrip("/")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(f"# qa stub for {path}\n" + "x" * 250, encoding="utf-8")
        elif role == "project_manager":
            self._write_phase_6()
        return f"{role} produced"

    def review(self, role: str, prompt: str) -> str:
        self.call_log.append((role, "review"))
        # Defaults to PASS unless tests pre-seed a different sequence
        if role in self.reviewer_responses:
            seq = self.reviewer_responses[role]
            if seq:
                return seq.pop(0)
        return "PASS\nlgtm"

    # -- artifact materializers --

    def _write_phase_1(self) -> None:
        docs = self.project_root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "requirement.md").write_text(
            "## 功能需求\nFR-001\n## 非功能需求\nNFR-001\n## 用例\nUC-001\n" + "x" * 2500,
            encoding="utf-8",
        )
        (docs / "requirement_contract.json").write_text(
            json.dumps(
                {
                    "functional_requirements": [{"id": "FR-001", "title": "t", "description": "d"}],
                    "non_functional_requirements": [],
                }
            ),
            encoding="utf-8",
        )

    def _write_phase_2(self) -> None:
        docs = self.project_root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "architecture.md").write_text("# Architecture\n" + "x" * 5500, encoding="utf-8")
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
                    ],
                }
            ],
            "lifecycle_inits": [],
        }
        (docs / "stack_contract.json").write_text(json.dumps(sc), encoding="utf-8")
        bc = {
            "scenarios": [{"id": f"sc{i}", "name": f"S{i}", "trigger": {"x": i}, "effect": {"y": i}} for i in range(5)]
        }
        (docs / "behavioral_contract.json").write_text(json.dumps(bc), encoding="utf-8")

    def _write_phase_6(self) -> None:
        docs = self.project_root / "docs"
        docs.mkdir(parents=True, exist_ok=True)
        (docs / "delivery_report.md").write_text(
            "## 验收结论\nshipped.\n## 已知 issue\nnone.\n## 下一步建议\niter.\n"
            "Built per docs/requirement.md and docs/architecture.md.\n"
            "Stack: docs/stack_contract.json. Behavior: docs/behavioral_contract.json.\n" + "x" * 1500,
            encoding="utf-8",
        )


# -- Happy path e2e -------------------------------------------------------


class TestHappyPath:
    def test_six_phase_run_completes(self, tmp_path: Path):
        mock = MockLLM(project_root=tmp_path)
        driver = WaterfallV2Driver(
            project_root=tmp_path,
            produce_fn=mock.produce,
            dispatch_reviewer=mock.review,
        )
        result = driver.run("Build the e2e widget")
        assert result.status == "completed"
        assert result.completed_phases == (
            "requirements",
            "architecture",
            "implementation",
            "main_entry",
            "verification",
            "delivery",
        )
        # No halt file
        assert not is_halted(tmp_path)
        # All 6 phase results present
        assert len(result.phase_results) == 6
        for r in result.phase_results:
            assert r.status.value in ("passed", "passed_with_unresolved_review")

    def test_artifacts_actually_landed(self, tmp_path: Path):
        mock = MockLLM(project_root=tmp_path)
        driver = WaterfallV2Driver(
            project_root=tmp_path,
            produce_fn=mock.produce,
            dispatch_reviewer=mock.review,
        )
        driver.run("Build")
        assert (tmp_path / "docs" / "requirement.md").is_file()
        assert (tmp_path / "docs" / "architecture.md").is_file()
        assert (tmp_path / "docs" / "stack_contract.json").is_file()
        assert (tmp_path / "docs" / "behavioral_contract.json").is_file()
        assert (tmp_path / "src" / "main.py").is_file()
        assert (tmp_path / "src" / "core" / "router.py").is_file()
        assert (tmp_path / "tests" / "scenarios" / "sc0.py").is_file()
        assert (tmp_path / "docs" / "delivery_report.md").is_file()


# -- Revise loop --------------------------------------------------------


class TestReviewerReviseLoop:
    def test_revise_then_pass(self, tmp_path: Path):
        # architect reviewer says REVISE first round, PASS second round
        mock = MockLLM(
            project_root=tmp_path,
            reviewer_responses={
                "architect": ["REVISE\nadd more detail", "PASS\nbetter"],
            },
        )
        driver = WaterfallV2Driver(
            project_root=tmp_path,
            produce_fn=mock.produce,
            dispatch_reviewer=mock.review,
        )
        result = driver.run("Build")
        assert result.status == "completed"
        # phase 1's review was called twice
        review_calls = [(r, c) for r, c in mock.call_log if c == "review"]
        architect_reviews = [c for c in review_calls if c[0] == "architect"]
        assert len(architect_reviews) >= 2  # 1 initial + ≥1 revise

    def test_revise_budget_exhaustion_continues_with_marker(self, tmp_path: Path):
        # architect reviewer ALWAYS REVISE → budget exhausted → continues
        mock = MockLLM(
            project_root=tmp_path,
            reviewer_responses={
                "architect": ["REVISE"] * 10,  # plenty of REVISE responses
            },
        )
        driver = WaterfallV2Driver(
            project_root=tmp_path,
            produce_fn=mock.produce,
            dispatch_reviewer=mock.review,
        )
        result = driver.run("Build")
        # Run still completes (Decision 1: continue_with_marker)
        assert result.status == "completed"
        # Phase 1's result is passed_with_unresolved_review
        req_result = result.phase_results[0]
        assert req_result.phase_id == "requirements"
        assert req_result.status.value == "passed_with_unresolved_review"


# -- Producer hard fail / halt -----------------------------------------


class TestProducerHardFail:
    def test_phase_halts_when_producer_cant_satisfy_gates(self, tmp_path: Path):
        # MockLLM that never writes anything
        class BrokenLLM:
            def produce(self, role, prompt, expected):
                return "(nothing produced)"

            def review(self, role, prompt):
                return "PASS"

        mock = BrokenLLM()
        driver = WaterfallV2Driver(
            project_root=tmp_path,
            produce_fn=mock.produce,
            dispatch_reviewer=mock.review,
        )
        result = driver.run("Build")
        assert result.halted
        assert result.halt_state is not None
        # Phase 1 (requirements) is the first one that fails
        assert result.halt_state.halted_at_phase == "requirements"
        assert is_halted(tmp_path)
        # Halt state was persisted
        from aise.runtime.halt_resume import load_halt_state

        loaded = load_halt_state(tmp_path)
        assert loaded is not None
        assert loaded.halted_at_phase == "requirements"


# -- Resume from halt ---------------------------------------------------


class TestResume:
    def test_resume_skips_completed_phases(self, tmp_path: Path):
        # Pre-seed: phases 1-3 done, halted at main_entry
        save_halt_state(
            tmp_path,
            HaltState(
                halted_at_phase="main_entry",
                halt_reason="prior",
                completed_phases=("requirements", "architecture", "implementation"),
            ),
        )
        # Stage all earlier-phase artifacts (resume doesn't re-create them)
        mock_pre = MockLLM(project_root=tmp_path)
        mock_pre._write_phase_1()
        mock_pre._write_phase_2()
        # Stage component files (phase 3 normally would)
        (tmp_path / "src" / "core").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "core" / "router.py").write_text("# stub\n" + "x" * 200, encoding="utf-8")
        (tmp_path / "src" / "core" / "__init__.py").write_text("# barrel\n" + "x" * 200, encoding="utf-8")

        # Now run with a tracking mock
        mock = MockLLM(project_root=tmp_path)
        driver = WaterfallV2Driver(
            project_root=tmp_path,
            produce_fn=mock.produce,
            dispatch_reviewer=mock.review,
        )
        result = driver.run("Build")
        assert result.status == "completed"
        # Phases re-run on resume = main_entry, verification, delivery
        # The completed_phases tuple in result tracks ONLY phases run
        # in this resume invocation, not pre-existing tags. We verify
        # the producer was NOT called for phases 1-3.
        produce_calls = [r for r, c in mock.call_log if c == "produce"]
        assert "product_manager" not in produce_calls  # phase 1 skipped
        assert "architect" not in produce_calls  # phase 2 skipped
        # halt file cleared
        assert not is_halted(tmp_path)
