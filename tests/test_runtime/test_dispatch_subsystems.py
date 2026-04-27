"""Regression tests for the ``dispatch_subsystems`` primitive — the
deterministic phase-3 fan-out that bypasses the orchestrator LLM's
weak multi-tool-call output.

The original symptom: vLLM logs showed ``Running: 1 reqs, Waiting: 0``
even when the architecture had 4+ subsystems. RCA confirmed the
weak orchestrator LLM (qwen3.6-35b on local vLLM) could not emit
multiple ``dispatch_task`` tool_calls in one inference, so the N
subsystems became N serial dispatches. Fix: build a primitive that
needs only ONE tool call from the LLM (``dispatch_subsystems(phase=…)``)
and runs the per-subsystem fan-out deterministically in Python from
``docs/stack_contract.json``.

This file exercises:

1. The primitive is registered in the orchestrator toolset.
2. Without ``docs/stack_contract.json`` it returns a ``failed`` result
   pointing the orchestrator to dispatch architect.
3. With a valid contract it dispatches one developer per subsystem in
   parallel — measured via timestamps that overlap, not march
   serially.
4. ``max_concurrent_subsystem_dispatches`` actually throttles the
   ThreadPoolExecutor: with cap=2, no more than 2 dispatches can be
   in-flight at the same time even when there are 5 subsystems.
5. Each subsystem's task_description (built by
   ``_build_subsystem_task_description``) carries the correct
   per-language toolchain row + components list — so the developer
   that receives it can do real per-component TDD without the
   orchestrator having drafted any of it.
"""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from aise.runtime.models import AgentState
from aise.runtime.runtime_config import RuntimeConfig
from aise.runtime.tool_primitives import (
    _LANGUAGE_TOOLCHAIN,
    ToolContext,
    WorkflowState,
    _build_component_implementation_task,
    _build_subsystem_skeleton_task,
    _build_subsystem_task_description,
    _interface_module_path,
    build_orchestrator_tools,
)


def _build_ctx(
    root: Path,
    *,
    handle_message_side_effect=None,
    max_concurrent: int | None = None,
) -> ToolContext:
    """Build a ToolContext whose ``developer`` runtime is a MagicMock
    with a controllable ``handle_message`` side effect (for timing
    tests). The developer dispatch and parallel fan-out logic is real;
    only the LLM call is mocked out.
    """
    fake_rt = MagicMock()
    fake_rt._state = AgentState.ACTIVE
    fake_rt.handle_message.side_effect = handle_message_side_effect or (lambda *a, **kw: "ok")
    fake_rt.definition.role = "developer"
    fake_rt.definition.metadata = {}

    manager = MagicMock()
    manager.runtimes = {"developer": fake_rt}
    manager.get_runtime = lambda n: fake_rt if n == "developer" else None

    cfg = RuntimeConfig()
    if max_concurrent is not None:
        cfg.safety_limits.max_concurrent_subsystem_dispatches = max_concurrent

    return ToolContext(
        manager=manager,
        project_root=root,
        config=cfg,
        workflow_state=WorkflowState(),
    )


def _write_contract(root: Path, payload: dict) -> Path:
    docs = root / "docs"
    docs.mkdir(exist_ok=True)
    p = docs / "stack_contract.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


def _valid_contract(n_subsystems: int = 4) -> dict:
    """Build a contract with N subsystems, each with 2 components."""
    subsystems = []
    for i in range(n_subsystems):
        sname = f"sub{i}"
        subsystems.append({
            "name": sname,
            "src_dir": f"src/{sname}/",
            "responsibilities": f"{sname} responsibilities",
            "components": [
                {"name": f"comp_a_{i}", "file": f"src/{sname}/comp_a_{i}.py", "responsibility": "A"},
                {"name": f"comp_b_{i}", "file": f"src/{sname}/comp_b_{i}.py", "responsibility": "B"},
            ],
        })
    return {
        "language": "python",
        "test_runner": "pytest",
        "static_analyzer": ["ruff", "mypy"],
        "subsystems": subsystems,
    }


# ---------------------------------------------------------------------------
# 1. Primitive registration
# ---------------------------------------------------------------------------


class TestDispatchSubsystemsPrimitiveExists:
    def test_registered_in_orchestrator_toolset(self, tmp_path):
        ctx = _build_ctx(tmp_path)
        tools = build_orchestrator_tools(ctx)
        names = {t.name for t in tools}
        assert "dispatch_subsystems" in names


# ---------------------------------------------------------------------------
# 2. Missing-contract behaviour
# ---------------------------------------------------------------------------


class TestDispatchSubsystemsContractRequired:
    def test_missing_contract_returns_failed_with_actionable_error(self, tmp_path):
        ctx = _build_ctx(tmp_path)  # no docs/stack_contract.json
        tools = build_orchestrator_tools(ctx)
        ds = next(t for t in tools if t.name == "dispatch_subsystems")
        result = json.loads(ds.invoke({"phase": "implementation"}))
        assert result["status"] == "failed"
        # Error should point the orchestrator at architect — not
        # leave it guessing.
        assert "architect" in result["error"].lower()

    def test_legacy_modules_only_contract_is_rejected(self, tmp_path):
        # An old-style flat modules[] contract is no longer accepted
        # by dispatch_subsystems — architect must produce the new
        # subsystems[].components[] schema before phase 3 can fan out.
        _write_contract(tmp_path, {
            "language": "python",
            "modules": [{"name": "x", "src_dir": "src/x/"}],
        })
        ctx = _build_ctx(tmp_path)
        tools = build_orchestrator_tools(ctx)
        ds = next(t for t in tools if t.name == "dispatch_subsystems")
        result = json.loads(ds.invoke({"phase": "implementation"}))
        assert result["status"] == "failed"
        assert "subsystems" in result["error"].lower()


# ---------------------------------------------------------------------------
# 3. Real parallel fan-out
# ---------------------------------------------------------------------------


class TestDispatchSubsystemsRunsInParallel:
    def test_skeleton_stage_dispatched_concurrently(self, tmp_path):
        """4 subsystems with default cap (4 concurrent) should all
        START their *skeleton* dispatches before any FINISHES.

        We measure stage 1 specifically by sleeping longer than the
        per-thread overhead. ``dispatch_task`` retries empty /
        artifact-missing dispatches once with context (see
        ``_MAX_DISPATCH_RETRIES``), so a worker thread may invoke
        ``handle_message`` more than once per dispatch — we record
        the FIRST start time per thread to measure initial fan-out.
        """
        _write_contract(tmp_path, _valid_contract(n_subsystems=4))

        first_start_per_thread: dict[int, float] = {}
        finish_times: list[float] = []
        lock = threading.Lock()

        def slow_handle(*args, **kwargs):
            tid = threading.get_ident()
            t0 = time.monotonic()
            with lock:
                first_start_per_thread.setdefault(tid, t0)
            time.sleep(0.3)
            t1 = time.monotonic()
            with lock:
                finish_times.append(t1)
            return "ok"

        ctx = _build_ctx(tmp_path, handle_message_side_effect=slow_handle, max_concurrent=4)
        tools = build_orchestrator_tools(ctx)
        ds = next(t for t in tools if t.name == "dispatch_subsystems")
        ds.invoke({"phase": "implementation"})

        # At least 4 distinct worker threads ran the skeleton stage in
        # parallel (additional threads from stage 2's component fan-out
        # may push this higher; what we assert is real fan-out).
        assert len(first_start_per_thread) >= 4, (
            f"expected ≥4 distinct worker threads (one per subsystem skeleton), "
            f"got {len(first_start_per_thread)}"
        )
        # The 4 EARLIEST starts must all happen before the first finish —
        # that's the skeleton stage proving real concurrency.
        starts = sorted(first_start_per_thread.values())[:4]
        first_finish = min(finish_times)
        for s in starts:
            assert s <= first_finish, (
                f"dispatch started at {s} after the first finish at {first_finish} — "
                "indicates serial execution, not parallel"
            )

    def test_per_subsystem_skeleton_before_components(self, tmp_path):
        """Within EACH subsystem, the skeleton dispatch must finish
        before that subsystem's component dispatches begin — otherwise
        a component would race ahead of its own skeleton's interface
        module. Cross-subsystem ordering is intentionally NOT enforced:
        a fast subsystem may already be deep into components while a
        slow sibling is still scaffolding.
        """
        _write_contract(tmp_path, _valid_contract(n_subsystems=2))

        # Each dispatch records (subsystem, phase, start, end) by
        # parsing the prompt — stage-1 prompts include the subsystem
        # name in "## Subsystem skeleton task: <name>" and stage-2
        # prompts include "## Component implementation task: <sub>.<comp>".
        events: list[tuple[str, str, float, float]] = []
        lock = threading.Lock()

        def phase_aware_handle(prompt, **_kwargs):
            t0 = time.monotonic()
            time.sleep(0.05)
            t1 = time.monotonic()
            if "Subsystem skeleton task: " in prompt:
                phase = "skeleton"
                sub = prompt.split("Subsystem skeleton task: ", 1)[1].split("\n", 1)[0].strip()
            elif "Component implementation task: " in prompt:
                phase = "component"
                token = prompt.split("Component implementation task: ", 1)[1].split("\n", 1)[0].strip()
                sub = token.split(".", 1)[0]
            else:
                phase, sub = "unknown", "?"
            with lock:
                events.append((sub, phase, t0, t1))
            return "ok"

        ctx = _build_ctx(tmp_path, handle_message_side_effect=phase_aware_handle, max_concurrent=4)
        tools = build_orchestrator_tools(ctx)
        ds = next(t for t in tools if t.name == "dispatch_subsystems")
        ds.invoke({"phase": "implementation"})

        # For each subsystem: every skeleton END (incl. retries) must
        # be ≤ every component START in the SAME subsystem.
        subsystems_seen = {sub for sub, _, _, _ in events if sub != "?"}
        assert subsystems_seen == {"sub0", "sub1"}, subsystems_seen
        for sub in subsystems_seen:
            skel = [(t0, t1) for s, p, t0, t1 in events if s == sub and p == "skeleton"]
            comp = [(t0, t1) for s, p, t0, t1 in events if s == sub and p == "component"]
            assert skel, f"{sub}: no skeleton dispatch observed"
            assert comp, f"{sub}: no component dispatch observed"
            last_skel_end = max(t1 for _, t1 in skel)
            first_comp_start = min(t0 for t0, _ in comp)
            assert last_skel_end <= first_comp_start, (
                f"{sub}: skeleton ended at {last_skel_end} but component started at "
                f"{first_comp_start} — per-subsystem ordering broken"
            )

    def test_subsystems_overlap_each_other(self, tmp_path):
        """Subsystems run fully in parallel — a slow subsystem's
        skeleton must NOT block a sibling subsystem's components.
        Concretely: at some point during the run, sub0's components
        and sub1's skeleton (or vice versa) overlap in time.
        """
        _write_contract(tmp_path, _valid_contract(n_subsystems=2))

        events: list[tuple[str, str, float, float]] = []
        lock = threading.Lock()

        def phase_aware_handle(prompt, **_kwargs):
            t0 = time.monotonic()
            time.sleep(0.1)
            t1 = time.monotonic()
            if "Subsystem skeleton task: " in prompt:
                phase = "skeleton"
                sub = prompt.split("Subsystem skeleton task: ", 1)[1].split("\n", 1)[0].strip()
            elif "Component implementation task: " in prompt:
                phase = "component"
                token = prompt.split("Component implementation task: ", 1)[1].split("\n", 1)[0].strip()
                sub = token.split(".", 1)[0]
            else:
                phase, sub = "unknown", "?"
            with lock:
                events.append((sub, phase, t0, t1))
            return "ok"

        ctx = _build_ctx(tmp_path, handle_message_side_effect=phase_aware_handle, max_concurrent=4)
        tools = build_orchestrator_tools(ctx)
        ds = next(t for t in tools if t.name == "dispatch_subsystems")
        ds.invoke({"phase": "implementation"})

        # Find any cross-subsystem time overlap. If subsystems were
        # globally serialized into "all skeletons → all components",
        # sub1's skeleton would start AFTER sub0's skeleton finishes,
        # but sub0's COMPONENTS would only start AFTER all skeletons.
        # Under the new design, sub0's components can overlap sub1's
        # skeleton (the slow sibling).
        def _overlaps(a, b):
            return a[2] < b[3] and b[2] < a[3]

        sub0_events = [e for e in events if e[0] == "sub0"]
        sub1_events = [e for e in events if e[0] == "sub1"]
        assert any(
            _overlaps(a, b) for a in sub0_events for b in sub1_events
        ), (
            "no time overlap between sub0 and sub1 dispatches — "
            "subsystems are not running in parallel"
        )

    def test_results_aggregate_includes_per_subsystem_status(self, tmp_path):
        _write_contract(tmp_path, _valid_contract(n_subsystems=3))
        ctx = _build_ctx(tmp_path, max_concurrent=4)
        tools = build_orchestrator_tools(ctx)
        ds = next(t for t in tools if t.name == "dispatch_subsystems")
        out = json.loads(ds.invoke({"phase": "implementation"}))
        # 3 subsystems × 2 components each = 3 skeleton + 6 component
        # dispatches under the new two-stage flow.
        assert out["subsystems_dispatched"] == 3
        assert out["components_dispatched"] == 6
        assert out["skeleton_completed"] + out["skeleton_failed"] == 3
        assert out["components_completed"] + out["components_failed"] == 6
        assert out["completed"] + out["failed"] == 9
        # Skeleton results map back to subsystems; component results
        # map to (subsystem, component) pairs so the LLM can pinpoint
        # which slot fell over.
        skel_names = {r["subsystem"] for r in out["skeleton_results"]}
        assert skel_names == {"sub0", "sub1", "sub2"}
        comp_pairs = {(r["subsystem"], r["component"]) for r in out["results"]}
        expected_pairs = {(f"sub{i}", f"comp_{ab}_{i}") for i in range(3) for ab in ("a", "b")}
        assert comp_pairs == expected_pairs


# ---------------------------------------------------------------------------
# 4. Throttling
# ---------------------------------------------------------------------------


class TestMaxConcurrentDispatchesCap:
    def test_cap_limits_simultaneous_dispatches(self, tmp_path):
        """With max_concurrent_subsystem_dispatches=2 and 5 subsystems,
        the in-flight count must NEVER exceed 2 at any sampled
        moment — even though the full execution still completes all 5.
        Without the cap a single architect with 24 subsystems would
        flood the LLM serving layer.
        """
        _write_contract(tmp_path, _valid_contract(n_subsystems=5))

        in_flight = 0
        peak_in_flight = 0
        lock = threading.Lock()

        def tracked_handle(*args, **kwargs):
            nonlocal in_flight, peak_in_flight
            with lock:
                in_flight += 1
                peak_in_flight = max(peak_in_flight, in_flight)
            time.sleep(0.15)
            with lock:
                in_flight -= 1
            return "ok"

        ctx = _build_ctx(tmp_path, handle_message_side_effect=tracked_handle, max_concurrent=2)
        tools = build_orchestrator_tools(ctx)
        ds = next(t for t in tools if t.name == "dispatch_subsystems")
        out = json.loads(ds.invoke({"phase": "implementation"}))

        # 5 skeleton dispatches + 5×2 = 10 component dispatches = 15 total.
        assert out["subsystems_dispatched"] == 5
        assert out["components_dispatched"] == 10
        assert peak_in_flight <= 2, (
            f"peak concurrent dispatches was {peak_in_flight}, "
            f"exceeded cap of 2 — throttle is broken"
        )
        assert peak_in_flight >= 2, (
            f"peak concurrent dispatches was {peak_in_flight}, "
            f"never reached cap of 2 — throttle may be over-restrictive "
            f"or the test is degenerate"
        )

    def test_cap_of_one_serializes(self, tmp_path):
        _write_contract(tmp_path, _valid_contract(n_subsystems=3))

        in_flight = 0
        peak = 0
        lock = threading.Lock()

        def tracked_handle(*args, **kwargs):
            nonlocal in_flight, peak
            with lock:
                in_flight += 1
                peak = max(peak, in_flight)
            time.sleep(0.05)
            with lock:
                in_flight -= 1
            return "ok"

        ctx = _build_ctx(tmp_path, handle_message_side_effect=tracked_handle, max_concurrent=1)
        tools = build_orchestrator_tools(ctx)
        ds = next(t for t in tools if t.name == "dispatch_subsystems")
        ds.invoke({"phase": "implementation"})
        assert peak == 1


# ---------------------------------------------------------------------------
# 5. Deterministic per-subsystem task description
# ---------------------------------------------------------------------------


class TestSubsystemTaskDescriptionDeterministic:
    def test_python_task_includes_component_paths_and_test_command(self):
        contract = {
            "language": "python", "test_runner": "pytest",
            "static_analyzer": ["ruff", "mypy"],
        }
        ss = {
            "name": "ui", "src_dir": "src/ui/", "responsibilities": "render",
            "components": [
                {"name": "menu", "file": "src/ui/menu.py", "responsibility": "main menu"},
                {"name": "hud", "file": "src/ui/hud.py", "responsibility": "in-game HUD"},
            ],
        }
        text = _build_subsystem_task_description(ss, contract, phase="implementation")
        # Subsystem identity
        assert "## Subsystem implementation task: ui" in text
        assert "src/ui/" in text
        # Each component appears with source + test paths derived
        # deterministically from the language pattern.
        assert "src/ui/menu.py" in text
        assert "src/ui/hud.py" in text
        assert "tests/ui/test_menu.py" in text
        assert "tests/ui/test_hud.py" in text
        # Toolchain commands rendered
        assert "python -m pytest" in text
        assert "ruff check" in text
        assert "mypy" in text
        # Anti-cross-contamination instruction so parallel sibling
        # subsystems don't stomp on each other
        assert "Do NOT touch source files outside src/ui/" in text

    def test_typescript_task_uses_vitest_and_ts_paths(self):
        contract = {
            "language": "typescript", "test_runner": "vitest",
            "static_analyzer": ["eslint", "tsc --noEmit"],
        }
        ss = {
            "name": "engine", "src_dir": "src/engine/", "responsibilities": "x",
            "components": [
                {"name": "loop", "file": "src/engine/loop.ts", "responsibility": "y"},
            ],
        }
        text = _build_subsystem_task_description(ss, contract, phase="implementation")
        assert "src/engine/loop.ts" in text
        assert "tests/engine/loop.test.ts" in text
        assert "npx vitest run" in text
        # No Python defaults leaked in
        assert "pytest" not in text
        assert ".py" not in text

    def test_go_and_rust_paths(self):
        for lang, src_pat, test_pat, cmd in (
            ("go", "internal/x/comp.go", "internal/x/comp_test.go", "go test"),
            ("rust", "src/x/comp.rs", "tests/x/comp.rs", "cargo test"),
        ):
            contract = {"language": lang, "test_runner": cmd, "static_analyzer": []}
            ss = {
                "name": "x", "src_dir": src_pat.rsplit("/", 1)[0] + "/",
                "responsibilities": "x",
                "components": [
                    {"name": "comp", "file": src_pat, "responsibility": "y"},
                ],
            }
            text = _build_subsystem_task_description(ss, contract, phase="implementation")
            assert src_pat in text
            assert test_pat in text
            assert cmd in text

    def test_unknown_language_falls_back_to_python_toolchain(self):
        # Unknown / future languages don't crash the renderer; they
        # fall back to the Python row so the developer at least gets
        # SOME guidance instead of an empty task. (The architect
        # should still prefer one of the canonical languages.)
        contract = {"language": "haskell"}
        ss = {
            "name": "x", "src_dir": "src/x/",
            "responsibilities": "x",
            "components": [{"name": "c", "file": "src/x/c.hs", "responsibility": "y"}],
        }
        text = _build_subsystem_task_description(ss, contract, phase="implementation")
        assert "## Subsystem implementation task: x" in text
        # Falls back to python toolchain — better than crashing
        assert "src/x/c.hs" in text


# ---------------------------------------------------------------------------
# 6. Toolchain table coverage
# ---------------------------------------------------------------------------


class TestLanguageToolchainCoverage:
    def test_mainstream_languages_present(self):
        for lang in ("python", "typescript", "javascript", "go", "rust", "java"):
            assert lang in _LANGUAGE_TOOLCHAIN, (
                f"mainstream language {lang!r} missing from "
                f"_LANGUAGE_TOOLCHAIN — every Phase-3 fan-out for that "
                f"language would fall back to Python defaults"
            )

    def test_each_row_has_required_keys(self):
        for lang, row in _LANGUAGE_TOOLCHAIN.items():
            for key in ("test_cmd", "test_path_pattern", "src_path_pattern", "static_check"):
                assert key in row, f"{lang!r} toolchain missing {key!r}"


# ---------------------------------------------------------------------------
# 7. Two-stage helpers (skeleton + per-component)
# ---------------------------------------------------------------------------


class TestSubsystemSkeletonTask:
    """Stage-1 skeleton task: scaffolds module files + interface module
    WITHOUT implementing logic or writing tests. Keeps the dispatch
    budget per subsystem bounded so the recursion limit doesn't bite
    even on subsystems with many components.
    """

    def test_python_skeleton_lists_components_and_interface(self):
        contract = {"language": "python"}
        ss = {
            "name": "ui", "src_dir": "src/ui/", "responsibilities": "render",
            "components": [
                {"name": "menu", "file": "src/ui/menu.py", "responsibility": "main menu"},
                {"name": "hud", "file": "src/ui/hud.py", "responsibility": "in-game HUD"},
            ],
        }
        text = _build_subsystem_skeleton_task(ss, contract, phase="implementation")
        assert "## Subsystem skeleton task: ui" in text
        # Each component's file listed for skeleton creation
        assert "src/ui/menu.py" in text
        assert "src/ui/hud.py" in text
        # Interface module is named explicitly so the worker writes it
        assert "src/ui/__init__.py" in text
        # Skeleton phase MUST forbid logic/tests so stage 2 owns those
        assert "NO logic" in text or "no logic" in text.lower()
        assert "NO tests" in text or "no tests" in text.lower()

    def test_typescript_skeleton_uses_index_ts(self):
        contract = {"language": "typescript"}
        ss = {
            "name": "engine", "src_dir": "src/engine/",
            "components": [{"name": "loop", "file": "src/engine/loop.ts", "responsibility": "tick"}],
        }
        text = _build_subsystem_skeleton_task(ss, contract, phase="implementation")
        assert "src/engine/index.ts" in text
        # No Python convention leaked into a TS skeleton
        assert "__init__.py" not in text


class TestComponentImplementationTask:
    """Stage-2 per-component task: a single component owns one source
    + one test file, against the skeleton's frozen public API.
    """

    def test_component_task_scopes_to_single_pair(self):
        contract = {
            "language": "python", "test_runner": "pytest",
            "static_analyzer": ["ruff", "mypy"],
        }
        ss = {"name": "ui", "src_dir": "src/ui/"}
        comp = {"name": "menu", "file": "src/ui/menu.py", "responsibility": "main menu"}
        text = _build_component_implementation_task(ss, comp, contract, phase="implementation")
        assert "## Component implementation task: ui.menu" in text
        assert "src/ui/menu.py" in text
        assert "tests/ui/test_menu.py" in text
        assert "src/ui/__init__.py" in text  # interface module reference
        assert "python -m pytest tests/ui/test_menu.py" in text
        assert "ruff check src/ui/menu.py" in text
        # Anti-cross-contamination so siblings don't race
        assert "DO NOT modify any source file other than" in text


class TestInterfaceModulePath:
    def test_python_default_is_init_py(self):
        assert _interface_module_path("python", "ui", "src/ui/") == "src/ui/__init__.py"

    def test_typescript_default_is_index_ts(self):
        assert _interface_module_path("typescript", "engine", "src/engine") == "src/engine/index.ts"

    def test_unknown_language_falls_back_to_init_py(self):
        # Worker still has a meaningful interface filename; the
        # architect ought to pick a canonical language anyway.
        assert _interface_module_path("haskell", "x", "src/x").endswith("__init__.py")
