"""Generic, role-agnostic tool primitives for orchestrator agents.

This module provides the *primitive* operations the orchestrator can
compose into any workflow described by a process.md file. None of the
tools here know what TDD is, what an "implementation phase" looks like,
or which agent is the "developer" — that knowledge lives entirely in
the data files.

Tool catalog
------------

Discovery:
- ``list_processes()`` — return process metadata
- ``get_process(process_file)`` — return a process definition
- ``list_agents()`` — return non-orchestrator agent cards

Dispatch:
- ``dispatch_task(agent_name, task_description, ...)``
- ``dispatch_tasks_parallel(tasks_json)``

Execution:
- ``execute_shell(command, cwd, timeout)`` — sandboxed shell, allowlist gated

Workflow state:
- ``mark_complete(report)`` — explicit terminal signal

Filesystem writes still use deepagents' built-in ``write_file``, which is
guarded by the agent's :class:`PolicyBackend` (see ``policy_backend.py``).

The :class:`ToolContext` carries everything a primitive needs (the
manager, the project root, the safety limits, the event sink). Each
``make_*`` factory closes over the context and returns LangChain
``BaseTool`` instances ready to register with an AgentRuntime.
"""

from __future__ import annotations

import json
import re
import subprocess
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from ..utils.logging import get_logger
from .runtime_config import RuntimeConfig

logger = get_logger(__name__)


# Minimum byte size an expected artifact must have to be considered
# "produced". Files that exist but contain only a few bytes (e.g. an
# empty Python file, a one-line placeholder) are treated the same as
# missing — the dispatch is re-issued with context.
_MIN_ARTIFACT_BYTES = 64

# Maximum number of context-augmented retries a single ``dispatch_task``
# will issue after an empty response or missing artifacts. One retry is
# enough in practice: if a fresh context-augmented attempt still fails,
# looping further usually burns tokens without recovering.
_MAX_DISPATCH_RETRIES = 1

# Text prepended to the task description on a context-augmented retry.
# Deliberately agent-, tool-, skill-, and file-neutral so it applies
# uniformly to every dispatch. ``{prev}`` is filled with a truncated
# verbatim copy of the previous response (or the literal ``(empty)`` if
# the previous attempt returned nothing). ``{task}`` is the original
# task description.
_RETRY_CONTEXT_TEMPLATE = (
    "[Retry context]\n"
    "A previous attempt at this task ended without producing the\n"
    "expected output. Its last message was:\n"
    "<<<\n"
    "{prev}\n"
    ">>>\n"
    "Continue the task. If the previous attempt described an intended\n"
    "action without performing it, perform it now.\n\n"
    "Original task:\n"
    "{task}"
)

# Max bytes of the previous response to echo into the retry prompt.
# Large responses would inflate the retry prompt without helping the
# model; most useful signal is in the final few hundred characters.
_RETRY_PREV_MAX_BYTES = 500


def _artifact_shortfalls(
    project_root: Path | None,
    expected: list[str] | None,
) -> list[str]:
    """Return the subset of ``expected`` that is missing or too small.

    An artifact counts as "produced" when the file exists under
    ``project_root`` and is at least :data:`_MIN_ARTIFACT_BYTES` long.
    Missing ``project_root`` or an empty ``expected`` list means no
    verification is possible — an empty list is returned.
    """
    if project_root is None or not expected:
        return []
    shortfalls: list[str] = []
    root = project_root.resolve()
    for rel in expected:
        rel_norm = rel.lstrip("/")
        path = (project_root / rel_norm).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            shortfalls.append(rel)
            continue
        if not path.is_file() or path.stat().st_size < _MIN_ARTIFACT_BYTES:
            shortfalls.append(rel)
    return shortfalls


def _build_retry_prompt(original_task: str, previous_response: str) -> str:
    """Compose the context-augmented retry prompt for a dispatch."""
    prev = previous_response.strip()
    if not prev:
        echoed = "(empty)"
    elif len(prev) <= _RETRY_PREV_MAX_BYTES:
        echoed = prev
    else:
        echoed = prev[-_RETRY_PREV_MAX_BYTES:]
    return _RETRY_CONTEXT_TEMPLATE.format(prev=echoed, task=original_task)


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


def _build_subsystem_skeleton_task(
    subsystem: dict[str, Any],
    contract: dict[str, Any],
    phase: str,
) -> str:
    """Render the *stage 1* developer task: scaffold module files and
    inter-module interfaces for one subsystem.

    For domain-only subsystems (data / persistence / rules / ...), the
    skeleton is "stub bodies + public API surface" — stage 2 fills in
    each component via TDD.

    For UI subsystems (`ui_required=True` and a UI-flavoured subsystem
    name / responsibilities), the skeleton additionally wires the
    framework's runtime: imports the framework, initialises its
    display / app object, sets up the main loop, and threads the
    framework's surface / context type through every component method
    signature. This forces stage 2 component dispatches to fill in
    real ``pygame.draw.*`` / ``QPainter.draw*`` / ``app.route(...)``
    calls instead of state-recording mock classes (project_0-tower
    regression).
    """
    name = subsystem.get("name", "?")
    src_dir = subsystem.get("src_dir", "")
    responsibilities = subsystem.get("responsibilities", "")
    components = subsystem.get("components", []) or []
    language = (contract.get("language") or "python").lower()

    component_lines: list[str] = []
    for c in components:
        if not isinstance(c, dict):
            continue
        cname = c.get("name", "?")
        cfile = c.get("file", "")
        cresp = c.get("responsibility", "")
        component_lines.append(f"  - {cname}\n      file: {cfile}\n      responsibility: {cresp}")
    components_block = "\n".join(component_lines) if component_lines else "  (no components declared)"
    interface_path = _interface_module_path(language, name, src_dir)

    is_ui = _is_ui_subsystem(subsystem, contract)

    if not is_ui:
        # Domain / persistence / rules subsystem — keep the original
        # stub-only template.
        return (
            f"## Subsystem skeleton task: {name}\n\n"
            f"Phase: {phase} (stage 1: skeletons + interfaces)\n"
            f"Subsystem directory: {src_dir}\n"
            f"Subsystem responsibility: {responsibilities}\n"
            f"Project language: {language}\n\n"
            f"### Components in this subsystem\n\n"
            f"{components_block}\n\n"
            f"### What to do (skeleton ONLY — NO logic, NO tests)\n\n"
            f"Read ``docs/architecture.md`` first to understand this subsystem's\n"
            f"role and how it talks to siblings. Then:\n\n"
            f"1. Create the subsystem directory ({src_dir}) if it does not\n"
            f"   already exist.\n"
            f"2. For EACH component above, create the source file at the\n"
            f"   listed path with **only**:\n"
            f"     - module-level docstring naming the component and its\n"
            f"       responsibility;\n"
            f"     - public type / class / function declarations with full\n"
            f"       signatures and docstrings (no implementation — bodies\n"
            f"       must be ``pass`` / ``raise NotImplementedError`` /\n"
            f"       language-equivalent stubs);\n"
            f"     - the imports the public API requires.\n"
            f"3. Create / update the subsystem interface module at\n"
            f"   ``{interface_path}`` so sibling subsystems can import this\n"
            f"   subsystem's public API from a single place. Re-export every\n"
            f"   component's public types / classes / functions and add a\n"
            f"   one-paragraph docstring describing the cross-subsystem\n"
            f"   contracts the architecture defines for this module.\n"
            f"4. Do NOT write any test files. Do NOT fill in function bodies.\n"
            f"   The next stage dispatches one task per component to do TDD\n"
            f"   in parallel against the skeletons you produced.\n\n"
            f"Stay strictly inside ``{src_dir}``. Other subsystems' skeletons\n"
            f"are being produced in parallel by sibling dispatches — do not\n"
            f"touch their files.\n"
        )

    # UI-flavoured subsystem — emit a framework-aware skeleton.
    framework_name = (contract.get("framework_frontend") or contract.get("ui_kind") or "").strip() or "(declared)"
    recipe = _ui_framework_recipe(contract)
    if recipe is not None:
        framework_block = (
            f"### Framework runtime wiring (REQUIRED, not optional)\n\n"
            f"This subsystem is the project's UI layer. The skeleton MUST\n"
            f"produce REAL framework binding code — NOT state-recording\n"
            f"mocks. Concretely, ``{framework_name}`` requires:\n\n"
            f"1. **Imports** at the top of the bootstrap file (the\n"
            f"   component whose responsibility says ``main / window /\n"
            f"   renderer / app / engine``, or — if none qualifies — the\n"
            f"   first component listed):\n\n"
            f"   ```\n   {recipe['import']}\n   ```\n\n"
            f"2. **Runtime setup** invoked once at construction. Use this\n"
            f"   exact pattern (adapt window title / dimensions to the\n"
            f"   project; do NOT remove any ``pygame.init`` /\n"
            f"   ``set_mode`` / ``QApplication`` / ``Flask(...)`` line):\n\n"
            f"   ```\n   {recipe['runtime_setup']}\n   ```\n\n"
            f"3. **Main loop / app entry** wired into the bootstrap\n"
            f"   component. The body must enter and stay in the loop —\n"
            f"   ``self._running=True; self._running=False`` is FORBIDDEN.\n"
            f"   Pattern:\n\n"
            f"   ```\n   {recipe['main_loop_hint']}\n   ```\n\n"
            f"4. **Surface / context propagation**: every other component\n"
            f"   in this subsystem (renderers, HUDs, dialog views,\n"
            f"   menus, route handlers, etc.) MUST take a parameter of\n"
            f"   type ``{recipe['surface_type']}`` (or the framework's\n"
            f"   equivalent canvas / request object) on every public\n"
            f"   render / draw / handle method. This is what forces\n"
            f"   stage 2 component dispatches to call real framework\n"
            f"   APIs (``surface.blit``, ``painter.drawText``,\n"
            f"   ``request.json()``, etc.) instead of inventing state\n"
            f"   recorders.\n\n"
        )
    else:
        framework_block = (
            f"### Framework runtime wiring (REQUIRED, not optional)\n\n"
            f"This subsystem is the project's UI layer. ``framework_frontend``\n"
            f"= ``{framework_name}``. The skeleton MUST:\n\n"
            f"1. ``import`` the declared framework at module top.\n"
            f"2. Add a bootstrap component (or, if the architecture\n"
            f"   already named one, use it) whose constructor performs\n"
            f"   the framework's `init / main-window / app-object`\n"
            f"   sequence — concrete API calls, not stubs.\n"
            f"3. Wire a main loop / event-pump / app-entry that actually\n"
            f"   runs (``self._running=True; self._running=False`` is\n"
            f"   FORBIDDEN; the loop must dispatch input events, call\n"
            f"   each component's render/handle methods, and only exit\n"
            f"   on a real quit signal).\n"
            f"4. Thread the framework's surface / context / canvas /\n"
            f"   request type through every other component's public\n"
            f"   methods so stage 2 cannot fake a state recorder.\n\n"
        )

    return (
        f"## Subsystem skeleton task: {name}  (UI subsystem — framework wiring required)\n\n"
        f"Phase: {phase} (stage 1: UI skeletons + framework runtime)\n"
        f"Subsystem directory: {src_dir}\n"
        f"Subsystem responsibility: {responsibilities}\n"
        f"Project language: {language}\n"
        f"UI framework: {framework_name}\n\n"
        f"### Components in this subsystem\n\n"
        f"{components_block}\n\n"
        f"{framework_block}"
        f"### What to do (skeleton with real framework boot — NO tests)\n\n"
        f"Read ``docs/architecture.md`` first to understand the subsystem's\n"
        f"role and the component decomposition. Then:\n\n"
        f"1. Create the subsystem directory ({src_dir}) if it does not\n"
        f"   already exist.\n"
        f"2. For the bootstrap component (the one that owns the framework\n"
        f"   runtime — typically the renderer / window / app), write\n"
        f"   FULL framework binding bodies as described above. Per-frame\n"
        f"   render / event handling delegates to the OTHER components\n"
        f"   via method calls so stage 2 can fill in their bodies.\n"
        f"3. For every NON-bootstrap component, declare the public API\n"
        f"   with full signatures and docstrings; method bodies remain\n"
        f"   stubs (``pass`` / ``raise NotImplementedError``) BUT every\n"
        f"   render/draw/handle method MUST accept the framework's\n"
        f"   surface / context / request type as its first parameter.\n"
        f"4. Create / update ``{interface_path}`` to re-export every\n"
        f"   component's public types and the bootstrap's entry callable\n"
        f"   (``run()`` / ``main()`` / ``app``). Document the\n"
        f"   inter-subsystem contracts.\n"
        f"5. Do NOT write any test files in this stage. Do NOT fill in\n"
        f"   non-bootstrap component bodies. The next stage dispatches\n"
        f"   one task per non-bootstrap component to do TDD against the\n"
        f"   skeleton you produced.\n\n"
        f"### Smoke-runnability requirement\n\n"
        f"After your skeleton is on disk, ``{contract.get('run_command') or 'the project run command'}`` must\n"
        f"start the framework runtime (open a window, bind the port,\n"
        f"enter the main loop) — even though most components still have\n"
        f"stub bodies. A framework whose ``init`` / ``set_mode`` /\n"
        f"``app.run`` is never called is a FAILED skeleton.\n\n"
        f"Stay strictly inside ``{src_dir}``. Other subsystems' skeletons\n"
        f"are being produced in parallel by sibling dispatches — do not\n"
        f"touch their files.\n"
    )


def _build_component_implementation_task(
    subsystem: dict[str, Any],
    component: dict[str, Any],
    contract: dict[str, Any],
    phase: str,
) -> str:
    """Render the *stage 2* developer task: implement ONE component
    (test + source body) on top of the skeleton produced in stage 1.

    Single-component scope keeps each dispatch's recursion budget
    bounded, so a 10-component subsystem becomes 10 small dispatches
    that fan out concurrently instead of one mega-dispatch that runs
    out of recursion / context budget after the 7th component.
    """
    sname = subsystem.get("name", "?")
    src_dir = subsystem.get("src_dir", "")
    cname = component.get("name", "?")
    cfile = component.get("file", "")
    cresp = component.get("responsibility", "")
    language = (contract.get("language") or "python").lower()
    toolchain = _LANGUAGE_TOOLCHAIN.get(language, _LANGUAGE_TOOLCHAIN["python"])
    test_runner = contract.get("test_runner", "")
    static_analyzer = contract.get("static_analyzer", "")
    if isinstance(static_analyzer, list):
        static_analyzer = " ; ".join(str(s) for s in static_analyzer)

    upper_initial = (cname[:1].upper() + cname[1:]) if cname else "?"
    test_file = component.get("test_file") or toolchain["test_path_pattern"].format(
        subsystem=sname,
        component=cname,
        Component=upper_initial,
    )
    interface_path = _interface_module_path(language, sname, src_dir)

    class _PlaceholderDict(dict):
        def __missing__(self, key: str) -> str:
            return f"<{key}>"

    test_cmd = toolchain["test_cmd"].format_map(
        _PlaceholderDict(
            test_path=test_file,
            component=cname,
            Component=upper_initial,
            subsystem=sname,
        )
    )
    static_check = toolchain["static_check"].format_map(_PlaceholderDict(src_path=cfile, subsystem=sname))

    is_ui = _is_ui_subsystem(subsystem, contract)
    framework_name = (contract.get("framework_frontend") or contract.get("ui_kind") or "").strip()
    recipe = _ui_framework_recipe(contract) if is_ui else None
    surface_type = recipe["surface_type"] if recipe else "the framework's surface / context type"

    ui_block = ""
    if is_ui:
        ui_block = (
            f"\n### UI subsystem rule (REQUIRED — overrides the generic TDD steps below)\n\n"
            f"This component lives in a UI subsystem whose ``framework_frontend`` is\n"
            f"``{framework_name or '(declared in stack_contract.json)'}``. The skeleton phase\n"
            f"already wired the framework's runtime (init / display / app object /\n"
            f"main loop) and threaded ``{surface_type}`` (or its equivalent) through\n"
            f"every public render / draw / handle method on this component.\n\n"
            f"Your bodies MUST call REAL framework APIs against that surface /\n"
            f"context — for example ``surface.blit`` / ``pygame.draw.*`` /\n"
            f"``painter.drawText`` / ``app.route(...)``. State-recording mocks\n"
            f"(``self.last_action = 'render_map'``) are FORBIDDEN: they pass the\n"
            f"unit tests but produce a project that opens no window and renders\n"
            f"nothing (project_0-tower regression).\n\n"
            f"Your tests must instantiate the framework's surface (e.g.\n"
            f"``pygame.Surface((W,H))`` after ``pygame.init()``) and assert on\n"
            f"observable framework state — pixel colors, rect positions, route\n"
            f"responses — NOT on private state-tracking attributes.\n\n"
        )

    return (
        f"## Component implementation task: {sname}.{cname}\n\n"
        f"Phase: {phase} (stage 2: per-component TDD)\n"
        f"Subsystem directory: {src_dir}\n"
        f"Component responsibility: {cresp}\n"
        f"Project language: {language}\n"
        f"Test runner: {test_runner}\n"
        f"Static analyzer: {static_analyzer}\n\n"
        f"### Files\n"
        f"  source:    {cfile}   (skeleton already exists — fill in bodies)\n"
        f"  test:      {test_file}\n"
        f"  interface: {interface_path}   (do NOT modify; import from here\n"
        f"             when you need types / functions from sibling\n"
        f"             components in the same subsystem)\n"
        f"{ui_block}"
        f"### Workflow (strict TDD, ONE component only)\n\n"
        f"1. RED — write the test file at the listed path. Cover the\n"
        f"   public API the skeleton already declares for this component.\n"
        f"2. GREEN — replace the stub bodies in ``{cfile}`` with real\n"
        f"   implementations. Keep the public API EXACTLY as the\n"
        f"   skeleton declared it; sibling components / subsystems\n"
        f"   already import that contract.\n"
        f"3. VERIFY — run the per-file test command:\n"
        f"     {test_cmd}\n"
        f"4. INSPECT — run the static analyzer on the source file:\n"
        f"     {static_check}\n"
        f"   Fix every finding before returning.\n"
        f"5. Up to 3 fix attempts, then return.\n\n"
        f"DO NOT modify any source file other than ``{cfile}`` and ``{test_file}``.\n"
        f"All other components in this subsystem are being implemented\n"
        f"concurrently by sibling dispatches; touching them races.\n"
        f"Cross-component imports MUST go through the interface module\n"
        f"``{interface_path}`` so the skeleton's contract stays the\n"
        f"single source of truth.\n"
    )


def _build_subsystem_task_description(
    subsystem: dict[str, Any],
    contract: dict[str, Any],
    phase: str,
) -> str:
    """Render the developer task description for one subsystem
    deterministically from the stack contract. The LLM is NOT in
    this loop — the resulting text is stable, complete, and
    multilingual based on ``contract.language``.
    """
    name = subsystem.get("name", "?")
    src_dir = subsystem.get("src_dir", "")
    responsibilities = subsystem.get("responsibilities", "")
    components = subsystem.get("components", []) or []
    language = (contract.get("language") or "python").lower()
    toolchain = _LANGUAGE_TOOLCHAIN.get(language, _LANGUAGE_TOOLCHAIN["python"])
    test_runner = contract.get("test_runner", "")
    static_analyzer = contract.get("static_analyzer", "")
    if isinstance(static_analyzer, list):
        static_analyzer = " ; ".join(str(s) for s in static_analyzer)

    component_lines = []
    for c in components:
        if not isinstance(c, dict):
            continue
        cname = c.get("name", "?")
        cfile = c.get("file", "")
        cresp = c.get("responsibility", "")
        # Derive test path from the source file path using the
        # language's pattern. If the contract already specifies a
        # test_file we honour it; otherwise compute one.
        test_file = c.get("test_file") or toolchain["test_path_pattern"].format(
            subsystem=name,
            component=cname,
            Component=cname[:1].upper() + cname[1:],
        )
        component_lines.append(
            f"  - {cname}\n      source: {cfile}\n      test:   {test_file}\n      responsibility: {cresp}"
        )
    components_block = "\n".join(component_lines) if component_lines else "  (no components declared)"

    # Render the per-component test/static-analysis commands as
    # *templates* (with ``<placeholder>`` slots) rather than concrete
    # calls — the developer fills them in per component when they
    # actually run them. Using a placeholder dict keeps any unknown
    # template variable in the toolchain row from raising KeyError;
    # extras are simply rendered as their literal name.
    class _PlaceholderDict(dict):
        def __missing__(self, key: str) -> str:
            return f"<{key}>"

    test_cmd_template = toolchain["test_cmd"].format_map(
        _PlaceholderDict(
            test_path="<test file>",
            component="<component>",
            Component="<Component>",
            subsystem=name,
        )
    )
    static_check_template = toolchain["static_check"].format_map(
        _PlaceholderDict(src_path="<source file>", subsystem=name)
    )

    return (
        f"## Subsystem implementation task: {name}\n\n"
        f"Phase: {phase}\n"
        f"Subsystem directory: {src_dir}\n"
        f"Subsystem responsibility: {responsibilities}\n"
        f"Project language: {language}\n"
        f"Test runner: {test_runner}\n"
        f"Static analyzer: {static_analyzer}\n\n"
        f"### Components to implement (one source file + one test file each)\n\n"
        f"{components_block}\n\n"
        f"### Workflow (strict TDD, per component)\n\n"
        f"For EACH component above, in order:\n"
        f"1. RED — write the test file at the listed path. Cover the\n"
        f"   public API the component's responsibility implies.\n"
        f"2. GREEN — write the source file at the listed path.\n"
        f"3. VERIFY — run the per-file test command:\n"
        f"     {test_cmd_template}\n"
        f"4. INSPECT — run the static analyzer on the source file:\n"
        f"     {static_check_template}\n"
        f"   Fix every finding before moving to the next component.\n"
        f"5. Up to 3 fix attempts per component, then move on.\n\n"
        f"All components share the subsystem directory ({src_dir}) — design\n"
        f"the public API across them as a coherent module, not isolated\n"
        f"islands. Read the architecture doc (docs/architecture.md) for\n"
        f"the subsystem's role in the larger system.\n\n"
        f"Do NOT touch source files outside {src_dir}. Other subsystems are\n"
        f"being developed in parallel by sibling dispatches.\n"
    )


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


# -- Context ---------------------------------------------------------------


@dataclass
class WorkflowState:
    """Mutable workflow state shared by all primitives in a session.

    Code never inspects fields by string keys — instead a tool calls
    ``mark_complete(report)`` and the orchestrator loop reads
    ``state.is_complete``.
    """

    is_complete: bool = False
    final_report: str = ""
    completed_steps: list[str] = field(default_factory=list)


@dataclass
class ToolContext:
    """All the runtime state a tool primitive may need.

    ``manager`` is a :class:`RuntimeManager`. ``runtime_resolver`` is an
    optional callable ``(agent_name, global_runtime) -> AgentRuntime``
    that returns a project-scoped runtime when one exists.
    """

    manager: Any
    project_root: Path | None
    config: RuntimeConfig
    workflow_state: WorkflowState
    on_event: Callable[[dict[str, Any]], None] | None = None
    event_log: list[dict[str, Any]] = field(default_factory=list)
    event_lock: threading.Lock = field(default_factory=threading.Lock)
    runtime_resolver: Callable[[str, Any], Any] | None = None
    processes_dir: Path | None = None
    # The raw user requirement that kicked off this session. Prepended
    # to every dispatch_task prompt so workers see the user's original
    # natural language and can mirror it in any docs/*.md they write.
    # Empty string means "no requirement available" (e.g. unit tests
    # exercising the primitive directly); the prefix is then skipped.
    original_requirement: str = ""
    # Dedup caches: the orchestrator fires a ``stage_update`` before every
    # dispatch even when the stage has not actually changed (parallel
    # developer dispatches all emit "implementation started"), and weak
    # local LLMs spam ``write_todos`` with unchanged todo lists — both
    # make the run log visually incoherent. We suppress consecutive
    # duplicates at emit-time.
    _last_stage: str | None = field(default=None, repr=False, compare=False)
    _last_todos_by_task: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def emit(self, event: dict[str, Any]) -> None:
        """Thread-safe event recording + callback dispatch.

        Suppresses two classes of redundant events that pollute the UI:
        - ``stage_update`` with the same ``stage`` as the previous one
          (typical during parallel dispatch within one phase).
        - ``todos_update`` whose ``todos`` list is byte-identical to the
          previous one for the same ``taskId`` (LLM write_todos spam).
        """
        et = event.get("type")
        with self.event_lock:
            if et == "stage_update":
                stage = event.get("stage")
                if stage is not None and stage == self._last_stage:
                    return
                self._last_stage = stage
            elif et == "todos_update":
                tid = event.get("taskId")
                if tid is not None:
                    import json as _json

                    try:
                        sig = _json.dumps(event.get("todos"), sort_keys=True, ensure_ascii=False)
                    except Exception:
                        sig = repr(event.get("todos"))
                    if self._last_todos_by_task.get(tid) == sig:
                        return
                    self._last_todos_by_task[tid] = sig
            self.event_log.append(event)
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception as exc:  # pragma: no cover - sink should never break tools
                logger.debug("on_event sink raised: %s", exc)

    def dispatch_count(self) -> int:
        with self.event_lock:
            return sum(1 for e in self.event_log if e.get("type") == "task_request")


# -- Discovery primitives --------------------------------------------------


def make_discovery_tools(ctx: ToolContext) -> list[BaseTool]:
    """Create the discovery tool primitives (processes + agents)."""
    from .process_md_parser import parse_process_md

    processes_dir = ctx.processes_dir or _default_processes_dir()
    orchestrator_role = ctx.config.orchestrator_role
    orchestrator_fallback_name = ctx.config.orchestrator_fallback_name

    @tool
    def list_processes() -> str:
        """List all available process definitions with metadata only."""
        if not processes_dir.is_dir():
            return json.dumps({"processes": []})
        items: list[dict[str, str]] = []
        for f in sorted(processes_dir.glob("*.process.md")):
            try:
                proc = parse_process_md(f)
            except Exception as exc:
                logger.warning("Failed to parse process %s: %s", f.name, exc)
                continue
            entry = proc.header_dict()
            entry["file"] = f.name
            items.append(entry)
        ctx.emit(
            {
                "type": "tool_call",
                "tool": "list_processes",
                "summary": f"Found {len(items)} processes",
                "timestamp": _now(),
            }
        )
        return json.dumps({"processes": items}, ensure_ascii=False)

    @tool
    def get_process(process_file: str) -> str:
        """Read the full content of a specific process definition file.

        Args:
            process_file: Filename like 'waterfall.process.md'.
        """
        path = processes_dir / process_file
        if not path.is_file():
            return json.dumps({"error": f"Process file not found: {process_file}"})
        content = path.read_text(encoding="utf-8")
        ctx.emit(
            {
                "type": "tool_call",
                "tool": "get_process",
                "summary": f"Read {process_file}",
                "timestamp": _now(),
            }
        )
        return content

    @tool
    def list_agents() -> str:
        """List all non-orchestrator agents with their cards."""
        agents: list[dict[str, Any]] = []
        for name, rt in ctx.manager.runtimes.items():
            defn = rt.definition
            role = (getattr(defn, "role", "") or "").lower()
            if role == orchestrator_role:
                continue
            # Always exclude the configured orchestrator fallback name,
            # regardless of how its role is tagged. This keeps legacy
            # project_manager.md (no explicit role) excluded.
            if name == orchestrator_fallback_name:
                continue
            agents.append(rt.get_agent_card_dict())
        ctx.emit(
            {
                "type": "tool_call",
                "tool": "list_agents",
                "summary": f"Found {len(agents)} agents",
                "timestamp": _now(),
            }
        )
        return json.dumps({"agents": agents}, ensure_ascii=False)

    return [list_processes, get_process, list_agents]


# -- Dispatch primitives ---------------------------------------------------


def make_dispatch_tools(ctx: ToolContext) -> list[BaseTool]:
    """Create the dispatch_task and dispatch_tasks_parallel primitives."""
    import concurrent.futures

    @tool
    def dispatch_task(
        agent_name: str,
        task_description: str,
        step_id: str = "",
        phase: str = "",
        expected_artifacts: list[str] | None = None,
    ) -> str:
        """Send a task to an agent and return its response.

        Follows the A2A task_request/task_response protocol. The
        orchestrator decides which agent to call — code does not.

        Args:
            agent_name: The target agent's name (must exist).
            task_description: Detailed instructions for the agent.
            step_id: Optional workflow step identifier (free-form).
            phase: Optional workflow phase name (free-form).
            expected_artifacts: Optional list of project-relative paths
                this task must produce. After the agent returns, each
                path is checked for existence and non-trivial size; if
                any is missing, the dispatch is re-issued once with a
                generic context prefix quoting the previous response.
        """
        # Workflow-complete guard: once ``mark_complete`` has fired, no
        # further dispatches are accepted in this session. This stops
        # the "PM keeps dispatching after marking complete" pathology
        # without referencing any specific step or agent.
        if ctx.workflow_state.is_complete:
            logger.info(
                "dispatch_task refused: workflow already complete (to=%s step=%s)",
                agent_name,
                step_id,
            )
            return json.dumps(
                {
                    "status": "refused",
                    "error": (
                        "Workflow is already marked complete. Do not dispatch further tasks. Stop calling tools."
                    ),
                }
            )

        max_dispatches = ctx.config.safety_limits.max_dispatches
        if ctx.dispatch_count() >= max_dispatches:
            logger.warning("dispatch_task refused: cap reached (%d)", max_dispatches)
            return json.dumps(
                {
                    "status": "failed",
                    "error": (
                        f"Maximum dispatches ({max_dispatches}) reached. "
                        "Workflow must finish now. Stop calling tools and "
                        "produce the final delivery report as text."
                    ),
                }
            )

        rt = ctx.manager.get_runtime(agent_name)
        if rt is None:
            available = sorted(ctx.manager.runtimes.keys())
            return json.dumps(
                {
                    "status": "failed",
                    "error": f"Agent '{agent_name}' not found. Available: {available}",
                }
            )

        task_id = uuid.uuid4().hex[:10]
        # Emit a stage_update first so the UI can group events under
        # the active phase. ``phase`` is free-form; the only thing the
        # code knows is that empty means "default execution".
        ctx.emit(
            {
                "type": "stage_update",
                "stage": phase or "execution",
                "status": "started",
                "timestamp": _now(),
            }
        )
        request_msg = {
            "taskId": task_id,
            "from": "orchestrator",
            "to": agent_name,
            "type": "task_request",
            "timestamp": _now(),
            "payload": {"step": step_id, "phase": phase, "task": task_description},
        }
        ctx.emit(request_msg)
        logger.info("Task dispatched: task=%s to=%s step=%s", task_id, agent_name, step_id)

        # Mark the GLOBAL runtime as WORKING so the Monitor shows
        # real-time status. The actual work runs on a project-scoped
        # runtime clone, but the Monitor reads from the manager's
        # global registry.
        from .models import AgentState

        rt._state = AgentState.WORKING
        rt._current_task = task_description[:120]

        try:
            resolver = ctx.runtime_resolver
            dispatch_rt = resolver(agent_name, rt) if resolver is not None else rt

            def _on_todos_update(todos: list[dict[str, Any]]) -> None:
                ctx.emit(
                    {
                        "type": "todos_update",
                        "taskId": task_id,
                        "agent": agent_name,
                        "timestamp": _now(),
                        "todos": todos,
                    }
                )

            def _on_token_usage(counts: dict[str, int]) -> None:
                ctx.emit(
                    {
                        "type": "token_usage",
                        "taskId": task_id,
                        "agent": agent_name,
                        "timestamp": _now(),
                        "input_tokens": int(counts.get("input_tokens", 0) or 0),
                        "output_tokens": int(counts.get("output_tokens", 0) or 0),
                        "total_tokens": int(counts.get("total_tokens", 0) or 0),
                    }
                )

            # Build the prompt the worker actually sees. Two prefixes
            # are prepended (when available) so workers have stable
            # context the orchestrator LLM cannot strip:
            #
            #   1. ORIGINAL USER REQUIREMENT — the raw user text, used
            #      by doc-producing agents to mirror its natural
            #      language in any docs/*.md they write.
            #   2. STACK CONTRACT — the architect's pinned language /
            #      framework / test-runner / entry-point choices,
            #      loaded from docs/stack_contract.json. This stops
            #      orchestrator dispatches from "translating" the
            #      stack into a different language (e.g. Node→Python)
            #      because the worker now has the architect's
            #      authoritative choices in its prompt.
            #
            # The already-emitted ``request_msg`` keeps the
            # unprefixed ``task_description`` in its payload so the
            # UI/log is not bloated by N copies of these blocks.
            worker_prompt = task_description
            if ctx.original_requirement:
                worker_prompt = (
                    "=== ORIGINAL USER REQUIREMENT "
                    "(preserve this natural language in all docs/*.md) ===\n"
                    f"{ctx.original_requirement}\n"
                    "=== END ORIGINAL REQUIREMENT ===\n\n"
                    f"{worker_prompt}"
                )
            stack_block = _load_stack_contract_block(ctx.project_root)
            if stack_block:
                worker_prompt = f"{stack_block}\n\n{worker_prompt}"

            # First attempt.
            result = dispatch_rt.handle_message(
                worker_prompt,
                on_todos_update=_on_todos_update,
                on_token_usage=_on_token_usage,
            )

            # Context-augmented retry loop. Triggers in two cases, both
            # role-neutral:
            #   a) the agent's response was effectively empty;
            #   b) ``expected_artifacts`` were declared but are missing
            #      or trivially small.
            # The retry prompt quotes the previous response verbatim and
            # asks the agent to continue — no agent-specific phrasing,
            # no tool names, no filenames baked into the template.
            retries_used = 0
            while retries_used < _MAX_DISPATCH_RETRIES:
                shortfalls = _artifact_shortfalls(ctx.project_root, expected_artifacts)
                if result.strip() and not shortfalls:
                    break
                retries_used += 1
                if shortfalls:
                    logger.info(
                        "Retry %d/%d for task=%s: missing artifacts=%s",
                        retries_used,
                        _MAX_DISPATCH_RETRIES,
                        task_id,
                        shortfalls,
                    )
                else:
                    logger.info(
                        "Retry %d/%d for task=%s: empty response",
                        retries_used,
                        _MAX_DISPATCH_RETRIES,
                        task_id,
                    )
                retry_prompt = _build_retry_prompt(worker_prompt, result)
                result = dispatch_rt.handle_message(
                    retry_prompt,
                    on_todos_update=_on_todos_update,
                    on_token_usage=_on_token_usage,
                )

            output_len = len(result)
            preview = result[:500] + "..." if output_len > 500 else result
            response_msg = {
                "taskId": task_id,
                "from": agent_name,
                "to": "orchestrator",
                "type": "task_response",
                "status": "completed",
                "timestamp": _now(),
                "payload": {
                    "output_preview": preview,
                    "output_length": output_len,
                    "retries": retries_used,
                },
            }
            ctx.emit(response_msg)
            logger.info(
                "Task completed: task=%s from=%s output=%d chars retries=%d",
                task_id,
                agent_name,
                output_len,
                retries_used,
            )
            return json.dumps(response_msg, ensure_ascii=False)
        except Exception as exc:
            error_msg = {
                "taskId": task_id,
                "from": agent_name,
                "to": "orchestrator",
                "type": "task_response",
                "status": "failed",
                "timestamp": _now(),
                "payload": {"error": str(exc)},
            }
            ctx.emit(error_msg)
            logger.warning("Task failed: task=%s from=%s error=%s", task_id, agent_name, exc)
            return json.dumps(error_msg, ensure_ascii=False)
        finally:
            rt._state = AgentState.ACTIVE
            rt._current_task = None

    @tool
    def dispatch_tasks_parallel(tasks_json: str) -> str:
        """Dispatch multiple tasks in parallel to different agents.

        Args:
            tasks_json: JSON array of objects with keys agent_name,
                task_description, step_id, phase, expected_artifacts.
        """
        try:
            tasks = json.loads(tasks_json)
        except Exception:
            return json.dumps({"status": "failed", "error": "Invalid JSON"})

        if not isinstance(tasks, list) or not tasks:
            return json.dumps({"status": "failed", "error": "tasks must be a non-empty array"})

        results: list[dict[str, Any]] = []
        results_lock = threading.Lock()

        def run_one(t: dict[str, Any]) -> dict[str, Any]:
            raw = dispatch_task.invoke(
                {
                    "agent_name": t.get("agent_name", ""),
                    "task_description": t.get("task_description", ""),
                    "step_id": t.get("step_id", ""),
                    "phase": t.get("phase", ""),
                    "expected_artifacts": t.get("expected_artifacts"),
                }
            )
            return json.loads(raw)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(tasks))) as pool:
            futures = {pool.submit(run_one, t): t for t in tasks}
            for future in concurrent.futures.as_completed(futures):
                try:
                    item = future.result()
                except Exception as exc:
                    t = futures[future]
                    item = {"status": "failed", "from": t.get("agent_name"), "error": str(exc)}
                with results_lock:
                    results.append(item)

        ok = sum(1 for r in results if r.get("status") == "completed")
        fail = sum(1 for r in results if r.get("status") == "failed")
        return json.dumps(
            {
                "parallel_results": results,
                "total": len(results),
                "completed": ok,
                "failed": fail,
            },
            ensure_ascii=False,
        )

    @tool
    def dispatch_subsystems(phase: str = "implementation", agent_name: str = "developer") -> str:
        """Two-stage subsystem fan-out: skeletons first, then per-component
        TDD in full parallel.

        Stage 1 (sequential within the subsystem, parallel across
        subsystems): dispatch one *skeleton* task per subsystem. Each
        worker creates the source files with public API
        types/signatures/docstrings populated, plus an interface module
        re-exporting the subsystem's public API — but NO logic and NO
        tests. This guarantees inter-module contracts are committed to
        disk before any component is implemented.

        Stage 2 (full fan-out): once every skeleton is on disk, dispatch
        one *component implementation* task per component across every
        subsystem. Each dispatch only owns one ``src_dir/<component>``
        file pair (source + test), so its recursion budget is bounded
        even for very weak workers — a 24-component architecture
        becomes 24 small concurrent dispatches instead of one
        mega-dispatch that runs out of recursion limit at component 9.

        Both stages are throttled by
        ``max_concurrent_subsystem_dispatches``.

        Args:
            phase: Phase label ("implementation" /
                "sprint_execution" / etc.), embedded in every dispatched
                task description for traceability.
            agent_name: Worker agent to dispatch to. Defaults to
                "developer" — change if a future phase needs a
                different worker (e.g. "qa_engineer").
        """
        contract = _load_stack_contract_data(ctx.project_root)
        if contract is None:
            return json.dumps(
                {
                    "status": "failed",
                    "error": (
                        "docs/stack_contract.json missing or unparseable. Dispatch architect first to produce it."
                    ),
                }
            )
        subsystems = contract.get("subsystems")
        if not isinstance(subsystems, list) or not subsystems:
            return json.dumps(
                {
                    "status": "failed",
                    "error": (
                        "docs/stack_contract.json has no subsystems[] array. "
                        "Architect must use the two-level subsystems[].components[] "
                        "schema (legacy flat modules[] is no longer supported here)."
                    ),
                }
            )

        max_workers = max(1, ctx.config.safety_limits.max_concurrent_subsystem_dispatches)
        language = (contract.get("language") or "python").lower()
        toolchain = _LANGUAGE_TOOLCHAIN.get(language, _LANGUAGE_TOOLCHAIN["python"])

        # Build a per-subsystem plan that bundles its own skeleton +
        # component dispatches. Cross-subsystem ordering is intentionally
        # NOT serialized — different subsystems share no files, so a
        # subsystem that finishes its skeleton early can start its
        # components while a slower sibling is still scaffolding.
        subsystem_plans: list[dict[str, Any]] = []
        for ss in subsystems:
            if not isinstance(ss, dict):
                continue
            sname = ss.get("name", "?")
            src_dir = ss.get("src_dir", "")
            interface_path = _interface_module_path(language, sname, src_dir)

            skel_expected: list[str] = []
            component_items: list[dict[str, Any]] = []
            for comp in ss.get("components", []) or []:
                if not isinstance(comp, dict):
                    continue
                cf = comp.get("file")
                if cf:
                    skel_expected.append(cf)
                cname = comp.get("name", "?")
                upper_initial = (cname[:1].upper() + cname[1:]) if cname else "?"
                tfile = comp.get("test_file") or toolchain["test_path_pattern"].format(
                    subsystem=sname,
                    component=cname,
                    Component=upper_initial,
                )
                component_items.append(
                    {
                        "subsystem": sname,
                        "component": cname,
                        "task_description": _build_component_implementation_task(ss, comp, contract, phase=phase),
                        "step_id": f"phase_{phase}_component_{sname}_{cname}",
                        "phase": f"{phase}_component",
                        "expected_artifacts": [p for p in (cf, tfile) if p],
                    }
                )
            skel_expected.append(interface_path)

            subsystem_plans.append(
                {
                    "subsystem": sname,
                    "skeleton": {
                        "subsystem": sname,
                        "task_description": _build_subsystem_skeleton_task(ss, contract, phase=phase),
                        "step_id": f"phase_{phase}_skeleton_{sname}",
                        "phase": f"{phase}_skeleton",
                        "expected_artifacts": skel_expected,
                    },
                    "components": component_items,
                }
            )

        # Cross-subsystem global throttle. Outer (subsystem) and inner
        # (component) executors are nested, so a naïve ``max_workers``
        # on each pool would multiply: cap=2 with 5 subsystems × 2
        # components could put 4 dispatches in flight. The semaphore
        # bounds TOTAL in-flight ``dispatch_task`` calls across every
        # subsystem and every stage, matching the user-visible
        # ``max_concurrent_subsystem_dispatches`` contract.
        global_throttle = threading.Semaphore(max_workers)

        def _run_dispatch(item: dict[str, Any]) -> dict[str, Any]:
            with global_throttle:
                raw = dispatch_task.invoke(
                    {
                        "agent_name": agent_name,
                        "task_description": item["task_description"],
                        "step_id": item["step_id"],
                        "phase": item["phase"],
                        "expected_artifacts": item["expected_artifacts"] or None,
                    }
                )
            try:
                parsed = json.loads(raw)
            except Exception:
                parsed = {"status": "failed", "error": "non-JSON dispatch result"}
            parsed["subsystem"] = item["subsystem"]
            if "component" in item:
                parsed["component"] = item["component"]
            return parsed

        # Per-subsystem worker: run skeleton first (sequential within
        # the subsystem), then fan out the subsystem's own components
        # in parallel. Each subsystem owns its own ThreadPoolExecutor
        # for the inner component fan-out so a slow subsystem never
        # blocks a sibling.
        skeleton_results: list[dict[str, Any]] = []
        component_results: list[dict[str, Any]] = []
        results_lock = threading.Lock()

        def _run_subsystem(plan: dict[str, Any]) -> dict[str, Any]:
            skel_item = plan["skeleton"]
            try:
                skel_out = _run_dispatch(skel_item)
            except Exception as exc:  # pragma: no cover - defensive
                skel_out = {
                    "status": "failed",
                    "subsystem": skel_item["subsystem"],
                    "error": str(exc),
                }
            # Run components even if the skeleton dispatch reported
            # ``failed`` — the per-component dispatch will surface a
            # missing-artifact failure via ``expected_artifacts``,
            # which is more diagnostic than refusing to launch them.
            inner_results: list[dict[str, Any]] = []
            comp_items = plan["components"]
            if comp_items:
                # Pool just needs enough threads to feed the global
                # semaphore — the semaphore is the real throttle.
                inner_workers = max(1, len(comp_items))
                with concurrent.futures.ThreadPoolExecutor(max_workers=inner_workers) as pool:
                    futures = {pool.submit(_run_dispatch, item): item for item in comp_items}
                    for future in concurrent.futures.as_completed(futures):
                        try:
                            comp_out = future.result()
                        except Exception as exc:
                            item = futures[future]
                            comp_out = {
                                "status": "failed",
                                "subsystem": item["subsystem"],
                                "component": item["component"],
                                "error": str(exc),
                            }
                        inner_results.append(comp_out)
            with results_lock:
                skeleton_results.append(skel_out)
                component_results.extend(inner_results)
            return {"skeleton": skel_out, "components": inner_results}

        # Subsystems fan out fully in parallel; the global semaphore
        # above bounds the total in-flight dispatches across every
        # subsystem and every stage, so the executor sizes are just
        # "enough threads to keep the semaphore busy". The actual
        # concurrency cap is ``max_workers`` (== the semaphore
        # capacity) regardless of how many subsystems / components
        # the architect declared.
        outer_workers = max(1, len(subsystem_plans)) if subsystem_plans else 1
        with concurrent.futures.ThreadPoolExecutor(max_workers=outer_workers) as outer_pool:
            outer_futures = [outer_pool.submit(_run_subsystem, plan) for plan in subsystem_plans]
            for fut in concurrent.futures.as_completed(outer_futures):
                # Per-subsystem worker already wrote into the shared
                # result lists; we drain the futures here only to
                # surface any uncaught exceptions.
                try:
                    fut.result()
                except Exception as exc:  # pragma: no cover - defensive
                    logger.warning("Subsystem worker raised: %s", exc)

        skel_ok = sum(1 for r in skeleton_results if r.get("status") == "completed")
        skel_fail = sum(1 for r in skeleton_results if r.get("status") == "failed")
        comp_ok = sum(1 for r in component_results if r.get("status") == "completed")
        comp_fail = sum(1 for r in component_results if r.get("status") == "failed")

        return json.dumps(
            {
                "phase": phase,
                "agent_name": agent_name,
                "subsystems_dispatched": len(subsystem_plans),
                "components_dispatched": len(component_results),
                "max_concurrent": max_workers,
                "skeleton_completed": skel_ok,
                "skeleton_failed": skel_fail,
                "components_completed": comp_ok,
                "components_failed": comp_fail,
                # Aggregate roll-up across both stages so callers that just
                # want pass/fail counts don't have to add the four numbers
                # themselves.
                "completed": skel_ok + comp_ok,
                "failed": skel_fail + comp_fail,
                "skeleton_results": skeleton_results,
                "results": component_results,
            },
            ensure_ascii=False,
        )

    return [dispatch_task, dispatch_tasks_parallel, dispatch_subsystems]


# -- Shell primitive -------------------------------------------------------


def make_shell_tool(ctx: ToolContext) -> BaseTool:
    """Create the ``execute_shell`` primitive (allowlist-guarded)."""
    shell_cfg = ctx.config.shell

    def _strip_cd_prefix(command: str) -> str:
        """Remove ``cd <path> &&`` or ``cd <path> ;`` prefix from a command.

        LLMs frequently prepend ``cd /absolute/path && actual_command``
        but execute_shell already sets cwd to the project root. The cd
        overrides that, pointing to the wrong directory. We strip it so
        the command runs in the correct project root.
        """
        import re

        return re.sub(r"^\s*cd\s+\S+\s*[;&]+\s*", "", command)

    @tool
    def execute_shell(command: str, cwd: str = "", timeout: int = 0) -> str:
        """Execute a shell command in the project root directory.

        The working directory is ALREADY set to the project root.
        Do NOT use ``cd`` to change directory — it is unnecessary and
        will be stripped. Just run the command directly, e.g.:
        ``python -m pytest tests/ -q --tb=short``

        Args:
            command: Shell command string (pipes and && are supported).
            cwd: Optional subdirectory relative to project root.
            timeout: Optional timeout in seconds.
        """
        command = _strip_cd_prefix(command)
        if not command.strip():
            return json.dumps({"status": "failed", "error": "empty command after stripping cd prefix"})

        if not shell_cfg.is_allowed(command):
            return json.dumps(
                {
                    "status": "refused",
                    "error": (f"Command not in allowlist. Allowed: {sorted(shell_cfg.allowlist)}"),
                }
            )

        effective_timeout = timeout if timeout > 0 else shell_cfg.timeout_seconds
        if ctx.project_root is None:
            return json.dumps({"status": "failed", "error": "no project root"})

        work_dir = ctx.project_root
        if cwd:
            candidate = (ctx.project_root / cwd).resolve()
            try:
                candidate.relative_to(ctx.project_root.resolve())
            except ValueError:
                return json.dumps({"status": "refused", "error": "cwd escapes project root"})
            work_dir = candidate

        try:
            # Use shell=True so that pipes (|), redirections (2>&1),
            # and chained commands (&&) work as LLMs expect.
            # Safety: the allowlist check already validated all
            # executables in the command string.
            proc = subprocess.run(  # noqa: S603 — allowlist enforced above
                command,
                shell=True,
                cwd=str(work_dir),
                capture_output=True,
                text=True,
                timeout=effective_timeout,
            )
        except subprocess.TimeoutExpired:
            return json.dumps(
                {
                    "status": "failed",
                    "error": f"command timed out after {effective_timeout}s",
                }
            )
        except FileNotFoundError as exc:
            return json.dumps({"status": "failed", "error": f"command not found: {exc}"})

        stdout = (proc.stdout or "")[-3000:]
        stderr = (proc.stderr or "")[-3000:]
        ctx.emit(
            {
                "type": "tool_call",
                "tool": "execute_shell",
                "summary": f"{command} → exit={proc.returncode}",
                "timestamp": _now(),
            }
        )
        return json.dumps(
            {
                "status": "completed",
                "exit_code": proc.returncode,
                "stdout": stdout,
                "stderr": stderr,
            },
            ensure_ascii=False,
        )

    return execute_shell


# -- Workflow state primitive ---------------------------------------------


_COMPLETION_MIN_ARTIFACT_BYTES = 64

# Regex hits that indicate the report itself is announcing a partial
# delivery. PM has historically called ``mark_complete`` after a
# truncated implementation phase with text like "0/10 ❌ (dispatch
# cap hit)" — the gate refuses these so the run cannot be falsely
# closed as completed. Patterns are case-insensitive.
_COMPLETION_REPORT_REJECT_PATTERNS: tuple[str, ...] = (
    r"\bdispatch cap hit\b",
    r"\bnot implemented\b",
    r"\bcould not be processed\b",
    r"\bbefore this subsystem\b",
    r"\b0\s*/\s*\d+\b",
    r"❌",
    r"\btruncated\b",
    r"\bexhausted\b",
)


def _completion_artifact_shortfall(
    project_root: Path | None,
) -> list[str]:
    """Return component source files declared by the architect's stack
    contract that are missing or trivially small on disk.

    Used by the ``mark_complete`` gate to refuse closing a run while
    the architect's deliverables aren't fully on disk.
    """
    if project_root is None:
        return []
    contract_path = project_root / "docs" / "stack_contract.json"
    if not contract_path.is_file():
        return []
    try:
        data = json.loads(contract_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    subsystems = data.get("subsystems")
    if not isinstance(subsystems, list):
        return []

    missing: list[str] = []
    for ss in subsystems:
        if not isinstance(ss, dict):
            continue
        for comp in ss.get("components") or []:
            if not isinstance(comp, dict):
                continue
            cfile = comp.get("file")
            if not cfile:
                continue
            target = (project_root / cfile).resolve()
            try:
                size = target.stat().st_size if target.is_file() else 0
            except OSError:
                size = 0
            if size < _COMPLETION_MIN_ARTIFACT_BYTES:
                missing.append(cfile)
    return missing


def make_completion_tool(ctx: ToolContext) -> BaseTool:
    """Create the ``mark_complete`` primitive — the explicit terminal signal."""

    @tool
    def mark_complete(report: str) -> str:
        """Signal that the workflow is complete and provide the final report.

        After calling this, the orchestrator's continuation loop exits.
        Use ONCE, when all phases are done.

        The runtime gates this call: it is REJECTED when

        - every planned phase has not yet emitted ``phase_complete``,
        - the architect's stack contract declares component files that
          are missing or trivially small on disk, OR
        - the report text contains markers indicating the run was
          truncated (``"dispatch cap hit"``, ``"0/N"``, ``"❌"``, etc.)

        Rejected calls return ``status: refused`` with the missing
        artifact list so the orchestrator can dispatch the gaps and
        retry instead of silently closing a partial run.

        Args:
            report: The final delivery report (markdown text).
        """
        # Idempotency guard: if the workflow is already complete, keep
        # the first report and refuse the second call. Without this the
        # LLM sometimes calls ``mark_complete`` twice in a row, the
        # second call overwriting the first report (often with a
        # shorter / lower-quality version) and also interleaving extra
        # dispatches between the two calls.
        if ctx.workflow_state.is_complete:
            logger.info(
                "mark_complete refused: already complete (existing_len=%d new_len=%d)",
                len(ctx.workflow_state.final_report),
                len(report),
            )
            return json.dumps(
                {
                    "status": "refused",
                    "error": "Workflow is already marked complete.",
                    "existing_report_length": len(ctx.workflow_state.final_report),
                }
            )

        # Gate 1: every planned phase must have completed — except the
        # final one, since mark_complete is called from INSIDE the
        # final phase (before the orchestrator loop emits its
        # ``phase_complete`` event). The legal pattern is therefore:
        # we have a ``phase_start`` for the final index AND every
        # earlier index has a matching ``phase_complete``.
        with ctx.event_lock:
            plan_events = [e for e in ctx.event_log if e.get("type") == "phase_plan"]
            done_events = [e for e in ctx.event_log if e.get("type") == "phase_complete"]
            start_events = [e for e in ctx.event_log if e.get("type") == "phase_start"]
        planned_total = 0
        if plan_events:
            try:
                planned_total = int(plan_events[-1].get("total") or 0)
            except (TypeError, ValueError):
                planned_total = 0
        done_indices: set[int] = set()
        for ev in done_events:
            try:
                done_indices.add(int(ev.get("phase_idx")))
            except (TypeError, ValueError):
                continue
        started_indices: set[int] = set()
        for ev in start_events:
            try:
                started_indices.add(int(ev.get("phase_idx")))
            except (TypeError, ValueError):
                continue
        if planned_total:
            final_idx = planned_total - 1
            earlier_required = set(range(final_idx))
            missing_earlier = sorted(earlier_required - done_indices)
            in_final_phase = final_idx in started_indices
            if missing_earlier or not in_final_phase:
                missing_phases = sorted(earlier_required - done_indices)
                if not in_final_phase:
                    missing_phases.append(final_idx)
                logger.info(
                    "mark_complete refused: phases_done=%s started_final=%s plan_total=%d",
                    sorted(done_indices),
                    in_final_phase,
                    planned_total,
                )
                return json.dumps(
                    {
                        "status": "refused",
                        "error": (
                            f"Cannot mark complete — {len(done_indices)}/{planned_total} "
                            f"phases finished and final phase started={in_final_phase}. "
                            f"Missing phase indices: {missing_phases}. "
                            "Continue dispatching the remaining phases (main_entry / "
                            "qa_testing / delivery) before calling mark_complete again."
                        ),
                        "phases_completed": sorted(done_indices),
                        "phases_total": planned_total,
                        "missing_phase_indices": missing_phases,
                    },
                    ensure_ascii=False,
                )

        # Gate 2: every component file declared by the architect must
        # exist on disk with non-trivial content. A run that closes
        # while ``src/gameplay/*.py`` is still empty is not done.
        missing_files = _completion_artifact_shortfall(ctx.project_root)
        if missing_files:
            logger.info(
                "mark_complete refused: %d declared component files missing/empty",
                len(missing_files),
            )
            return json.dumps(
                {
                    "status": "refused",
                    "error": (
                        f"Cannot mark complete — {len(missing_files)} component "
                        "files declared in docs/stack_contract.json are missing or "
                        "trivially small on disk. Dispatch the responsible subsystem "
                        "to fill them in, then call mark_complete again."
                    ),
                    "missing_artifacts": missing_files[:50],
                    "missing_artifact_count": len(missing_files),
                },
                ensure_ascii=False,
            )

        # Gate 3: refuse reports that openly admit partial delivery.
        # PM has historically tried to close runs with text like
        # "0/10 ❌ (dispatch cap hit before this subsystem was
        # processed)" — that's a partial delivery, not a delivery.
        report_lower = (report or "").lower()
        flagged: list[str] = []
        for pattern in _COMPLETION_REPORT_REJECT_PATTERNS:
            if re.search(pattern, report_lower, flags=re.IGNORECASE):
                flagged.append(pattern)
        if flagged:
            logger.info(
                "mark_complete refused: report contains partial-delivery markers: %s",
                flagged,
            )
            return json.dumps(
                {
                    "status": "refused",
                    "error": (
                        "Cannot mark complete — the report you supplied describes a "
                        "partial delivery (matched markers: "
                        f"{flagged}). Finish the missing work and submit a report "
                        "that does not flag any subsystem as failed/truncated."
                    ),
                    "flagged_markers": flagged,
                },
                ensure_ascii=False,
            )

        ctx.workflow_state.is_complete = True
        ctx.workflow_state.final_report = report
        ctx.emit(
            {
                "type": "workflow_complete",
                "report_length": len(report),
                "timestamp": _now(),
            }
        )
        logger.info("Workflow marked complete: report=%d chars", len(report))
        return json.dumps({"status": "acknowledged", "report_length": len(report)})

    return mark_complete


# -- Aggregate factory -----------------------------------------------------


def build_orchestrator_tools(ctx: ToolContext) -> list[BaseTool]:
    """Build the full primitive tool set for an orchestrator session."""
    tools: list[BaseTool] = []
    tools.extend(make_discovery_tools(ctx))
    tools.extend(make_dispatch_tools(ctx))
    tools.append(make_shell_tool(ctx))
    tools.append(make_completion_tool(ctx))
    return tools


# -- Helpers ---------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_processes_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "processes"
