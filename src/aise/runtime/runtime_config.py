"""Runtime-level configuration: safety caps, orchestrator selection, shell policy.

Separate from :class:`aise.config.ProjectConfig` (which deals with model/provider
selection). This module owns the *operational* policy that the runtime needs:

- How many task dispatches may a single project make?
- How many continuation passes will the orchestrator be given?
- Which shell commands are agents allowed to run?
- Which agent role is the orchestrator?

All of these used to be magic constants buried in
``project_session.py``/``manager.py``. They now live here, with clear
defaults that can be overridden either programmatically or by a
``ProcessDefinition.caps`` block on a per-project basis.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .models import ProcessCaps

# -- Safety limits ----------------------------------------------------------


# Defaults preserve the prior in-code constants so behavior is unchanged
# until a project explicitly overrides them.
DEFAULT_MAX_DISPATCHES = 30
DEFAULT_MAX_CONTINUATIONS = 15
DEFAULT_PER_PHASE_TIMEOUT_SECONDS = 600


@dataclass
class SafetyLimits:
    """Hard caps that protect against runaway orchestration."""

    max_dispatches: int = DEFAULT_MAX_DISPATCHES
    max_continuations: int = DEFAULT_MAX_CONTINUATIONS
    per_phase_timeout_seconds: int = DEFAULT_PER_PHASE_TIMEOUT_SECONDS

    def overlay(self, caps: ProcessCaps | None) -> SafetyLimits:
        """Return a new SafetyLimits with non-None ``caps`` fields applied."""
        if caps is None:
            return self
        return SafetyLimits(
            max_dispatches=caps.max_dispatches if caps.max_dispatches is not None else self.max_dispatches,
            max_continuations=(
                caps.max_continuations if caps.max_continuations is not None else self.max_continuations
            ),
            per_phase_timeout_seconds=(
                caps.per_phase_timeout_seconds
                if caps.per_phase_timeout_seconds is not None
                else self.per_phase_timeout_seconds
            ),
        )


# -- Shell policy ----------------------------------------------------------


# Conservative default allowlist. Anything not on the list is rejected by
# the ``execute_shell`` primitive. Override at construction time.
DEFAULT_SHELL_ALLOWLIST: tuple[str, ...] = (
    # Interpreters / runners
    "python",
    "python3",
    "pytest",
    "node",
    "npm",
    "npx",
    "go",
    "cargo",
    # Static analyzers used by the ``code_inspection`` skill.
    # Python: ruff (lint) + mypy (types). JS/TS: eslint + tsc.
    # Go: go vet + gofmt. Rust: clippy runs via ``cargo clippy``.
    "ruff",
    "mypy",
    "pyright",
    "eslint",
    "tsc",
    "gofmt",
    # Mermaid CLI used by the ``mermaid`` skill to validate diagrams.
    "mmdc",
    # Filesystem / text utilities used for collecting metrics and
    # inspecting outputs.
    "ls",
    "cat",
    "head",
    "tail",
    "grep",
    "wc",
    "find",
    # Version control. The runtime auto-initializes each project as
    # its own git repo and commits after every successful dispatch
    # (see the ``git`` skill). Agents may read repo state (status,
    # log, diff) via execute_shell but should leave commits to the
    # runtime.
    "git",
)

DEFAULT_SHELL_TIMEOUT_SECONDS = 120


@dataclass
class ShellConfig:
    """Policy for the ``execute_shell`` tool primitive."""

    allowlist: tuple[str, ...] = DEFAULT_SHELL_ALLOWLIST
    timeout_seconds: int = DEFAULT_SHELL_TIMEOUT_SECONDS

    # Shell builtins that are safe to ignore when checking the allowlist.
    _SHELL_BUILTINS = frozenset(
        {
            "cd",
            "export",
            "set",
            "unset",
            "source",
            ".",
            "env",
            "echo",
            "pwd",
        }
    )

    def is_allowed(self, command: str) -> bool:
        """True when all real executables in ``command`` are in the allowlist.

        Splits by shell operators (``&&``, ``||``, ``|``, ``;``), then
        checks the first token of each sub-command. Shell builtins like
        ``cd`` are skipped. This allows commands like
        ``cd /path && pytest tests/ -q --tb=short``.
        """
        import re

        if not command or not command.strip():
            return False
        # Split by shell operators into sub-commands
        parts = re.split(r"\s*(?:&&|\|\||[|;])\s*", command.strip())
        found_disallowed = False
        for part in parts:
            tokens = part.strip().split()
            if not tokens:
                continue
            first = tokens[0].rsplit("/", 1)[-1]  # strip leading path
            if first in self._SHELL_BUILTINS:
                continue  # skip cd, export, etc.
            if first not in self.allowlist:
                found_disallowed = True
                break
        return not found_disallowed


# -- LLM defaults ----------------------------------------------------------


# Floor for max_tokens. Many tool-calling workflows need lots of headroom
# for tool arguments + responses; a 4 KB ceiling causes silent truncation.
# Reasoning-capable models (qwen3.x et al.) emit a hidden ``<think>…</think>``
# block whose tokens count against this budget but are stripped from the
# visible content. Observed on project_3-snake (2026-04-19): the architect
# burned 16384 completion tokens in the think block for a "produce complete
# architecture blueprint" dispatch, leaving zero budget for the
# ``write_file`` tool call that would have actually created the document.
# A 64 KB floor gives room for both the reasoning chain and the composed
# output on large-artifact tasks.
DEFAULT_MIN_MAX_TOKENS = 65536


@dataclass
class LLMDefaults:
    """Provider-agnostic defaults applied when building an LLM client."""

    min_max_tokens: int = DEFAULT_MIN_MAX_TOKENS
    max_retries: int = 1


# -- RuntimeConfig ---------------------------------------------------------


@dataclass
class RuntimeConfig:
    """All runtime-level policy in one place.

    The ``orchestrator_role`` field selects which agent acts as the
    orchestrator: any AgentDefinition whose ``role`` matches will be
    treated as eligible. Falling back on a name match keeps existing
    project_manager.md working without an immediate edit.

    The ``trace_subdir`` field is the relative directory under each
    project root where the runtime writes its own per-call JSON
    traces. It is operational infrastructure, not workflow logic.
    """

    safety_limits: SafetyLimits = field(default_factory=SafetyLimits)
    shell: ShellConfig = field(default_factory=ShellConfig)
    llm: LLMDefaults = field(default_factory=LLMDefaults)
    orchestrator_role: str = "orchestrator"
    orchestrator_fallback_name: str = "project_manager"
    trace_subdir: str = "runs/trace"

    def with_process_caps(self, caps: ProcessCaps | None) -> RuntimeConfig:
        """Return a new RuntimeConfig with the process caps applied."""
        return RuntimeConfig(
            safety_limits=self.safety_limits.overlay(caps),
            shell=self.shell,
            llm=self.llm,
            orchestrator_role=self.orchestrator_role,
            orchestrator_fallback_name=self.orchestrator_fallback_name,
            trace_subdir=self.trace_subdir,
        )
