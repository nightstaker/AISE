"""Generate language-idiomatic root config files after implementation.

The orchestrator agents deliberately don't write build boilerplate
(``pyproject.toml`` / ``package.json`` / ``go.mod`` / ``Cargo.toml`` /
``pom.xml``) — the architect spec explicitly forbids it. Generated
projects end up with working source in ``src/`` and a verified entry
point, but no way for a downstream user to ``pip install .`` or
``npm install`` or ``go build``.

This module plugs the gap deterministically:

1. :func:`detect_dominant_language` counts source files under
   ``src/`` and picks the language with the most hits.
2. :func:`generate_root_config` writes a minimal but valid config
   file for that language to ``project_root`` (one file, no
   dependencies beyond stdlib / language-runtime). The file is only
   written if one doesn't already exist — so retry / incremental
   runs never overwrite user-authored config.

No LLM is involved. The goal is predictability, not completeness: the
generated config is always syntactically valid and always small enough
that a human can extend it by hand.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class _LangSpec:
    """Detection + generation rules for a single language."""

    key: str  # canonical language id, e.g. ``python``
    extensions: tuple[str, ...]  # source extensions to count
    config_filename: str  # filename to write into project_root
    # Signals that the project ALREADY has a hand-authored config file
    # we should never touch. Extra belt-and-braces on top of the
    # existing-path check (users sometimes have alternative filenames).
    other_config_filenames: tuple[str, ...] = ()


_LANGUAGES: tuple[_LangSpec, ...] = (
    _LangSpec(
        key="python",
        extensions=(".py",),
        config_filename="pyproject.toml",
        other_config_filenames=("setup.py", "setup.cfg", "Pipfile"),
    ),
    _LangSpec(
        key="typescript",
        extensions=(".ts", ".tsx"),
        config_filename="package.json",
        other_config_filenames=("yarn.lock", "pnpm-lock.yaml"),
    ),
    _LangSpec(
        key="javascript",
        extensions=(".js", ".jsx", ".mjs", ".cjs"),
        config_filename="package.json",
        other_config_filenames=("yarn.lock", "pnpm-lock.yaml"),
    ),
    _LangSpec(
        key="go",
        extensions=(".go",),
        config_filename="go.mod",
    ),
    _LangSpec(
        key="rust",
        extensions=(".rs",),
        config_filename="Cargo.toml",
    ),
    _LangSpec(
        key="java",
        extensions=(".java",),
        config_filename="pom.xml",
        other_config_filenames=("build.gradle", "build.gradle.kts"),
    ),
)


# Minimum file count for a language to qualify as "dominant". Avoids
# writing a go.mod because a single-file fixture happens to end in
# ``.go`` while the real project is Python.
_MIN_SOURCE_FILES = 1


def detect_dominant_language(src_dir: Path) -> str | None:
    """Return the language id with the most source files under ``src_dir``.

    Returns ``None`` when the directory is missing, empty, or has no
    files matching a known extension. The caller is expected to treat
    ``None`` as "skip config generation" rather than as an error.

    When two languages tie (e.g. 3 ``.ts`` files + 3 ``.py`` files),
    the first one in :data:`_LANGUAGES` wins. The order was picked so
    the most common project type (Python) comes first.
    """
    if not src_dir or not src_dir.is_dir():
        return None
    counts: dict[str, int] = {}
    # Walk once, bucketing every file by extension.
    for entry in src_dir.rglob("*"):
        if not entry.is_file():
            continue
        suffix = entry.suffix.lower()
        if not suffix:
            continue
        for spec in _LANGUAGES:
            if suffix in spec.extensions:
                counts[spec.key] = counts.get(spec.key, 0) + 1
                break
    if not counts:
        return None
    # Tie-break by _LANGUAGES order (stable, deterministic).
    best_key: str | None = None
    best_count = 0
    for spec in _LANGUAGES:
        c = counts.get(spec.key, 0)
        if c > best_count and c >= _MIN_SOURCE_FILES:
            best_count = c
            best_key = spec.key
    return best_key


def generate_root_config(
    project_root: Path,
    *,
    language: str | None = None,
    project_name: str = "",
    run_command: str = "",
) -> dict[str, object]:
    """Write a language-idiomatic config file to ``project_root``.

    Args:
        project_root: Absolute path to the project directory.
        language: Optional override. If ``None`` (default), the
            function auto-detects from ``project_root / src``.
        project_name: Display / package name. Falls back to the
            directory name when blank.
        run_command: The ``RUN:`` command the developer phase
            extracted, e.g. ``"python src/main.py"``. Used to derive
            entry-point metadata for langs that have one.

    Returns:
        A dict describing what happened:
          - ``{"language": None, "path": None, "skipped": True,
             "reason": "<why>"}`` on a no-op (no source / unknown
             language / existing config), or
          - ``{"language": "<lang>", "path": "<rel-path>",
             "created": True}`` when a new file was written.

    The return value is meant to feed an ``on_event`` sink; callers
    don't have to parse it.
    """
    root = Path(project_root) if project_root else None
    if root is None or not root.is_dir():
        return {"language": None, "path": None, "skipped": True, "reason": "no-project-root"}
    lang = language
    if lang is None:
        lang = detect_dominant_language(root / "src")
    if lang is None:
        return {"language": None, "path": None, "skipped": True, "reason": "no-source-detected"}
    spec = next((s for s in _LANGUAGES if s.key == lang), None)
    if spec is None:
        return {"language": lang, "path": None, "skipped": True, "reason": "unknown-language"}

    target = root / spec.config_filename
    if target.exists():
        # Never overwrite an existing config — retry / incremental
        # runs must be idempotent.
        return {
            "language": lang,
            "path": spec.config_filename,
            "skipped": True,
            "reason": "already-exists",
        }
    for other in spec.other_config_filenames:
        if (root / other).exists():
            return {
                "language": lang,
                "path": other,
                "skipped": True,
                "reason": "alternative-config-exists",
            }

    name = _normalize_name(project_name, fallback=root.name) or "aise-project"
    content = _render_config(spec, name, run_command)
    target.write_text(content, encoding="utf-8")
    return {
        "language": lang,
        "path": spec.config_filename,
        "created": True,
    }


# -- Rendering -------------------------------------------------------------


def _render_config(spec: _LangSpec, name: str, run_command: str) -> str:
    if spec.key == "python":
        return _render_pyproject(name, run_command)
    if spec.key in {"javascript", "typescript"}:
        return _render_package_json(name, run_command, is_typescript=(spec.key == "typescript"))
    if spec.key == "go":
        return _render_go_mod(name)
    if spec.key == "rust":
        return _render_cargo_toml(name)
    if spec.key == "java":
        return _render_pom_xml(name)
    # Defensive fallback — should never fire given the spec list.
    return f"# AISE-generated placeholder for {spec.key}\n"


def _render_pyproject(name: str, run_command: str) -> str:
    entry = _python_entry_point(run_command)
    lines = [
        "# AISE-generated minimal pyproject.toml.",
        "# Extend this file with real dependencies as the project grows.",
        "[build-system]",
        'requires = ["setuptools>=61"]',
        'build-backend = "setuptools.build_meta"',
        "",
        "[project]",
        f'name = "{name}"',
        'version = "0.1.0"',
        'description = "Generated by AISE."',
        'requires-python = ">=3.10"',
        "dependencies = []",
        "",
        "[tool.setuptools.packages.find]",
        'where = ["src"]',
        "",
    ]
    if entry:
        lines.extend(
            [
                "[project.scripts]",
                f'{name} = "{entry}"',
                "",
            ]
        )
    return "\n".join(lines)


def _render_package_json(name: str, run_command: str, *, is_typescript: bool) -> str:
    start = (run_command.strip() or "node src/index.js").strip()
    # ``node src/index.js`` → ``node src/index.js``. For TS projects,
    # leave the command intact; the generated ``scripts.start`` just
    # mirrors whatever the developer decided boots the app.
    payload: dict[str, object] = {
        "name": name,
        "version": "0.1.0",
        "description": "Generated by AISE.",
        "private": True,
        "main": "src/index.ts" if is_typescript else "src/index.js",
        "scripts": {
            "start": start,
            "test": "echo 'no tests configured' && exit 0",
        },
    }
    if is_typescript:
        payload["devDependencies"] = {"typescript": "^5"}
    return json.dumps(payload, indent=2) + "\n"


def _render_go_mod(name: str) -> str:
    module = name.replace(" ", "-").lower() or "aise-project"
    return f"// AISE-generated minimal go.mod.\nmodule {module}\n\ngo 1.22\n"


def _render_cargo_toml(name: str) -> str:
    return "\n".join(
        [
            "# AISE-generated minimal Cargo.toml.",
            "[package]",
            f'name = "{name}"',
            'version = "0.1.0"',
            'edition = "2021"',
            "",
            "[dependencies]",
            "",
        ]
    )


def _render_pom_xml(name: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!-- AISE-generated minimal pom.xml. -->\n"
        '<project xmlns="http://maven.apache.org/POM/4.0.0">\n'
        "    <modelVersion>4.0.0</modelVersion>\n"
        f"    <groupId>local.aise</groupId>\n"
        f"    <artifactId>{name}</artifactId>\n"
        f"    <version>0.1.0</version>\n"
        "    <packaging>jar</packaging>\n"
        "</project>\n"
    )


# -- Helpers ---------------------------------------------------------------


# Package names in the ecosystems we target (PEP 503, npm, Cargo,
# Go) share the same hyphen-lowercase skeleton, so a single normalizer
# is enough. The regex strips anything that's not an ascii letter /
# digit / dash; collapses runs; trims leading/trailing dashes.
_NAME_RE = re.compile(r"[^a-z0-9]+")


def _normalize_name(raw: str, *, fallback: str = "") -> str:
    base = (raw or fallback or "").strip().lower()
    if not base:
        return ""
    cleaned = _NAME_RE.sub("-", base).strip("-")
    return cleaned or ""


# Extracts an importable entry from a shell run command so tools like
# ``pip install .`` followed by ``python -m <entry>`` stay consistent.
# Returns ``""`` when the command doesn't look like a Python launcher.
_PYTHON_FILE_RE = re.compile(r"(?:^|\s)src/([\w/]+)\.py(?:\s|$)")


def _python_entry_point(run_command: str) -> str:
    if not run_command:
        return ""
    match = _PYTHON_FILE_RE.search(run_command)
    if not match:
        return ""
    module_path = match.group(1).replace("/", ".")
    return f"{module_path}:main"
