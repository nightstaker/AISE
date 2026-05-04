"""Dispatch tools — dispatch_task / dispatch_tasks_parallel / dispatch_subsystems.

Kept in one factory because ``dispatch_subsystems`` and
``dispatch_tasks_parallel`` invoke the closure-captured ``dispatch_task``
tool directly.
"""

from __future__ import annotations

import concurrent.futures
import json
import threading
import uuid
from typing import Any

from langchain_core.tools import BaseTool, tool

from ..utils.logging import get_logger
from ._common import _now
from .artifacts import _artifact_shortfalls
from .context import ToolContext
from .retry import _MAX_DISPATCH_RETRIES, _build_retry_prompt
from .stack_contract import (
    _LANGUAGE_TOOLCHAIN,
    _interface_module_path,
    _load_stack_contract_block,
    _load_stack_contract_data,
)
from .task_descriptions import (
    _build_component_implementation_task,
    _build_subsystem_skeleton_task,
)

logger = get_logger(__name__)


def make_dispatch_tools(ctx: ToolContext) -> list[BaseTool]:
    """Create the dispatch_task and dispatch_tasks_parallel primitives."""

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
        from ..runtime.models import AgentState

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

            # First attempt. A path-policy rejection inside the agent
            # loop surfaces as an exception with the sentinel
            # "outside this project's root" in its message — that is
            # not a model failure, it's a sandbox guardrail tripping
            # because the LLM emitted a host-absolute path
            # (``/home/...`` / ``/tmp/...``). Re-dispatch ONCE with a
            # corrective preface that names the failure and reminds
            # the worker to use project-relative paths, instead of
            # marking the whole task failed (the prior behaviour
            # silently dropped core components in project_0-tower).
            try:
                result = dispatch_rt.handle_message(
                    worker_prompt,
                    on_todos_update=_on_todos_update,
                    on_token_usage=_on_token_usage,
                )
            except Exception as first_exc:
                if "outside this project's root" not in str(first_exc):
                    raise
                logger.info(
                    "Retrying task=%s after path-policy rejection: %s",
                    task_id,
                    first_exc,
                )
                corrective_prompt = (
                    "[Path-policy retry]\n"
                    "Your previous attempt was aborted by the project "
                    "sandbox because a tool call used an absolute host "
                    "path. The sandbox accepts only project-relative "
                    "paths (e.g. ``docs/foo.md``) or virtual-rooted "
                    "paths (``/docs/foo.md``). Re-issue every "
                    "``write_file`` / ``edit_file`` / ``read_file`` "
                    "with such a path. Never emit any path that starts "
                    "with /home, /tmp, /etc, /var, /usr, /opt, /root, "
                    "/mnt, /proc, /sys, /dev, /boot.\n\n"
                    f"Original task:\n{worker_prompt}"
                )
                result = dispatch_rt.handle_message(
                    corrective_prompt,
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

            # c5: real acceptance check after the retry loop exits.
            # Previously this branch unconditionally emitted
            # status="completed" regardless of whether expected_artifacts
            # were satisfied — orchestrators saw 100% green even when
            # the gate was failing on every retry. Now: if shortfalls
            # remain after all retries, status="incomplete" and the
            # missing artifact list is surfaced in the response.
            final_shortfalls = _artifact_shortfalls(ctx.project_root, expected_artifacts)
            output_len = len(result)
            preview = result[:500] + "..." if output_len > 500 else result
            status = "completed" if not final_shortfalls else "incomplete"
            payload: dict[str, Any] = {
                "output_preview": preview,
                "output_length": output_len,
                "retries": retries_used,
            }
            if final_shortfalls:
                payload["shortfalls"] = final_shortfalls
            response_msg = {
                "taskId": task_id,
                "from": agent_name,
                "to": "orchestrator",
                "type": "task_response",
                "status": status,
                "timestamp": _now(),
                "payload": payload,
            }
            ctx.emit(response_msg)
            log_fn = logger.info if status == "completed" else logger.warning
            log_fn(
                "Task %s: task=%s from=%s output=%d chars retries=%d shortfalls=%d",
                status,
                task_id,
                agent_name,
                output_len,
                retries_used,
                len(final_shortfalls),
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
        incomplete = sum(1 for r in results if r.get("status") == "incomplete")
        return json.dumps(
            {
                "parallel_results": results,
                "total": len(results),
                "completed": ok,
                "failed": fail,
                "incomplete": incomplete,
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
            # Empty interface_path means the language has no
            # per-folder barrel convention (C# / Unity / .NET /
            # Kotlin / Swift / unknown). Skip the artifact entry so
            # we don't demand a phantom ``__init__.py`` from a stack
            # that doesn't use one.
            if interface_path:
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
