"""Tests for ConcurrentExecutor (commit c6)."""

from __future__ import annotations

import threading
import time

from aise.runtime.concurrent_executor import (
    DagResult,
    StageResult,
    StageSpec,
    Task,
    TaskResult,
    run_dag,
    run_grouped,
    run_parallel,
)


def _ok(t: Task) -> TaskResult:
    return TaskResult(task_id=t.id, passed=True, detail="ok")


def _fail(t: Task) -> TaskResult:
    return TaskResult(task_id=t.id, passed=False, detail="bad")


# -- run_parallel ---------------------------------------------------------


class TestRunParallel:
    def test_empty_returns_empty(self):
        sr = run_parallel([], _ok)
        assert sr.results == ()
        assert not sr.passed  # length-0 stage is NOT pass

    def test_all_pass(self):
        tasks = [Task(id=f"t{i}", payload=i) for i in range(5)]
        sr = run_parallel(tasks, _ok, max_workers=3)
        assert sr.passed
        assert len(sr.results) == 5
        assert tuple(r.task_id for r in sr.results) == ("t0", "t1", "t2", "t3", "t4")

    def test_one_fail_makes_stage_fail(self):
        tasks = [Task(id="a", payload=0), Task(id="b", payload=0), Task(id="c", payload=0)]

        def fn(t):
            return _fail(t) if t.id == "b" else _ok(t)

        sr = run_parallel(tasks, fn)
        assert not sr.passed
        assert tuple(r.task_id for r in sr.failed_results) == ("b",)
        assert tuple(r.task_id for r in sr.passed_results) == ("a", "c")

    def test_does_not_cancel_siblings_on_failure(self):
        """When one task fails fast, siblings should still complete."""
        completed = set()

        def fn(t):
            if t.id == "fast_fail":
                return _fail(t)
            time.sleep(0.05)  # slow but completes
            completed.add(t.id)
            return _ok(t)

        tasks = [Task(id="fast_fail", payload=0)] + [
            Task(id=f"slow_{i}", payload=i) for i in range(4)
        ]
        sr = run_parallel(tasks, fn, max_workers=5)
        assert not sr.passed
        # All 4 slow tasks should have completed
        assert completed == {"slow_0", "slow_1", "slow_2", "slow_3"}

    def test_exception_in_task_fn_becomes_failed_result(self):
        def fn(t):
            raise ValueError("oops")

        sr = run_parallel([Task(id="x", payload=0)], fn)
        assert not sr.passed
        assert sr.results[0].passed is False
        assert "ValueError: oops" in sr.results[0].detail

    def test_actually_runs_in_parallel(self):
        """Sanity: with workers=5, 5 tasks each sleeping 0.1s should
        finish in ~0.1s, not ~0.5s."""
        tasks = [Task(id=f"t{i}", payload=i) for i in range(5)]

        def slow(t):
            time.sleep(0.1)
            return _ok(t)

        start = time.monotonic()
        sr = run_parallel(tasks, slow, max_workers=5)
        elapsed = time.monotonic() - start
        assert sr.passed
        assert elapsed < 0.4, f"expected ~0.1s parallel, got {elapsed:.2f}s"


# -- run_grouped ----------------------------------------------------------


class TestRunGrouped:
    def test_same_group_runs_serially(self):
        order: list[str] = []
        order_lock = threading.Lock()

        def fn(t):
            with order_lock:
                order.append(f"start_{t.id}")
            time.sleep(0.05)
            with order_lock:
                order.append(f"end_{t.id}")
            return _ok(t)

        # 4 tasks all in group "G"
        tasks = [Task(id=f"t{i}", payload="G") for i in range(4)]
        sr = run_grouped(tasks, fn, group_by=lambda p: p, max_workers=4)
        assert sr.passed
        # Same-group tasks must alternate start/end (no overlap)
        for i in range(4):
            start_idx = order.index(f"start_t{i}")
            end_idx = order.index(f"end_t{i}")
            assert end_idx == start_idx + 1, f"task t{i} overlapped within group"

    def test_different_groups_parallel(self):
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fn(t):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return _ok(t)

        tasks = [Task(id=f"t{i}", payload=f"group_{i}") for i in range(4)]
        sr = run_grouped(tasks, fn, group_by=lambda p: p, max_workers=4)
        assert sr.passed
        assert max_active >= 2, f"expected ≥2 concurrent, saw max={max_active}"

    def test_group_failure_does_not_block_other_groups(self):
        def fn(t):
            return _fail(t) if t.payload == "bad" else _ok(t)

        tasks = [
            Task(id="b1", payload="bad"),
            Task(id="g1", payload="good1"),
            Task(id="g2", payload="good2"),
        ]
        sr = run_grouped(tasks, fn, group_by=lambda p: p)
        assert not sr.passed
        assert sr.failed_results[0].task_id == "b1"
        assert {r.task_id for r in sr.passed_results} == {"g1", "g2"}


# -- run_dag --------------------------------------------------------------


class TestRunDag:
    def test_passes_when_all_stages_pass(self):
        s1 = StageSpec(id="s1", tasks=(Task(id="a", payload=0),))
        s2 = StageSpec(
            id="s2",
            tasks=(Task(id="b", payload=0),),
            depends_on="s1",
        )
        result = run_dag([s1, s2], _ok)
        assert isinstance(result, DagResult)
        assert result.passed
        assert result.halted_at_stage is None
        assert tuple(s.stage_id for s in result.stage_results) == ("s1", "s2")

    def test_halts_when_first_stage_fails(self):
        s1 = StageSpec(id="s1", tasks=(Task(id="a", payload=0),))
        s2 = StageSpec(id="s2", tasks=(Task(id="b", payload=0),), depends_on="s1")
        result = run_dag([s1, s2], _fail)
        assert not result.passed
        assert result.halted_at_stage == "s1"
        # Only s1 ran
        assert len(result.stage_results) == 1

    def test_dag_with_grouping(self):
        order: list[str] = []
        lock = threading.Lock()

        def fn(t):
            with lock:
                order.append(t.id)
            return _ok(t)

        s1 = StageSpec(
            id="skeleton",
            tasks=(
                Task(id="ssA", payload="A"),
                Task(id="ssB", payload="B"),
            ),
        )
        s2 = StageSpec(
            id="component",
            tasks=(
                Task(id="cA1", payload="A"),
                Task(id="cA2", payload="A"),
                Task(id="cB1", payload="B"),
            ),
            depends_on="skeleton",
            group_by=lambda p: p,
        )
        result = run_dag([s1, s2], fn)
        assert result.passed
        # skeleton stage tasks must all appear before component stage tasks
        sk_idx = max(order.index("ssA"), order.index("ssB"))
        cp_idx = min(order.index("cA1"), order.index("cA2"), order.index("cB1"))
        assert sk_idx < cp_idx, f"skeleton must complete before component: order={order}"

    def test_empty_stages_list(self):
        result = run_dag([], _ok)
        assert isinstance(result, DagResult)
        assert result.passed  # no stages = vacuously true (no halted_at_stage)
        assert result.stage_results == ()


# -- Type sanity ----------------------------------------------------------


class TestTypes:
    def test_stage_result_passed_false_when_empty(self):
        sr = StageResult(stage_id="x", results=())
        assert not sr.passed

    def test_task_result_defaults(self):
        r = TaskResult(task_id="x", passed=True)
        assert r.detail == ""
        assert r.artifact_paths == ()
        assert r.raw == {}
