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

            # First attempt.
            result = dispatch_rt.handle_message(
                task_description,
                on_todos_update=_on_todos_update,
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
                retry_prompt = _build_retry_prompt(task_description, result)
                result = dispatch_rt.handle_message(
                    retry_prompt,
                    on_todos_update=_on_todos_update,
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

    return [dispatch_task, dispatch_tasks_parallel]


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


def make_completion_tool(ctx: ToolContext) -> BaseTool:
    """Create the ``mark_complete`` primitive — the explicit terminal signal."""

    @tool
    def mark_complete(report: str) -> str:
        """Signal that the workflow is complete and provide the final report.

        After calling this, the orchestrator's continuation loop exits.
        Use ONCE, when all phases are done.

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
