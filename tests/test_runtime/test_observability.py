"""Tests for observability + abort_task (commit c9)."""

from __future__ import annotations

import threading
import time

import pytest

from aise.runtime.observability import (
    AbortRequested,
    check_abort,
    get_registry,
)


@pytest.fixture(autouse=True)
def _fresh_registry():
    get_registry().clear()
    yield
    get_registry().clear()


# -- Basic registration --------------------------------------------------


class TestRegistration:
    def test_register_then_snapshot(self):
        reg = get_registry()
        reg.register_task("t1", agent="developer", step="impl")
        snap = reg.get_snapshot("t1")
        assert snap is not None
        assert snap.task_id == "t1"
        assert snap.agent == "developer"
        assert snap.step == "impl"
        assert snap.status == "running"
        assert snap.llm_call_count == 0
        assert snap.input_tokens == 0
        assert snap.last_llm_call_seconds_ago is None

    def test_unknown_task_returns_none(self):
        assert get_registry().get_snapshot("ghost") is None


# -- Recording -----------------------------------------------------------


class TestRecording:
    def test_record_llm_call_increments(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev")
        reg.record_llm_call("t1", duration_ms=500, input_tokens=1000, output_tokens=200)
        reg.record_llm_call("t1", duration_ms=300, input_tokens=2000, output_tokens=400)
        snap = reg.get_snapshot("t1")
        assert snap.llm_call_count == 2
        assert snap.input_tokens == 3000
        assert snap.output_tokens == 600
        assert snap.last_llm_call_seconds_ago is not None
        assert snap.last_llm_call_seconds_ago < 1.0

    def test_record_loop_detector_hit(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev")
        reg.record_loop_detector_hit("t1")
        reg.record_loop_detector_hit("t1")
        assert reg.get_snapshot("t1").loop_detector_hits == 2

    def test_record_on_unknown_task_is_noop(self):
        # Should not raise — the dispatch hot path may record on a task
        # that was never registered (defensive)
        get_registry().record_llm_call("ghost", duration_ms=10)
        get_registry().record_loop_detector_hit("ghost")


# -- Status transitions --------------------------------------------------


class TestStatusTransitions:
    def test_mark_completed(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev")
        reg.mark_completed("t1", "completed")
        assert reg.get_snapshot("t1").status == "completed"

    def test_mark_failed(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev")
        reg.mark_completed("t1", "failed")
        assert reg.get_snapshot("t1").status == "failed"

    def test_mark_aborted(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev")
        reg.mark_completed("t1", "aborted")
        assert reg.get_snapshot("t1").status == "aborted"


# -- active_tasks vs all_tasks ------------------------------------------


class TestActiveTasksFilter:
    def test_active_filters_by_running(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev")
        reg.register_task("t2", agent="dev")
        reg.register_task("t3", agent="dev")
        reg.mark_completed("t2", "completed")
        active = reg.active_tasks()
        assert {s.task_id for s in active} == {"t1", "t3"}
        all_t = reg.all_tasks()
        assert {s.task_id for s in all_t} == {"t1", "t2", "t3"}

    def test_active_sorted_newest_first(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev")
        time.sleep(0.01)
        reg.register_task("t2", agent="dev")
        time.sleep(0.01)
        reg.register_task("t3", agent="dev")
        ids = [s.task_id for s in reg.active_tasks()]
        assert ids == ["t3", "t2", "t1"]


# -- Abort surface ------------------------------------------------------


class TestAbort:
    def test_request_abort_marks_flag(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev")
        assert not reg.is_abort_requested("t1")
        assert reg.request_abort("t1") is True
        assert reg.is_abort_requested("t1")

    def test_request_abort_unknown_returns_false(self):
        assert get_registry().request_abort("ghost") is False

    def test_check_abort_raises_when_requested(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev")
        reg.request_abort("t1")
        with pytest.raises(AbortRequested, match="t1"):
            check_abort("t1")

    def test_check_abort_silent_when_not_requested(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev")
        check_abort("t1")  # no raise

    def test_check_abort_silent_when_unknown(self):
        check_abort("never_registered")  # no raise


# -- Snapshot serialization ---------------------------------------------


class TestSnapshotToDict:
    def test_serializes_all_fields(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev", step="x")
        reg.record_llm_call("t1", duration_ms=100, input_tokens=500, output_tokens=50)
        snap = reg.get_snapshot("t1")
        d = snap.to_dict()
        assert d["task_id"] == "t1"
        assert d["agent"] == "dev"
        assert d["step"] == "x"
        assert d["llm_call_count"] == 1
        assert d["input_tokens"] == 500
        assert d["output_tokens"] == 50
        assert d["loop_detector_hits"] == 0
        assert d["status"] == "running"
        assert d["abort_requested"] is False
        assert "elapsed_seconds" in d


# -- Thread safety ------------------------------------------------------


class TestThreadSafety:
    def test_concurrent_records_dont_drop(self):
        reg = get_registry()
        reg.register_task("t1", agent="dev")
        n_threads = 10
        per_thread = 50

        def worker():
            for _ in range(per_thread):
                reg.record_llm_call("t1", duration_ms=1, input_tokens=10, output_tokens=2)

        threads = [threading.Thread(target=worker) for _ in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        snap = reg.get_snapshot("t1")
        assert snap.llm_call_count == n_threads * per_thread
        assert snap.input_tokens == n_threads * per_thread * 10
        assert snap.output_tokens == n_threads * per_thread * 2
