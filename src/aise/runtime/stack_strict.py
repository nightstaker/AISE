"""Strict (raise-on-unknown) accessors for the language tables.

Replaces the silent ``.get(lang, _LANGUAGE_TOOLCHAIN["python"])`` Python
fallback that was responsible for the project_1-tower regression where
a Unity (csharp) project was treated as Python — see the long
docstrings in ``aise.tools.stack_contract`` for the historical
debris.

This module is deliberately separate from ``aise.tools.stack_contract``
(which is in legacy use by the dispatch_subsystems flow that c4 will
remove) so callers migrating to the new PhaseExecutor pipeline can
``from aise.runtime.stack_strict import get_toolchain`` without
reaching back into the legacy module's silent-fallback world.

Surface
-------
* get_toolchain(language) → dict — raises UnsupportedLanguageError
  if the table has no row for that language.
* get_interface_filename(language, subsystem_name, src_dir) → str
  Returns the per-language barrel file path. ``""`` for
  csharp/kotlin/swift/cs (those have no per-folder barrel) — caller
  uses the empty string to skip the artifact.
* get_test_extension(language) → str — raises UnsupportedLanguageError.
* registered_languages() → list[str]

The actual table data is sourced once from the legacy module to keep
a single source of truth — adding a language only requires editing
``_LANGUAGE_TOOLCHAIN`` / ``_INTERFACE_FILENAME``. Each strict accessor
just wraps the lookup with a "raise instead of fallback" semantic.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


# Load the language tables directly from their source files. Going
# through ``from ..tools.stack_contract import ...`` would trigger
# the pre-existing project_session ↔ tools.context circular import
# (orthogonal to c12; will be untangled in a separate cleanup).
def _load_module_from_file(name: str, rel_path: str):
    here = Path(__file__).resolve().parent.parent  # …/src/aise/
    spec = importlib.util.spec_from_file_location(name, here / rel_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"could not load {name} from {rel_path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_stack_contract_mod = _load_module_from_file(
    "_c12_stack_contract", "tools/stack_contract.py"
)
_LANGUAGE_TOOLCHAIN: dict[str, dict[str, str]] = _stack_contract_mod._LANGUAGE_TOOLCHAIN
_INTERFACE_FILENAME: dict[str, str] = _stack_contract_mod._INTERFACE_FILENAME
_interface_module_path = _stack_contract_mod._interface_module_path

# safety_net is package-importable cleanly (no circular import through
# project_session), so a normal import works for scenario_gate.
from ..safety_net.scenario_gate import _LANGUAGE_TEST_EXT  # noqa: E402

# csharp/kotlin/swift use empty string in _INTERFACE_FILENAME ("" means
# "no barrel file convention"). Exclude them from the "must be in
# _INTERFACE_FILENAME" supported set since their entry is the empty
# sentinel, not a real filename.
_LANGUAGES_WITHOUT_BARREL: frozenset[str] = frozenset(
    {"csharp", "cs", "kotlin", "swift"}
)


class UnsupportedLanguageError(ValueError):
    """Raised when a language is not in the toolchain / extension table.

    Carries ``.language`` and ``.table`` for callers that want to format
    a structured error to the LLM."""

    def __init__(self, language: str, table: str, registered: list[str]) -> None:
        self.language = language
        self.table = table
        self.registered = registered
        super().__init__(
            f"language={language!r} has no row in {table}. "
            f"Registered: {registered}. Add a row to "
            f"src/aise/tools/stack_contract.py:{table} (or for the "
            "test extension table, "
            "src/aise/safety_net/scenario_gate.py:_LANGUAGE_TEST_EXT) "
            "and a corresponding test in tests/test_runtime/."
        )


def _norm(language: str) -> str:
    return (language or "").strip().lower()


def get_toolchain(language: str) -> dict[str, Any]:
    """Strict toolchain row lookup. Raises if language unknown."""
    norm = _norm(language)
    row = _LANGUAGE_TOOLCHAIN.get(norm)
    if row is None:
        raise UnsupportedLanguageError(
            norm, "_LANGUAGE_TOOLCHAIN", sorted(_LANGUAGE_TOOLCHAIN.keys())
        )
    return row


def get_interface_filename(language: str, subsystem_name: str, src_dir: str) -> str:
    """Strict barrel-file path lookup. Returns the project-relative
    path or ``""`` for languages with no per-folder barrel.

    Raises UnsupportedLanguageError when the language is not in
    _INTERFACE_FILENAME at all (registers as a typo). For the
    no-barrel sentinel languages (csharp/cs/kotlin/swift) returns
    ``""`` deliberately — caller should treat that as "skip this
    deliverable entry".
    """
    norm = _norm(language)
    if norm not in _INTERFACE_FILENAME:
        raise UnsupportedLanguageError(
            norm, "_INTERFACE_FILENAME", sorted(_INTERFACE_FILENAME.keys())
        )
    return _interface_module_path(norm, subsystem_name, src_dir)


def get_test_extension(language: str) -> str:
    """Strict scenario test-file extension lookup."""
    norm = _norm(language)
    ext = _LANGUAGE_TEST_EXT.get(norm)
    if ext is None:
        raise UnsupportedLanguageError(
            norm, "_LANGUAGE_TEST_EXT", sorted(_LANGUAGE_TEST_EXT.keys())
        )
    return ext


def registered_languages() -> list[str]:
    """Union of languages declared across all 3 tables."""
    return sorted(
        set(_LANGUAGE_TOOLCHAIN)
        | set(_INTERFACE_FILENAME)
        | set(_LANGUAGE_TEST_EXT)
    )


def language_has_no_barrel(language: str) -> bool:
    """True for csharp/cs/kotlin/swift — languages where per-folder
    barrel files are not idiomatic and the AUTO_GATE should skip the
    interface_filename deliverable entry."""
    return _norm(language) in _LANGUAGES_WITHOUT_BARREL
