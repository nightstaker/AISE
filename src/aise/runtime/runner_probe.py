"""Runner-availability probe for verification phase.

The verification phase's prompt asks the developer to "make the test
go red, then fix until green". That assumes the project's
``test_runner`` is actually installed and runnable in the sandbox.
For Unity / xcode / dotnet projects on a stock Linux sandbox, it
isn't — the developer enters a TDD loop that mathematically can't
converge (it can't actually compile or run anything).

This module probes the runner. If unavailable, the verification
phase's fanout uses ``mode_when_runner_unavailable`` from
``waterfall_v2.process.md`` (default ``write_only``) which:
* still requires the developer to write the scenario test files
* relaxes the AUTO_GATE to "file_exists + min_bytes" only (no
  command-success predicate)
* skips the TDD loop entirely

Probe protocol:
1. Extract first token of stack_contract.test_cmd (or test_runner if
   no test_cmd). Examples: ``pytest``, ``dotnet``, ``vitest``,
   ``cargo``.
2. shutil.which() to confirm it's on PATH.
3. Run ``<binary> --version`` (or ``--help`` for some) with 10s
   timeout. Non-zero exit → UNAVAILABLE.
4. Cache result per (stack_contract.language, binary) so repeated
   phases don't re-probe.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Any


class RunnerStatus(str, Enum):
    OK = "ok"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"  # contract has no test_cmd / test_runner declared


@dataclass(frozen=True)
class ProbeResult:
    status: RunnerStatus
    binary: str = ""
    detail: str = ""

    @property
    def is_ok(self) -> bool:
        return self.status == RunnerStatus.OK


# Per-process cache: (lang, binary) -> ProbeResult. Repeated calls in
# the same Python process get the cached answer. Tests should pass
# fresh contracts to avoid pollution; production processes probe each
# stack at most once.
_PROBE_CACHE: dict[tuple[str, str], ProbeResult] = {}


# Per-binary version-flag heuristic. Most CLIs accept --version; a
# few (e.g. some old Java tools) only respond to -version. This map
# is intentionally tiny — the default is --version.
_VERSION_FLAGS: dict[str, str] = {
    "java": "-version",
    "javac": "-version",
}


def probe_runner(stack_contract: dict[str, Any] | None) -> ProbeResult:
    """Probe the test runner declared in stack_contract.

    Returns ProbeResult.UNKNOWN when the contract is None / empty or
    has no test_cmd/test_runner.
    """
    if not stack_contract:
        return ProbeResult(status=RunnerStatus.UNKNOWN, detail="no stack_contract")
    binary = _extract_binary(stack_contract)
    if not binary:
        return ProbeResult(
            status=RunnerStatus.UNKNOWN,
            detail="stack_contract has no test_cmd or test_runner",
        )
    lang = (stack_contract.get("language") or "").lower()
    cache_key = (lang, binary)
    if cache_key in _PROBE_CACHE:
        return _PROBE_CACHE[cache_key]
    result = _probe_uncached(binary)
    _PROBE_CACHE[cache_key] = result
    return result


def clear_probe_cache() -> None:
    """For tests: reset the per-process cache."""
    _PROBE_CACHE.clear()


def _extract_binary(stack_contract: dict[str, Any]) -> str:
    """Pull the first token of test_cmd, falling back to test_runner."""
    test_cmd = (stack_contract.get("test_cmd") or "").strip()
    if test_cmd:
        return test_cmd.split()[0]
    runner = (stack_contract.get("test_runner") or "").strip()
    if runner:
        return runner.split()[0]
    return ""


def _probe_uncached(binary: str) -> ProbeResult:
    if shutil.which(binary) is None:
        return ProbeResult(
            status=RunnerStatus.UNAVAILABLE,
            binary=binary,
            detail=f"{binary!r} not on PATH",
        )
    flag = _VERSION_FLAGS.get(binary, "--version")
    try:
        proc = subprocess.run(  # noqa: S603 — binary is from architect's stack_contract
            [binary, flag],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return ProbeResult(
            status=RunnerStatus.UNAVAILABLE,
            binary=binary,
            detail=f"{binary} {flag} crashed/timeout: {exc}",
        )
    if proc.returncode != 0:
        return ProbeResult(
            status=RunnerStatus.UNAVAILABLE,
            binary=binary,
            detail=f"{binary} {flag} exit={proc.returncode}",
        )
    version_line = (proc.stdout or proc.stderr or "").splitlines()[:1]
    return ProbeResult(
        status=RunnerStatus.OK,
        binary=binary,
        detail=version_line[0] if version_line else f"{binary} OK",
    )


def degraded_mode_for(stage_mode: str | None) -> str:
    """Translate the FanoutStage's mode_when_runner_unavailable into a
    PhaseExecutor-friendly enum value. Acts as a no-op pass-through
    today; kept as an indirection so we can map process.md aliases
    to internal enums later without touching the executor."""
    if stage_mode in (None, "", "fail"):
        return "fail"
    if stage_mode in ("write_only", "skip"):
        return stage_mode
    return "fail"  # unknown mode → safe default: phase fails
