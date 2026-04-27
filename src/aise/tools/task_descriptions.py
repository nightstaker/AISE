"""Deterministic per-subsystem / per-component task-description renderers.

These templates are intentionally LLM-free — they translate the
architect's stack-contract data straight into worker prompts so the
orchestrator cannot drift the language / framework / test runner.
"""

from __future__ import annotations

from typing import Any

from .stack_contract import (
    _LANGUAGE_TOOLCHAIN,
    _interface_module_path,
    _is_ui_subsystem,
    _ui_framework_recipe,
)


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
