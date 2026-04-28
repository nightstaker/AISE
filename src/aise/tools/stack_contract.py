"""Stack-contract loading + UI/framework recipes used by dispatch tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Tech-stack contract that the architect writes in Phase 2 and that
# every downstream worker dispatch must respect. Worker prompts get
# this block prepended so the orchestrator LLM cannot translate the
# language / framework / test runner into something else.
#
# Two structural fields beyond the simple stack identifiers:
#   - ``subsystems`` (NEW SCHEMA, preferred) — a list of dicts with
#     ``name`` / ``src_dir`` / ``responsibilities`` /
#     ``components[]``. Each subsystem is one ``src/<name>/`` directory;
#     each component is a file inside it. This is the layout the
#     architect must produce going forward.
#   - ``modules`` (LEGACY) — a flat list of module dicts with
#     ``name`` / ``src_dir``. Emitted by the old prompt that
#     conflated "subsystem" and "component" levels. Loader still
#     accepts it (with a deprecation marker in the rendered block)
#     so any in-flight projects from before the schema upgrade keep
#     dispatching cleanly.
_STACK_CONTRACT_KEYS = (
    "language",
    "runtime",
    "framework_backend",
    "framework_frontend",
    "package_manager",
    "project_config_file",
    "test_runner",
    "static_analyzer",
    "entry_point",
    "run_command",
    "ui_required",
    "ui_kind",
)


def _render_subsystems_summary(subsystems: list[Any]) -> str:
    """Render the ``subsystems`` list as a one-line-per-subsystem
    summary suitable for worker prompts. Components are shown as a
    count, not enumerated — keeping the contract block short. A
    well-formed entry is ``{"name": str, "components": [...]}``;
    malformed entries fall back to a placeholder line so the block
    is always parseable downstream.
    """
    parts = []
    for ss in subsystems:
        if not isinstance(ss, dict):
            parts.append("  - <invalid subsystem entry>")
            continue
        name = ss.get("name", "?")
        src_dir = ss.get("src_dir", "")
        components = ss.get("components", []) or []
        n = len(components) if isinstance(components, list) else 0
        suffix = f" ({n} component{'s' if n != 1 else ''})" if n else ""
        path_suffix = f" [{src_dir}]" if src_dir else ""
        parts.append(f"  - {name}{path_suffix}{suffix}")
    return "\n".join(parts) if parts else "  (no subsystems declared)"


def _load_stack_contract_data(project_root: Path | None) -> dict[str, Any] | None:
    """Read and parse ``docs/stack_contract.json`` from the project
    root. Returns ``None`` when the file is missing, malformed, or not
    a JSON object. Used by ``dispatch_subsystems`` to discover the
    fan-out targets without going through the orchestrator LLM.
    """
    if project_root is None:
        return None
    contract_path = project_root / "docs" / "stack_contract.json"
    if not contract_path.is_file():
        return None
    try:
        data = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    return data


# Per-language test-runner / static-analyzer rows. Used by
# ``dispatch_subsystems`` to build a deterministic developer task
# description from the architect's stack contract — no LLM
# decision-making in the loop.
_LANGUAGE_TOOLCHAIN: dict[str, dict[str, str]] = {
    "python": {
        "test_cmd": "python -m pytest {test_path} -q --tb=short",
        "test_path_pattern": "tests/{subsystem}/test_{component}.py",
        "src_path_pattern": "src/{subsystem}/{component}.py",
        "static_check": "ruff check {src_path} && mypy {src_path}",
    },
    "typescript": {
        "test_cmd": "npx vitest run {test_path}",
        "test_path_pattern": "tests/{subsystem}/{component}.test.ts",
        "src_path_pattern": "src/{subsystem}/{component}.ts",
        "static_check": "eslint {src_path} && npx tsc --noEmit",
    },
    "javascript": {
        "test_cmd": "npx vitest run {test_path}",
        "test_path_pattern": "tests/{subsystem}/{component}.test.js",
        "src_path_pattern": "src/{subsystem}/{component}.js",
        "static_check": "eslint {src_path}",
    },
    "go": {
        "test_cmd": "go test ./internal/{subsystem}/...",
        "test_path_pattern": "internal/{subsystem}/{component}_test.go",
        "src_path_pattern": "internal/{subsystem}/{component}.go",
        "static_check": "go vet ./internal/{subsystem}/... && gofmt -l {src_path}",
    },
    "rust": {
        "test_cmd": "cargo test --test {component}",
        "test_path_pattern": "tests/{subsystem}/{component}.rs",
        "src_path_pattern": "src/{subsystem}/{component}.rs",
        "static_check": "cargo clippy -- -D warnings && cargo check",
    },
    "java": {
        "test_cmd": "mvn test -Dtest={Component}Test",
        "test_path_pattern": "src/test/java/{subsystem}/{Component}Test.java",
        "src_path_pattern": "src/main/java/{subsystem}/{Component}.java",
        "static_check": "mvn -q compile",
    },
}


# Per-language convention for the "subsystem interface module" — the
# file the skeleton phase writes so sibling subsystems and downstream
# component dispatches have a single, stable place to import the
# subsystem's public API from. Keeping this language-keyed avoids
# Python-isms leaking into TS/Go/Rust skeleton tasks.
_INTERFACE_FILENAME: dict[str, str] = {
    "python": "__init__.py",
    "py": "__init__.py",
    "typescript": "index.ts",
    "ts": "index.ts",
    "javascript": "index.js",
    "js": "index.js",
    "go": "doc.go",
    "rust": "mod.rs",
    "java": "package-info.java",
}


def _interface_module_path(language: str, subsystem_name: str, src_dir: str) -> str:
    """Return the conventional public-API module path for ``subsystem``.

    The skeleton phase writes this file so component dispatches and
    sibling subsystems can ``import`` against a single declared API
    surface instead of fishing through individual component files.
    """
    base = (src_dir or f"src/{subsystem_name}").rstrip("/")
    fname = _INTERFACE_FILENAME.get(language.lower(), "__init__.py")
    return f"{base}/{fname}"


# Heuristics that classify a subsystem as ``ui`` so the skeleton phase
# can wire the framework runtime instead of emitting pure stubs.
_UI_SUBSYSTEM_NAME_HINTS: tuple[str, ...] = ("ui", "view", "render", "frontend", "screen", "gui")
_UI_RESPONSIBILITY_HINTS: tuple[str, ...] = (
    "ui",
    "界面",
    "渲染",
    "rendering",
    "render",
    "screen",
    "view",
    "hud",
    "menu",
    "dialog",
)


def _is_ui_subsystem(subsystem: dict[str, Any], contract: dict[str, Any]) -> bool:
    """True when this subsystem owns the project's UI runtime.

    Used by the skeleton phase to switch from "stub bodies only" to
    "wire the framework runtime so component dispatches can fill in
    real rendering logic instead of building mock state recorders".

    A subsystem qualifies if either:
    - its ``src_dir`` contains a UI hint (``ui``, ``view``, ``render``...);
    - its ``responsibilities`` text contains a UI hint (handles
      Chinese keywords ``界面`` / ``渲染`` for projects whose contract
      mirrors the user's natural language).
    AND the architecture's ``ui_required`` flag is true. ``ui_kind`` /
    ``framework_frontend`` only matter for *which* runtime to wire, not
    for whether to wire one.
    """
    if not bool(contract.get("ui_required")):
        return False
    name = (subsystem.get("name") or "").lower()
    src_dir = (subsystem.get("src_dir") or "").lower()
    responsibilities = (subsystem.get("responsibilities") or "").lower()
    if any(hint in name or hint in src_dir for hint in _UI_SUBSYSTEM_NAME_HINTS):
        return True
    return any(hint in responsibilities for hint in _UI_RESPONSIBILITY_HINTS)


# Per-framework "what minimal runtime must boot" recipe used by the
# UI-skeleton branch. The shape stays stable so we can grow the table
# without touching the prompt builder. Each row encodes:
#
# - ``import``: imports the skeleton must add at module top.
# - ``runtime_setup``: the lines needed to initialise the framework's
#   display / app object inside the skeleton's bootstrap component.
# - ``main_loop_hint``: brief description of the main loop the skeleton
#   must wire, so the worker writes a real loop instead of the
#   ``_running=True; _running=False`` no-op observed on project_0.
# - ``surface_type``: the type that flows to per-component renderers
#   (``pygame.Surface``, ``QPainter``, ``Canvas``, etc.). Component
#   methods must accept this type so component dispatches in stage 2
#   are forced to call real framework APIs.
_UI_FRAMEWORK_RECIPES: dict[str, dict[str, str]] = {
    "pygame": {
        "import": "import pygame",
        "runtime_setup": (
            "pygame.init()\n"
            "screen = pygame.display.set_mode((800, 600))\n"
            "pygame.display.set_caption(<project title>)\n"
            "clock = pygame.time.Clock()"
        ),
        "main_loop_hint": (
            "while self._running:\n"
            "    for event in pygame.event.get():\n"
            "        if event.type == pygame.QUIT: self._running = False\n"
            "        # dispatch event to subsystems\n"
            "    # update game state, render to screen, pygame.display.flip()\n"
            "    clock.tick(60)\n"
            "pygame.quit()"
        ),
        "surface_type": "pygame.Surface",
    },
    "qt": {
        "import": "from PySide6.QtWidgets import QApplication, QMainWindow",
        "runtime_setup": "app = QApplication(sys.argv)\nwindow = QMainWindow()\nwindow.show()",
        "main_loop_hint": "sys.exit(app.exec())",
        "surface_type": "QPainter",
    },
    "tk": {
        "import": "import tkinter as tk",
        "runtime_setup": "root = tk.Tk()\nroot.title(<project title>)\nroot.geometry('800x600')",
        "main_loop_hint": "root.mainloop()",
        "surface_type": "tk.Canvas",
    },
    "arcade": {
        "import": "import arcade",
        "runtime_setup": "window = arcade.Window(800, 600, <title>)",
        "main_loop_hint": "arcade.run()",
        "surface_type": "arcade.Window",
    },
    "fastapi": {
        "import": "from fastapi import FastAPI",
        "runtime_setup": "app = FastAPI()",
        "main_loop_hint": "uvicorn.run(app, host='0.0.0.0', port=8000)",
        "surface_type": "fastapi.Request",
    },
    "flask": {
        "import": "from flask import Flask",
        "runtime_setup": "app = Flask(__name__)",
        "main_loop_hint": "app.run(host='0.0.0.0', port=5000)",
        "surface_type": "flask.Request",
    },
}


def _ui_framework_recipe(contract: dict[str, Any]) -> dict[str, str] | None:
    """Pick the framework recipe for this contract, or ``None`` when
    the architect declared a UI but no recipe is registered for the
    chosen framework — the skeleton task then falls back to a generic
    "wire the runtime declared in framework_frontend / ui_kind"
    instruction so the worker still produces real binding code.
    """
    candidates = [
        str(contract.get("framework_frontend") or "").lower().strip(),
        str(contract.get("ui_kind") or "").lower().strip(),
    ]
    for cand in candidates:
        if cand and cand in _UI_FRAMEWORK_RECIPES:
            return _UI_FRAMEWORK_RECIPES[cand]
    return None


def _load_stack_contract_block(project_root: Path | None) -> str:
    """Read ``docs/stack_contract.json`` and render it as a fenced
    block to prepend to worker prompts. Returns an empty string if
    the file is missing or malformed (compatible with older projects
    that never produced one).

    Supports both the new ``subsystems[]`` schema (preferred) and
    the legacy ``modules[]`` schema (rendered with a deprecation
    marker so the orchestrator can flag it for re-architecting).
    """
    if project_root is None:
        return ""
    contract_path = project_root / "docs" / "stack_contract.json"
    if not contract_path.is_file():
        return ""
    try:
        data = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    lines = [
        "=== STACK CONTRACT (architect-defined, FOLLOW EXACTLY — do NOT translate to another language/framework) ===",
    ]
    for key in _STACK_CONTRACT_KEYS:
        if key not in data:
            continue
        value = data[key]
        if isinstance(value, list):
            value = ", ".join(str(v) for v in value)
        lines.append(f"{key}: {value}")
    # Subsystem layout — prefer the new two-level schema; fall back
    # to the legacy flat schema with a clearly-marked deprecation
    # note so anyone reading the worker prompt sees it should be
    # re-architected.
    subsystems = data.get("subsystems")
    legacy_modules = data.get("modules")
    if isinstance(subsystems, list) and subsystems:
        lines.append("subsystems:")
        lines.append(_render_subsystems_summary(subsystems))
    elif isinstance(legacy_modules, list) and legacy_modules:
        lines.append(
            "subsystems: (LEGACY FLAT 'modules' SCHEMA — should be "
            "re-architected into nested subsystems[].components[])"
        )
        for mod in legacy_modules:
            if isinstance(mod, dict):
                name = mod.get("name", "?")
                src_dir = mod.get("src_dir", "")
                lines.append(f"  - {name} [{src_dir}]")
            else:
                lines.append("  - <invalid module entry>")
    lines.append("=== END STACK CONTRACT ===")
    return "\n".join(lines)
