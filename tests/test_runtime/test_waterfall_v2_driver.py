"""Tests for the waterfall_v2 driver (commit c4)."""

from __future__ import annotations

import json
from pathlib import Path

from aise.runtime.halt_resume import is_halted, load_halt_state, save_halt_state
from aise.runtime.observability import get_registry
from aise.runtime.waterfall_v2_driver import (
    RunResult,
    WaterfallV2Driver,
    make_observable_produce_fn,
)

# -- Helpers --------------------------------------------------------------


def _passing_produce(tmp_path: Path):
    """produce_fn that satisfies waterfall_v2's acceptance gates for
    every phase by writing all the needed artifacts on first call."""

    def produce(role, prompt, expected):
        docs = tmp_path / "docs"
        docs.mkdir(parents=True, exist_ok=True)

        # Phase 1
        (docs / "requirement.md").write_text(
            "## 功能需求\nFR-001\n## 非功能需求\nNFR\n## 用例\n" + "x" * 2500,
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

        # Phase 2
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
            "scenarios": [{"id": f"s{i}", "name": f"S{i}", "trigger": {"x": i}, "effect": {"y": i}} for i in range(5)]
        }
        (docs / "behavioral_contract.json").write_text(json.dumps(bc), encoding="utf-8")

        # Phase 3 fanout: write the component file + entry point
        (tmp_path / "src" / "core").mkdir(parents=True, exist_ok=True)
        (tmp_path / "src" / "core" / "router.py").write_text("# router stub\n" + "x" * 200, encoding="utf-8")
        (tmp_path / "src" / "core" / "__init__.py").write_text("# barrel\n" + "x" * 200, encoding="utf-8")
        (tmp_path / "src" / "main.py").write_text("# entry\n" + "x" * 200, encoding="utf-8")

        # Phase 4 (main_entry) requires integration_report.json (added
        # 2026-05-06 to harden assembly). Project has no
        # data_dependency_contract / action_contract on disk, so the
        # static gates vacuous-pass and a verdict=skipped is the
        # natural value.
        (docs / "integration_report.json").write_text(
            json.dumps(
                {
                    "phase": "main_entry",
                    "completed_at": "2026-05-06T00:00:00Z",
                    "verdict": "skipped",
                    "boot_check": {
                        "ran": False,
                        "verdict": "skipped",
                        "reason": "no contracts to enforce; legacy project shape",
                    },
                }
            ),
            encoding="utf-8",
        )

        # Phase 5 fanout: write scenario tests
        (tmp_path / "tests" / "scenarios").mkdir(parents=True, exist_ok=True)
        for sid in (f"s{i}" for i in range(5)):
            (tmp_path / "tests" / "scenarios" / f"{sid}.py").write_text("# scenario\n" + "x" * 250, encoding="utf-8")
        # Phase 5 also requires docs/qa_report.json (promoted to an
        # AUTO_GATE deliverable on 2026-05-05). Schema validates against
        # schemas/qa_report.schema.json — minimal valid shape below.
        (docs / "qa_report.json").write_text(
            json.dumps(
                {
                    "phase": "qa",
                    "completed_at": "2026-05-05T00:00:00Z",
                    "toolchain_check": {"pytest": "present"},
                    "pytest": {
                        "command": "python -m pytest -q",
                        "ran": True,
                        "passed": 5,
                        "failed": 0,
                        "skipped": 0,
                        "failed_tests": [],
                    },
                }
            ),
            encoding="utf-8",
        )

        # Phase 6 delivery
        (docs / "delivery_report.md").write_text(
            "## 验收结论\nok.\n## 已知 issue\nnone.\n## 下一步建议\nship.\n"
            "Built per docs/requirement.md and docs/architecture.md.\n"
            "Stack: docs/stack_contract.json. Behavior: docs/behavioral_contract.json.\n" + "x" * 1500,
            encoding="utf-8",
        )

        return f"produced ({role})"

    return produce


# -- Full happy path ------------------------------------------------------


class TestRunFullPipeline:
    def test_runs_all_six_phases(self, tmp_path: Path):
        driver = WaterfallV2Driver(
            project_root=tmp_path,
            produce_fn=_passing_produce(tmp_path),
            dispatch_reviewer=lambda role, prompt: "PASS",
        )
        result = driver.run("Build a thing")
        assert isinstance(result, RunResult)
        assert result.status == "completed", result.phase_results[-1].failure_summary
        assert result.completed_phases == (
            "requirements",
            "architecture",
            "implementation",
            "main_entry",
            "verification",
            "delivery",
        )
        assert not result.halted
        assert not is_halted(tmp_path)


# -- Halt + resume --------------------------------------------------------


class TestHaltAndResume:
    def test_halts_on_phase_failure(self, tmp_path: Path):
        # producer never writes anything → phase 1 AUTO_GATE exhausts → halt
        def bad_produce(role, prompt, expected):
            return "(nothing)"

        driver = WaterfallV2Driver(
            project_root=tmp_path,
            produce_fn=bad_produce,
            dispatch_reviewer=lambda role, prompt: "PASS",
        )
        result = driver.run("x")
        assert result.halted
        assert result.halt_state is not None
        assert result.halt_state.halted_at_phase == "requirements"
        assert is_halted(tmp_path)

    def test_resume_picks_up_at_halted_phase(self, tmp_path: Path):
        from aise.runtime.halt_resume import HaltState

        # Pre-seed a halt state at phase 4 (main_entry)
        save_halt_state(
            tmp_path,
            HaltState(
                halted_at_phase="main_entry",
                halt_reason="prior_failure",
                completed_phases=("requirements", "architecture", "implementation"),
            ),
        )
        # Now stage all the artifacts the EARLIER phases would have
        # produced (since resume skips them)
        prod = _passing_produce(tmp_path)
        prod("dev", "", ())  # writes everything

        # Driver run should pick up at main_entry
        called_phases: list[str] = []

        def tracking_produce(role, prompt, expected):
            # Detect which phase by inspecting expected_artifacts
            # main_entry's expected = entry_point (src/main.py)
            # verification expected = scenario tests
            # delivery expected = delivery_report.md
            for e in expected:
                if "main.py" in e:
                    called_phases.append("main_entry")
                elif "tests/scenarios" in e:
                    called_phases.append("verification")
                elif "delivery_report" in e:
                    called_phases.append("delivery")
                break  # just look at first expected
            return "ok"

        driver = WaterfallV2Driver(
            project_root=tmp_path,
            produce_fn=tracking_produce,
            dispatch_reviewer=lambda role, prompt: "PASS",
        )
        driver.run("x")
        # Resume cleared the halt file
        assert not is_halted(tmp_path)
        # Earlier phases were NOT re-executed
        assert "requirements" not in called_phases
        assert "architecture" not in called_phases

    def test_failed_resume_leaves_new_halt(self, tmp_path: Path):
        """If a resumed phase fails, halt state is re-saved (NOT
        regressing back to phase 1). This test exercises the path:
        resume at main_entry → verification has empty contracts →
        verification fanout fails → halt at verification (or earlier
        phase that hits it first)."""
        from aise.runtime.halt_resume import HaltState

        save_halt_state(
            tmp_path,
            HaltState(
                halted_at_phase="main_entry",
                halt_reason="x",
                completed_phases=("requirements", "architecture", "implementation"),
            ),
        )
        # No artifacts of any kind → some downstream phase will fail
        driver = WaterfallV2Driver(
            project_root=tmp_path,
            produce_fn=lambda r, p, e: "(nothing)",
            dispatch_reviewer=lambda r, p: "PASS",
        )
        result = driver.run("x")
        assert result.halted
        assert is_halted(tmp_path)
        new_halt = load_halt_state(tmp_path)
        # New halt should NOT regress to a phase earlier than main_entry
        # (the resume started there). Acceptable values: main_entry or
        # any phase after it.
        phase_order = ("requirements", "architecture", "implementation", "main_entry", "verification", "delivery")
        new_idx = phase_order.index(new_halt.halted_at_phase)
        main_entry_idx = phase_order.index("main_entry")
        assert new_idx >= main_entry_idx, (
            f"resume must not regress; halted at {new_halt.halted_at_phase} but resume started at main_entry"
        )


# -- Observability bridge ------------------------------------------------


class TestObservableProduceFnWrapper:
    def test_registers_and_marks_completed(self, tmp_path: Path):
        get_registry().clear()
        try:
            calls = []

            def underlying(role, prompt, expected):
                calls.append(role)
                return "ok"

            wrapped = make_observable_produce_fn(underlying)
            wrapped("developer", "do it", ["src/x.py"])
            wrapped("developer", "again", ["src/y.py"])
            assert calls == ["developer", "developer"]
            all_t = get_registry().all_tasks()
            assert len(all_t) == 2
            for snap in all_t:
                assert snap.agent == "developer"
                assert snap.status == "completed"
        finally:
            get_registry().clear()

    def test_registers_and_marks_failed_on_exception(self, tmp_path: Path):
        get_registry().clear()
        try:

            def underlying(role, prompt, expected):
                raise RuntimeError("boom")

            wrapped = make_observable_produce_fn(underlying)
            try:
                wrapped("dev", "x", [])
            except RuntimeError:
                pass
            all_t = get_registry().all_tasks()
            assert len(all_t) == 1
            assert all_t[0].status == "failed"
        finally:
            get_registry().clear()
