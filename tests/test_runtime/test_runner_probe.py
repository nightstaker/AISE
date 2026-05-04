"""Tests for runner_probe (commit c10)."""

from __future__ import annotations

import pytest

from aise.runtime.runner_probe import (
    ProbeResult,
    RunnerStatus,
    clear_probe_cache,
    degraded_mode_for,
    probe_runner,
)


@pytest.fixture(autouse=True)
def _reset_cache():
    clear_probe_cache()
    yield
    clear_probe_cache()


# -- probe_runner --------------------------------------------------------


class TestProbeRunner:
    def test_unknown_when_no_contract(self):
        r = probe_runner(None)
        assert r.status == RunnerStatus.UNKNOWN

    def test_unknown_when_contract_has_no_test_cmd_or_runner(self):
        r = probe_runner({"language": "python"})
        assert r.status == RunnerStatus.UNKNOWN

    def test_extracts_first_token_from_test_cmd(self):
        r = probe_runner({"test_cmd": "definitely_not_a_real_binary_xyz --foo bar"})
        assert r.status == RunnerStatus.UNAVAILABLE
        assert r.binary == "definitely_not_a_real_binary_xyz"

    def test_falls_back_to_test_runner_when_no_test_cmd(self):
        r = probe_runner({"test_runner": "definitely_not_a_real_binary_xyz"})
        assert r.status == RunnerStatus.UNAVAILABLE
        assert r.binary == "definitely_not_a_real_binary_xyz"

    def test_ok_for_real_binary_on_path(self):
        # `python3` is guaranteed to exist on this CI venv
        r = probe_runner({"test_cmd": "python3 -m pytest"})
        assert r.status == RunnerStatus.OK
        assert r.binary == "python3"
        assert "Python" in r.detail or "python" in r.detail.lower()

    def test_unavailable_for_missing_binary(self):
        r = probe_runner({"test_cmd": "this_binary_does_not_exist_42"})
        assert r.status == RunnerStatus.UNAVAILABLE
        assert r.binary == "this_binary_does_not_exist_42"
        assert "not on PATH" in r.detail


# -- Caching --------------------------------------------------------------


class TestCaching:
    def test_cached_result_returned(self):
        r1 = probe_runner({"language": "python", "test_cmd": "python3"})
        r2 = probe_runner({"language": "python", "test_cmd": "python3"})
        assert r1 is r2  # exact same object from cache

    def test_clear_cache_forces_re_probe(self):
        r1 = probe_runner({"language": "python", "test_cmd": "python3"})
        clear_probe_cache()
        r2 = probe_runner({"language": "python", "test_cmd": "python3"})
        assert r1 is not r2  # fresh probe ⇒ new object


# -- degraded_mode_for ---------------------------------------------------


class TestDegradedModeFor:
    def test_none_or_empty_or_fail_returns_fail(self):
        for mode in (None, "", "fail"):
            assert degraded_mode_for(mode) == "fail"

    def test_write_only_passes_through(self):
        assert degraded_mode_for("write_only") == "write_only"

    def test_skip_passes_through(self):
        assert degraded_mode_for("skip") == "skip"

    def test_unknown_mode_falls_back_to_fail(self):
        assert degraded_mode_for("yolo_mode") == "fail"


# -- ProbeResult ---------------------------------------------------------


class TestProbeResult:
    def test_is_ok_helper(self):
        assert ProbeResult(status=RunnerStatus.OK).is_ok
        assert not ProbeResult(status=RunnerStatus.UNAVAILABLE).is_ok
        assert not ProbeResult(status=RunnerStatus.UNKNOWN).is_ok
