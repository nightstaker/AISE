"""DEPRECATED: reliability primitives (circuit breaker, retry, timeout, wrapper).

This module is not wired into any production code path in `src/aise/`.
Only test modules (`tests/test_reliability/`, `tests/test_e2e/`) import from
it in isolation; no runtime, agent, skill, session, orchestrator, web, or
CLI entry point consumes it. See `DEPRECATED.md` in this directory for
details and migration notes.
"""

from __future__ import annotations

import warnings

warnings.warn(
    "aise.reliability is deprecated: it is not used by any production code path "
    "and is retained only for isolated tests. Do not add new usages.",
    DeprecationWarning,
    stacklevel=2,
)
