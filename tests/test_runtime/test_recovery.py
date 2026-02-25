from __future__ import annotations

import pytest

from aise.runtime.recovery import RecoveryManager, RetryPolicy


def test_recovery_manager_retries_then_succeeds(monkeypatch) -> None:
    monkeypatch.setattr("aise.runtime.recovery.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("aise.runtime.recovery.random.uniform", lambda *_args, **_kwargs: 0.0)
    attempts = {"n": 0}
    retried = []

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("boom")
        return "ok"

    mgr = RecoveryManager(RetryPolicy(max_attempts=3, base_delay_sec=0, jitter_sec=0))
    out = mgr.run_with_retry(flaky, on_retry=lambda attempt, exc: retried.append((attempt, str(exc))))
    assert out == "ok"
    assert attempts["n"] == 3
    assert retried == [(1, "boom"), (2, "boom")]


def test_recovery_manager_raises_after_max_attempts(monkeypatch) -> None:
    monkeypatch.setattr("aise.runtime.recovery.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("aise.runtime.recovery.random.uniform", lambda *_args, **_kwargs: 0.0)
    mgr = RecoveryManager(RetryPolicy(max_attempts=2, base_delay_sec=0, jitter_sec=0))
    with pytest.raises(RuntimeError):
        mgr.run_with_retry(lambda: (_ for _ in ()).throw(RuntimeError("nope")))
