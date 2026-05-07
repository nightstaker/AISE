"""Stack profile registry — language/framework-agnostic abstraction for
the integration probe.

Each profile declares:

* ``matches`` — heuristics for auto-detecting the profile from a project
  root (presence of marker files like ``package.json`` + ``vite.config.*``)
* ``runtime_kind`` — ``cli`` | ``server`` | ``web`` | ``library``
* ``boot_cmd`` — command template for spawning the runtime, with
  placeholders ``{entry_point}``, ``{port}`` substituted at probe time
* ``observe`` — how to capture an observable signal (stdio_capture,
  http_get, screenshot_via_browser)
* ``primary_trigger`` — how to fire the architect-declared action's
  ``trigger.kind`` (only the cli + server runtimes have a real
  implementation today; ``web`` is a stub that returns ``skipped``)

The profiles are pure data — no executable code lives here. The probe
runner (``integration_probe.py``) consumes a profile and emits an
``integration_report.json`` fragment.

Detection precedence:
1. Explicit ``stack_contract.profile`` field (architect override)
2. Best-fit auto-detection over all registered profiles
3. ``unknown`` profile fallback (probe writes verdict=skipped)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# -- Profile dataclass ----------------------------------------------------


@dataclass(frozen=True)
class StackProfile:
    """Single source of truth for one (language, runtime_kind) profile.

    All command/template strings allow the placeholders:
      - ``{entry_point}`` — stack_contract.entry_point
      - ``{run_command}`` — stack_contract.run_command (preferred when set)
      - ``{port}`` — runtime-allocated free port for the probe

    The probe runner does literal ``str.format`` substitution; missing
    placeholders raise KeyError with a descriptive message rather than
    silently producing a malformed command.
    """

    name: str
    runtime_kind: str  # cli | server | web | library | unknown
    detect_required_files: tuple[str, ...] = ()
    detect_optional_indicators: tuple[str, ...] = ()
    detect_languages: tuple[str, ...] = ()
    boot_cmd: tuple[str, ...] = ()
    observe: str = "none"  # stdio_capture | http_get | screenshot | none
    observe_arg: str = ""  # e.g. URL path for http_get
    boot_timeout_s: int = 10
    primary_trigger: dict[str, Any] = field(default_factory=dict)
    invariant_emitter: dict[str, str] = field(default_factory=dict)
    notes: str = ""

    def detection_score(self, project_root: Path, language: str | None) -> int:
        """Return an integer score; higher = better fit. Zero means the
        profile cannot apply. The runner picks the highest-scoring
        profile across the registry; ties broken by registration order.
        """
        score = 0
        for req in self.detect_required_files:
            if not (project_root / req).is_file():
                return 0  # required file absent → disqualified
            score += 5
        for opt in self.detect_optional_indicators:
            # Optional indicators may include glob wildcards.
            if any(project_root.glob(opt)):
                score += 2
        if language and self.detect_languages:
            if language.lower() in tuple(s.lower() for s in self.detect_languages):
                score += 3
        return score


# -- Registry -------------------------------------------------------------


_PROFILES: list[StackProfile] = []


def register_profile(profile: StackProfile) -> StackProfile:
    """Register a profile. Idempotent on re-registration of the same name."""
    for i, existing in enumerate(_PROFILES):
        if existing.name == profile.name:
            _PROFILES[i] = profile
            return profile
    _PROFILES.append(profile)
    return profile


def all_profiles() -> tuple[StackProfile, ...]:
    return tuple(_PROFILES)


def profile_by_name(name: str) -> StackProfile | None:
    for p in _PROFILES:
        if p.name == name:
            return p
    return None


# -- Built-in profiles ----------------------------------------------------


# Web TS / Vite. Real boot would need a headless browser; we declare the
# command but mark observe=screenshot so the probe runner knows to
# delegate to a browser harness (currently a stub returning skipped).
_WEB_TYPESCRIPT = StackProfile(
    name="web_typescript",
    runtime_kind="web",
    detect_required_files=("package.json",),
    detect_optional_indicators=(
        "tsconfig.json",
        "vite.config.*",
        "vitest.config.*",
        "webpack.config.*",
    ),
    detect_languages=("typescript", "javascript"),
    boot_cmd=("npx", "vite", "preview", "--port", "{port}"),
    observe="screenshot",
    observe_arg="http://127.0.0.1:{port}/",
    boot_timeout_s=15,
    primary_trigger={
        "key": "key_press",  # browser-key-press emit
        "click": "browser_click",
    },
    invariant_emitter={
        "collection_non_empty": ("if (!({expr} && {expr}.length > 0)) throw new Error('data invariant: {name}');"),
        "map_size_at_least": (
            "if (Object.keys({expr} || {{}}).length < {min}) throw new Error('data invariant: {name}');"
        ),
        "string_non_empty": "if (!{expr}) throw new Error('data invariant: {name}');",
    },
    notes=(
        "Real web boot probe requires a headless browser. The probe runner "
        "currently writes verdict=skipped for runtime_kind=web; static gates "
        "(data_dependency_wiring_static, action_contract_wiring_static) still "
        "enforce assembly correctness."
    ),
)


# Generic CLI. Works for python (`python -m src.main`), go binary, node CLI,
# any process that accepts stdin, writes stdout, exits cleanly. Truly
# language-neutral — driven by stack_contract.run_command.
_GENERIC_CLI = StackProfile(
    name="cli",
    runtime_kind="cli",
    detect_required_files=(),
    detect_optional_indicators=(
        "pyproject.toml",
        "go.mod",
        "Cargo.toml",
        "src/main.py",
        "src/main.go",
        "src/main.rs",
    ),
    detect_languages=("python", "go", "rust", "node", "javascript"),
    boot_cmd=("sh", "-c", "{run_command}"),
    observe="stdio_capture",
    observe_arg="",
    boot_timeout_s=10,
    primary_trigger={
        "stdin": "stdin_write",
        "key": "stdin_write",  # CLIs treat key→stdin
    },
    invariant_emitter={
        # Language-specific generators are emitted by the stack profile
        # only when the architect requests runtime invariants; the static
        # gates do not need them. Strings here are pseudo-code that the
        # developer prompt expands into the host language.
        "collection_non_empty": "assert len({expr}) > 0, 'data invariant: {name}'",
        "map_size_at_least": "assert len({expr}) >= {min}, 'data invariant: {name}'",
        "string_non_empty": "assert {expr}, 'data invariant: {name}'",
    },
    notes="Generic CLI probe: spawn run_command, capture stdout, optional stdin trigger.",
)


# Generic HTTP server. Probe spawns the run_command, polls a known
# endpoint until it responds 2xx (or boot_timeout_s), then optionally
# fires primary_trigger as an HTTP request and re-observes.
_GENERIC_SERVER = StackProfile(
    name="server",
    runtime_kind="server",
    detect_required_files=(),
    detect_optional_indicators=(
        "fastapi.toml",
        "src/main.py",
        "main.go",
        "src/server.ts",
        "src/server.js",
    ),
    detect_languages=("python", "go", "node", "javascript", "typescript"),
    boot_cmd=("sh", "-c", "{run_command}"),
    observe="http_get",
    observe_arg="http://127.0.0.1:{port}/",
    boot_timeout_s=15,
    primary_trigger={
        "http": "http_request",
    },
    invariant_emitter={
        "collection_non_empty": "assert len({expr}) > 0, 'data invariant: {name}'",
        "map_size_at_least": "assert len({expr}) >= {min}, 'data invariant: {name}'",
        "string_non_empty": "assert {expr}, 'data invariant: {name}'",
    },
    notes="Generic server probe: spawn run_command, http_get the root, parse status.",
)


_UNKNOWN = StackProfile(
    name="unknown",
    runtime_kind="unknown",
    detect_required_files=(),
    detect_optional_indicators=(),
    detect_languages=(),
    boot_cmd=(),
    observe="none",
    boot_timeout_s=0,
    primary_trigger={},
    invariant_emitter={},
    notes=(
        "Fallback profile when no other profile matches. The probe runner "
        "writes integration_report.boot_check.verdict='skipped' with "
        "reason='no_matching_profile'. Static gates still enforce assembly."
    ),
)


# Register in priority order. ``select_profile`` picks the highest-scoring
# match; ``_UNKNOWN`` always scores 0 so it only wins when no other does.
register_profile(_WEB_TYPESCRIPT)
register_profile(_GENERIC_CLI)
register_profile(_GENERIC_SERVER)
register_profile(_UNKNOWN)


# -- Selection -----------------------------------------------------------


def select_profile(
    project_root: Path,
    stack_contract: dict[str, Any] | None,
) -> StackProfile:
    """Pick the best-fitting profile.

    Selection rules:
    1. ``stack_contract.profile`` (string field) — exact-match override.
    2. Highest-scoring built-in via ``StackProfile.detection_score``.
    3. ``unknown`` profile when nothing scores > 0.

    The unknown profile is functionally a no-op; the integration probe
    short-circuits to ``verdict=skipped`` for it.
    """
    sc = stack_contract or {}
    explicit = sc.get("profile")
    if isinstance(explicit, str) and explicit:
        named = profile_by_name(explicit)
        if named is not None:
            return named
    language = sc.get("language") if isinstance(sc.get("language"), str) else None
    best: tuple[int, StackProfile] | None = None
    for p in _PROFILES:
        if p.name == "unknown":
            continue
        score = p.detection_score(project_root, language)
        if score <= 0:
            continue
        if best is None or score > best[0]:
            best = (score, p)
    if best is not None:
        return best[1]
    return profile_by_name("unknown") or _UNKNOWN
