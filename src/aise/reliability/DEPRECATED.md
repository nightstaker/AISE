# DEPRECATED: `aise.reliability`

**Status:** Deprecated — not wired into any production code path.

## Why this directory is marked deprecated

This module ships four reliability primitives:

- `circuit_breaker.py` — `CircuitBreaker`, `CircuitState`
- `retry_policy.py` — `RetryPolicy`, `retry`, `TransientError`
- `timeout_handler.py` — `TimeoutHandler`, `timeout`, `TimeoutError`
- `reliability_wrapper.py` — `ReliabilityWrapper`, `reliability_guard`

None of them are imported by any file under `src/aise/`. They are referenced
only in isolated unit tests under `tests/test_reliability/` and a handful
of assertions in `tests/test_e2e/test_system_integration.py`. No agent,
skill, runtime, session, orchestrator, web endpoint, or CLI entry point
calls into this module.

Verification (from the repo root):

```bash
grep -rn "aise\.reliability\|from \.reliability\|from \.\.reliability" \
     --include="*.py" src/
# (no matches)
```

## What to do instead

- **For new code**: do **not** import from `aise.reliability`. If you
  need timeouts, retries, or circuit-breaking around a call site, use
  whatever pattern the surrounding subsystem already uses (e.g. the
  runtime's own safety-net and trace-callback machinery under
  `aise.runtime`).
- **For existing tests**: the tests here are self-contained and continue
  to exercise the primitives for their own sake; they do not validate any
  production behaviour.

## Removal plan

This directory (and its tests under `tests/test_reliability/`) can be
removed in a future cleanup commit once it is confirmed that no external
consumer depends on the API. Importing any symbol from this package now
emits a `DeprecationWarning`.
