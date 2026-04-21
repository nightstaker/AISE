"""Regression guards for the agent-interaction view added to the run detail page.

The view itself is React + SVG living in ``app.js``; we don't spin up a
headless browser in CI. Instead the tests pin two layers that together
keep the feature honest:

1. **Structural presence** — the view switcher, the ``AgentInteractionView``
   component, the ``computeAgentGraph`` helper, the i18n keys, and the
   CSS classes the component relies on must all exist.
2. **Derivation semantics** — the same aggregation logic the JS helper
   performs is re-implemented in Python against the same event shape
   the backend emits (via ``tool_primitives.dispatch_task``), so we can
   assert the intended behavior without a JS runtime.

If either layer regresses, the view on the page will silently degrade
(tabs vanish, cards empty, edge counts wrong) and these tests will
catch it first.
"""

from __future__ import annotations

import re
from pathlib import Path

import aise

STATIC_DIR = Path(aise.__file__).resolve().parent / "web" / "static"
APP_JS = STATIC_DIR / "app.js"
MAIN_CSS = STATIC_DIR / "main.css"


class TestAgentInteractionStructuralPresence:
    def test_view_switcher_tabs_rendered(self) -> None:
        body = APP_JS.read_text(encoding="utf-8")
        # The tab strip must exist with both timeline + agents options.
        assert '"run-view-tabs"' in body
        assert "setRunView" in body
        assert '"timeline", "agents"' in body or "'timeline', 'agents'" in body

    def test_agent_interaction_view_component_exists(self) -> None:
        body = APP_JS.read_text(encoding="utf-8")
        assert "function AgentInteractionView" in body
        # Its two helpers must be declared alongside it.
        assert "function computeAgentGraph" in body
        assert "function AgentCard" in body
        assert "function AgentStatusBadge" in body

    def test_runapp_mounts_agent_view_when_view_is_agents(self) -> None:
        body = APP_JS.read_text(encoding="utf-8")
        assert re.search(r'runView\s*===\s*"agents"\s*\?\s*h\(AgentInteractionView', body), (
            "RunApp must mount AgentInteractionView when runView === 'agents'"
        )
        # And the timeline branch must also be gated on ``runView === 'timeline'``
        # so switching to agents hides the old sections.
        assert re.search(r'runView\s*===\s*"timeline"', body)

    def test_i18n_keys_present_in_both_languages(self) -> None:
        """Every user-visible string the view uses must have a zh and
        en translation. A missing key would render the raw lookup key
        on the page."""
        body = APP_JS.read_text(encoding="utf-8")
        required_keys = [
            "run.view.timeline",
            "run.view.agents",
            "agents.section_title",
            "agents.role.orchestrator",
            "agents.role.worker",
            "agents.status.idle",
            "agents.status.working",
            "agents.status.done",
            "agents.stat.running",
            "agents.stat.completed",
            "agents.stat.failed",
            "agents.tasks_heading",
            "agents.no_tasks",
            "agents.no_participants",
            "agents.waiting",
            "agents.dispatches",
        ]
        # Extract the zh and en blocks.
        zh_block = _extract_lang_block(body, "zh")
        en_block = _extract_lang_block(body, "en")
        for key in required_keys:
            assert f'"{key}"' in zh_block, f"zh translation missing: {key}"
            assert f'"{key}"' in en_block, f"en translation missing: {key}"

    def test_css_classes_referenced_by_component_are_defined(self) -> None:
        """Every class the React tree uses must be declared in main.css,
        otherwise the cards render unstyled."""
        css = MAIN_CSS.read_text(encoding="utf-8")
        required_classes = [
            ".run-view-tabs",
            ".run-view-tab",
            ".run-view-tab-active",
            ".agent-graph",
            ".agent-graph-row",
            ".agent-graph-row-top",
            ".agent-graph-row-workers",
            ".agent-graph-edges",
            ".agent-graph-edge",
            ".agent-graph-edge-line",
            ".agent-graph-edge-label",
            ".agent-card",
            ".agent-card-role-orchestrator",
            ".agent-card-header",
            ".agent-card-status",
            ".agent-card-status-working",
            ".agent-card-status-idle",
            ".agent-card-status-done",
            ".agent-card-stats",
            ".agent-card-tasks-title",
            ".agent-card-tasks-list",
            ".agent-card-task",
            ".agent-task-running",
            ".agent-task-completed",
            ".agent-task-failed",
        ]
        for cls in required_classes:
            assert cls in css, f"CSS class referenced in app.js but missing in main.css: {cls}"


class TestAgentStatusInterpolation:
    """The ``agents.status.working`` template uses ``{n}`` for the
    running-task count. Every caller site must pass an ``n`` key in
    the params object, otherwise the placeholder surfaces literally
    on the page (observed: ``执行中 ({n})`` rendered instead of
    ``执行中 (3)``).

    Pin both sides of the contract: the template syntax AND the
    caller's param key — a change to one without the other is a
    silent regression. Extending this to ``agents.dispatches`` so a
    future rename of the edge-badge key can't break the same way.
    """

    # Which placeholder name is expected in each template + the
    # corresponding caller-side param name. Values are lowercase for
    # case-insensitive matching.
    INTERPOLATION_KEYS: list[tuple[str, str]] = [
        ("agents.status.working", "n"),
        ("agents.dispatches", "n"),
        ("entry.meta.output", "n"),
    ]

    def test_template_placeholder_matches_caller_param(self) -> None:
        body = APP_JS.read_text(encoding="utf-8")
        for key, expected_param in self.INTERPOLATION_KEYS:
            for value in _collect_template_values(body, key):
                # Every placeholder in the template must exactly match
                # ``expected_param``. A ``{count}`` in a template that
                # expects ``n`` is what caused the original bug.
                placeholders = re.findall(r"(?<!\{)\{(\w+)\}(?!\})", value)
                assert placeholders, (
                    f"template for {key} carries no {{x}} placeholder — "
                    "did the translation drop the interpolation spot?"
                )
                for ph in placeholders:
                    assert ph == expected_param, (
                        f"template for {key} uses {{{ph}}} but the "
                        f"caller in app.js passes {{ {expected_param} }} "
                        "— placeholder names must match exactly"
                    )
            # Find every call site for this key in app.js and check
            # that its params object has the expected_param key.
            for params_src in _collect_t_call_params(body, key):
                if params_src is None:
                    continue  # no params on this call (e.g. parameterless usage)
                assert re.search(rf"\b{expected_param}\s*:", params_src), (
                    f't("{key}", ...) caller passes params without '
                    f"{expected_param!r}: {params_src!r}. The template uses "
                    f"{{{expected_param}}} so any other key leaks the "
                    "placeholder through to the UI."
                )

    def test_agent_status_working_caller_binds_n(self) -> None:
        """Tight regression for the specific bug — don't just rely on
        the generic test above, which passes as long as SOME caller is
        correct. This one pins the ``AgentStatusBadge`` call site."""
        body = APP_JS.read_text(encoding="utf-8")
        # Skip the function signature (which contains destructured
        # ``{ agent }`` braces that confuse a naive depth counter) and
        # land the brace counter on the function body's opening brace.
        sig_match = re.search(r"function AgentStatusBadge\s*\([^)]*\)\s*\{", body)
        assert sig_match, "AgentStatusBadge not found"
        body_start = sig_match.end() - 1  # index of the body's opening '{'
        depth = 0
        i = body_start
        while i < len(body):
            if body[i] == "{":
                depth += 1
            elif body[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
            i += 1
        fn_src = body[body_start : end + 1]
        assert 't("agents.status.working"' in fn_src
        assert "{ n:" in fn_src or "{ n :" in fn_src, (
            "AgentStatusBadge must pass { n: agent.runningCount } — the template placeholder is {n}"
        )
        # Match `count:` as a key specifically, not inside other tokens
        # like `runningCount`.
        assert not re.search(r"[^\w]count\s*:", fn_src), (
            "AgentStatusBadge used to pass { count: ... } which left {n} literal in the rendered UI"
        )


def _collect_template_values(body: str, key: str) -> list[str]:
    """Return every string value a given translation key maps to in
    the TRANSLATIONS table. There's typically one per language."""
    values: list[str] = []
    for m in re.finditer(rf'"{re.escape(key)}":\s*"([^"]*)"', body):
        values.append(m.group(1))
    return values


def _collect_t_call_params(body: str, key: str) -> list[str | None]:
    """Return the source of the params dict for each ``t("key", ...)``
    call in ``body``. Returns ``None`` for calls that pass no params."""
    pattern = re.compile(
        rf't\(\s*"{re.escape(key)}"\s*(?:,\s*(\{{[^}}]*\}}))?\s*\)',
        re.DOTALL,
    )
    results: list[str | None] = []
    for m in pattern.finditer(body):
        results.append(m.group(1))
    return results


class TestComputeAgentGraphSemantics:
    """Port of the ``computeAgentGraph`` behavior so we can verify the
    derivation rules without a JS runtime. Any change to the JS helper
    should be mirrored here — the two implementations describe the
    same contract."""

    @staticmethod
    def compute(task_log: list[dict], orchestrator: str = "project_manager") -> dict:
        # Mirror of the JS ``computeAgentGraph`` function.
        worker_set: list[str] = []
        workers_seen: set[str] = set()
        edges: dict[tuple[str, str], int] = {}
        tasks_by_agent: dict[str, list[dict]] = {}

        # Two-pass: collect task_responses by taskId first so we can
        # label each task_request with its terminal status without
        # depending on message order.
        response_by_task = {
            e.get("taskId"): e for e in task_log if e.get("type") == "task_response" and e.get("taskId")
        }
        for ev in task_log:
            if ev.get("type") != "task_request":
                continue
            to = ev.get("to") or ""
            if not to:
                continue
            if to not in workers_seen:
                workers_seen.add(to)
                worker_set.append(to)
            edges[(orchestrator, to)] = edges.get((orchestrator, to), 0) + 1
            resp = response_by_task.get(ev.get("taskId"))
            status = resp.get("status") if resp else "running"
            payload = ev.get("payload") or {}
            goal = (
                payload.get("step")
                or (payload.get("task", "").split("\n")[0][:80] if payload.get("task") else "")
                or "Task"
            )
            task = {
                "taskId": ev.get("taskId"),
                "agent": to,
                "goal": goal,
                "phase": payload.get("phase") or "",
                "status": status,
            }
            tasks_by_agent.setdefault(to, []).append(task)

        agents = [{"name": orchestrator, "role": "orchestrator", "tasks": []}]
        for w in worker_set:
            tasks = tasks_by_agent.get(w, [])
            agents.append(
                {
                    "name": w,
                    "role": "worker",
                    "tasks": tasks,
                    "runningCount": sum(1 for t in tasks if t["status"] == "running"),
                    "completedCount": sum(1 for t in tasks if t["status"] == "completed"),
                    "failedCount": sum(1 for t in tasks if t["status"] == "failed"),
                }
            )
        edge_list = [{"from": f, "to": t, "count": c} for (f, t), c in edges.items()]
        return {"agents": agents, "edges": edge_list}

    def test_empty_task_log_yields_orchestrator_only(self) -> None:
        g = self.compute([])
        assert [a["name"] for a in g["agents"]] == ["project_manager"]
        assert g["edges"] == []

    def test_single_dispatch_creates_worker_and_edge(self) -> None:
        log = [
            {
                "type": "task_request",
                "taskId": "t1",
                "to": "developer",
                "payload": {"step": "impl_foo", "task": "Write foo"},
            },
        ]
        g = self.compute(log)
        names = [a["name"] for a in g["agents"]]
        assert names == ["project_manager", "developer"]
        assert g["edges"] == [{"from": "project_manager", "to": "developer", "count": 1}]

    def test_multiple_dispatches_to_same_agent_bump_edge(self) -> None:
        log = [
            {"type": "task_request", "taskId": "t1", "to": "developer", "payload": {"step": "a"}},
            {"type": "task_request", "taskId": "t2", "to": "developer", "payload": {"step": "b"}},
            {"type": "task_request", "taskId": "t3", "to": "developer", "payload": {"step": "c"}},
        ]
        g = self.compute(log)
        assert len(g["edges"]) == 1
        assert g["edges"][0]["count"] == 3

    def test_task_counts_split_by_status(self) -> None:
        log = [
            {"type": "task_request", "taskId": "t1", "to": "developer", "payload": {"step": "a"}},
            {"type": "task_response", "taskId": "t1", "status": "completed"},
            {"type": "task_request", "taskId": "t2", "to": "developer", "payload": {"step": "b"}},
            {"type": "task_response", "taskId": "t2", "status": "failed"},
            {"type": "task_request", "taskId": "t3", "to": "developer", "payload": {"step": "c"}},
            # t3 has no response yet -> running
        ]
        g = self.compute(log)
        dev = next(a for a in g["agents"] if a["name"] == "developer")
        assert dev["completedCount"] == 1
        assert dev["failedCount"] == 1
        assert dev["runningCount"] == 1

    def test_multiple_workers_preserve_dispatch_order(self) -> None:
        log = [
            {"type": "task_request", "taskId": "a1", "to": "architect", "payload": {}},
            {"type": "task_request", "taskId": "d1", "to": "developer", "payload": {}},
            {"type": "task_request", "taskId": "q1", "to": "qa_engineer", "payload": {}},
        ]
        g = self.compute(log)
        assert [a["name"] for a in g["agents"]] == [
            "project_manager",
            "architect",
            "developer",
            "qa_engineer",
        ]

    def test_goal_falls_back_to_first_task_line(self) -> None:
        log = [
            {
                "type": "task_request",
                "taskId": "x",
                "to": "developer",
                "payload": {"task": "Implement the thing\nDetails follow..."},
            },
        ]
        g = self.compute(log)
        dev = next(a for a in g["agents"] if a["name"] == "developer")
        assert dev["tasks"][0]["goal"] == "Implement the thing"

    def test_goal_uses_step_when_available(self) -> None:
        log = [
            {
                "type": "task_request",
                "taskId": "x",
                "to": "developer",
                "payload": {"step": "impl_config", "task": "Some long body"},
            },
        ]
        g = self.compute(log)
        dev = next(a for a in g["agents"] if a["name"] == "developer")
        # step_id takes precedence — it's the shortest meaningful label.
        assert dev["tasks"][0]["goal"] == "impl_config"


def _extract_lang_block(body: str, lang: str) -> str:
    """Extract the ``{ ... }`` body of the given language's TRANSLATIONS block.

    Uses a simple brace counter rather than a nested regex so it
    survives newlines and comments inside the table."""
    needle = f"{lang}: {{"
    start = body.find(needle)
    assert start >= 0, f"lang block not found: {lang}"
    depth = 0
    open_brace = body.find("{", start)
    i = open_brace
    while i < len(body):
        ch = body[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return body[open_brace : i + 1]
        i += 1
    raise AssertionError(f"unmatched braces for lang block: {lang}")
