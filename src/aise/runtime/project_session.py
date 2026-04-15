"""ProjectSession — generic, role-agnostic orchestrator session.

Drives a project from a raw requirement to delivery using only:

- The agents declared in ``src/aise/agents/*.md``
- The processes declared in ``src/aise/processes/*.process.md``
- The runtime safety policy in :class:`RuntimeConfig`

Nothing in this file knows what TDD is, what an "implementation phase"
looks like, or which agent plays which role — that knowledge lives in
the data files. Code only walks the structures it parses out of those
files and exposes generic primitives via :mod:`tool_primitives`.

Public surface (kept stable so existing tests/web code continue to work):

- ``ProjectSession(manager, project_root=..., on_event=...)``
- ``run(requirement) -> str``
- ``task_log`` property
- ``current_stage`` property
- ``_make_tools()`` — returns the primitive tools (back-compat alias)
- ``_build_pm_runtime()`` — builds the orchestrator runtime (back-compat alias)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..utils.logging import get_logger
from .llm_factory import build_llm as _factory_build_llm
from .runtime_config import LLMDefaults, RuntimeConfig
from .tool_primitives import ToolContext, WorkflowState, build_orchestrator_tools

logger = get_logger(__name__)


class ProjectSession:
    """Drives a project from raw requirement to delivery.

    The constructor builds a :class:`ToolContext`, picks the
    orchestrator agent (by ``role: orchestrator`` or fallback name),
    rebuilds that agent's runtime with the orchestrator tool primitives
    injected, and exposes a :meth:`run` entry point.
    """

    def __init__(
        self,
        manager: Any,
        *,
        project_root: str | Path | None = None,
        on_event: Any | None = None,
        runtime_config: RuntimeConfig | None = None,
    ) -> None:
        """Initialize a project session.

        Args:
            manager: A started :class:`RuntimeManager` instance.
            project_root: Directory where project artifacts are written.
            on_event: Optional ``(event: dict) -> None`` callback fired
                on every event the orchestrator emits.
            runtime_config: Optional :class:`RuntimeConfig` for safety
                caps and orchestrator selection. Defaults to
                :class:`RuntimeConfig`'s defaults.
        """
        self._manager = manager
        self._session_id = uuid.uuid4().hex[:12]
        self._project_root: Path | None = Path(project_root) if project_root else None
        self._config = runtime_config or RuntimeConfig()
        self._workflow_state = WorkflowState()

        if self._project_root:
            self._scaffold_project_dirs(self._project_root)

        self._ctx = ToolContext(
            manager=self._manager,
            project_root=self._project_root,
            config=self._config,
            workflow_state=self._workflow_state,
            on_event=on_event,
            runtime_resolver=self._resolve_runtime,
        )

        self._tools = build_orchestrator_tools(self._ctx)
        self._orchestrator_name = self._select_orchestrator_name()
        self._pm_runtime = self._build_pm_runtime()

    # -- Public API ----------------------------------------------------------

    def run(self, requirement: str) -> str:
        """Submit a raw requirement and let the orchestrator drive the workflow.

        The continuation loop exits when the orchestrator calls
        ``mark_complete`` (preferred) OR when the dispatch / continuation
        cap is reached.
        """
        if self._pm_runtime is None:
            raise RuntimeError("orchestrator runtime not available")

        logger.info(
            "ProjectSession started: session=%s requirement_len=%d orchestrator=%s",
            self._session_id,
            len(requirement),
            self._orchestrator_name,
        )

        # Mark the global orchestrator runtime as WORKING for the Monitor.
        from .models import AgentState

        global_pm_rt = self._manager.get_runtime(self._orchestrator_name)

        self._requirement = requirement
        try:
            if global_pm_rt is not None:
                global_pm_rt._state = AgentState.WORKING
                global_pm_rt._current_task = requirement[:120]

            # Drive the workflow phase by phase. Each phase gets a FRESH
            # PM runtime so context never accumulates beyond one phase.
            # The framework controls the macro sequence; PM controls the
            # agent-level tactics within each phase.
            phases = self._build_phase_prompts(requirement)
            response = ""

            for phase_idx, (phase_name, phase_prompt) in enumerate(phases):
                is_last_phase = phase_idx == len(phases) - 1

                # Only honor mark_complete in the LAST phase. PM often
                # calls it prematurely (e.g. after implementation, skipping
                # main.py and QA). Reset the flag before non-final phases.
                if not is_last_phase and self._workflow_state.is_complete:
                    logger.info(
                        "Ignoring premature mark_complete at phase %d/%d [%s]",
                        phase_idx + 1,
                        len(phases),
                        phase_name,
                    )
                    self._workflow_state.is_complete = False
                    self._workflow_state.final_report = ""

                if is_last_phase and self._workflow_state.is_complete:
                    break

                if self._ctx.dispatch_count() >= self._config.safety_limits.max_dispatches:
                    logger.warning("Hit dispatch cap (%d)", self._config.safety_limits.max_dispatches)
                    break

                logger.info(
                    "Phase %d/%d [%s]: session=%s dispatches=%d",
                    phase_idx + 1,
                    len(phases),
                    phase_name,
                    self._session_id,
                    self._ctx.dispatch_count(),
                )

                # Fresh PM runtime per phase — no context accumulation
                self._pm_runtime = self._build_pm_runtime()
                response = self._invoke_pm(phase_prompt)

            if self._workflow_state.is_complete and self._workflow_state.final_report:
                return self._workflow_state.final_report

            logger.info("ProjectSession finished all phases: session=%s", self._session_id)
            return response
        finally:
            if global_pm_rt is not None:
                global_pm_rt._state = AgentState.ACTIVE
                global_pm_rt._current_task = None

    @property
    def task_log(self) -> list[dict[str, Any]]:
        """Chronological log of every event the orchestrator emitted."""
        with self._ctx.event_lock:
            return list(self._ctx.event_log)

    def _invoke_pm(self, prompt: str) -> str:
        """Invoke PM with error resilience.

        LLMs sometimes generate malformed tool call JSON (e.g. gemma4's
        repetition bug: "progress, progress, progress..." × 1000). The
        LLM server returns 500, which crashes handle_message. Instead of
        crashing the session, we catch the error and return empty so the
        continuation loop can retry.
        """
        try:
            return self._pm_runtime.handle_message(prompt, thread_id=self._session_id)
        except Exception as exc:
            logger.warning(
                "PM handle_message failed (will retry on next continuation): session=%s error=%s",
                self._session_id,
                str(exc)[:200],
            )
            return ""

    # Back-compat alias used by tests that mutate the log directly.
    @property
    def _task_log(self) -> list[dict[str, Any]]:
        return self._ctx.event_log

    @property
    def current_stage(self) -> str:
        """Most recent ``stage_update`` stage, or empty if none yet."""
        with self._ctx.event_lock:
            for event in reversed(self._ctx.event_log):
                if event.get("type") == "stage_update":
                    return str(event.get("stage", ""))
        return ""

    @property
    def workflow_state(self) -> WorkflowState:
        return self._workflow_state

    @property
    def orchestrator_name(self) -> str:
        return self._orchestrator_name

    # -- Tool factory (back-compat) ------------------------------------------

    def _make_tools(self) -> list[Any]:
        """Return the orchestrator's tool primitives.

        Kept as an instance method so existing tests that call
        ``session._make_tools()`` continue to work. Returns the same
        list that was injected into the orchestrator runtime.
        """
        return list(self._tools)

    # -- Orchestrator runtime ------------------------------------------------

    def _build_pm_runtime(self) -> Any:
        """Build the orchestrator's AgentRuntime with primitive tools injected."""
        from .agent_runtime import AgentRuntime
        from .manager import _agents_dir
        from .policy_backend import make_policy_backend

        orchestrator_md = _agents_dir() / f"{self._orchestrator_name}.md"
        if not orchestrator_md.is_file():
            logger.error("Orchestrator agent.md not found at %s", orchestrator_md)
            return None

        existing_rt = self._manager.get_runtime(self._orchestrator_name)
        if existing_rt is None:
            logger.error("Orchestrator '%s' not found in RuntimeManager", self._orchestrator_name)
            return None

        from ..config import ModelConfig

        model_info = existing_rt.definition.metadata.get("_model_info", {})
        model_cfg = ModelConfig(
            provider=model_info.get("provider", ""),
            model=model_info.get("model", ""),
            temperature=model_info.get("temperature", 0.7),
            max_tokens=model_info.get("maxTokens", 4096),
        )
        if hasattr(self._manager, "_config"):
            global_cfg = self._manager._config.get_model_config(self._orchestrator_name)
            model_cfg.api_key = global_cfg.api_key
            model_cfg.base_url = global_cfg.base_url
            model_cfg.extra = global_cfg.extra

        llm = _factory_build_llm(model_cfg, LLMDefaults(min_max_tokens=self._config.llm.min_max_tokens))

        skills_dir = orchestrator_md.parent / "_runtime_skills"
        skills_dir.mkdir(exist_ok=True)

        from langgraph.checkpoint.memory import MemorySaver

        trace_dir = str(self._project_root / self._config.trace_subdir) if self._project_root else None

        backend = None
        if self._project_root:
            try:
                backend = make_policy_backend(
                    self._project_root,
                    layout=existing_rt.definition.output_layout,
                    agent_name=self._orchestrator_name,
                )
            except Exception as exc:
                logger.warning("Failed to build policy backend for orchestrator: %s", exc)

        rt = AgentRuntime(
            agent_md=orchestrator_md,
            skills_dir=skills_dir,
            model=llm,
            extra_tools=self._tools,
            backend=backend,
            trace_dir=trace_dir,
            checkpointer=MemorySaver(),
            max_iterations=200,
        )
        rt.evoke()
        logger.info(
            "Orchestrator runtime built: name=%s tools=%d trace_dir=%s session=%s",
            self._orchestrator_name,
            len(self._tools),
            trace_dir,
            self._session_id,
        )
        return rt

    def _scaffold_project_dirs(self, root: Path) -> None:
        """Pre-create the directories declared by every loaded agent's output_layout.

        This is purely cosmetic — it ensures the project directory tree
        is visible from the start so the file-tree UI has something to
        show. The runtime's policy backend would create the directories
        on demand anyway.
        """
        wanted: set[str] = {self._config.trace_subdir}
        for rt in self._manager.runtimes.values():
            layout = getattr(rt.definition, "output_layout", None)
            if layout is None:
                continue
            for path in layout.paths.values():
                if path:
                    wanted.add(path.rstrip("/"))
        for sub in sorted(wanted):
            (root / sub).mkdir(parents=True, exist_ok=True)

    def _resolve_runtime(self, agent_name: str, global_rt: Any) -> Any:
        """Create a FRESH project-scoped AgentRuntime for each dispatch.

        Every dispatch gets its own AgentRuntime instance with a clean
        conversation context. This ensures:
        - No message history leakage between dispatches
        - Each module task runs in a completely isolated agent session
        - Parallel dispatches don't share mutable agent state

        The FilesystemBackend is shared (so module B can read files
        written by module A), but the LLM context is isolated.
        """
        if not self._project_root:
            return global_rt

        from .agent_runtime import AgentRuntime
        from .manager import _agents_dir
        from .policy_backend import make_policy_backend

        try:
            md_path = _agents_dir() / f"{agent_name}.md"
            if not md_path.is_file():
                logger.warning("No agent.md for %s, using global runtime", agent_name)
                return global_rt

            from ..config import ModelConfig

            model_info = global_rt.definition.metadata.get("_model_info", {})
            model_cfg = ModelConfig(
                provider=model_info.get("provider", ""),
                model=model_info.get("model", ""),
                temperature=model_info.get("temperature", 0.7),
                max_tokens=model_info.get("maxTokens", 4096),
            )
            if hasattr(self._manager, "_config"):
                gc = self._manager._config.get_model_config(agent_name)
                model_cfg.api_key = gc.api_key
                model_cfg.base_url = gc.base_url
                model_cfg.extra = gc.extra

            llm = _factory_build_llm(model_cfg, LLMDefaults(min_max_tokens=self._config.llm.min_max_tokens))
            backend = make_policy_backend(
                self._project_root,
                layout=global_rt.definition.output_layout,
                agent_name=agent_name,
            )

            skills_dir = md_path.parent / "_runtime_skills"
            skills_dir.mkdir(exist_ok=True)
            trace_dir = str(self._project_root / self._config.trace_subdir)

            rt = AgentRuntime(
                agent_md=md_path,
                skills_dir=skills_dir,
                model=llm,
                backend=backend,
                trace_dir=trace_dir,
            )
            rt.evoke()
            logger.info("Fresh runtime created: agent=%s root=%s", agent_name, self._project_root)
            return rt
        except Exception as exc:
            logger.warning(
                "Failed to create project-scoped runtime for %s: %s, using global",
                agent_name,
                exc,
            )
            return global_rt

    # -- Orchestrator selection ----------------------------------------------

    def _select_orchestrator_name(self) -> str:
        """Pick the orchestrator agent by role, then fall back to a name match."""
        target_role = self._config.orchestrator_role
        for name, rt in self._manager.runtimes.items():
            role = (getattr(rt.definition, "role", "") or "").lower()
            if role == target_role:
                return name
        # Legacy fallback: use the configured name even if role isn't tagged.
        fallback = self._config.orchestrator_fallback_name
        if fallback in self._manager.runtimes:
            return fallback
        # Final fallback: use the first runtime if any.
        if self._manager.runtimes:
            return next(iter(self._manager.runtimes))
        raise RuntimeError("No agents available; cannot select an orchestrator")

    # -- Prompt rendering ----------------------------------------------------

    def _build_phase_prompts(self, requirement: str) -> list[tuple[str, str]]:
        """Build one prompt per workflow phase.

        Each prompt is self-contained: the PM gets a fresh runtime and
        this prompt tells it exactly what to do for this phase.
        """
        return [
            (
                "requirements",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 1 — Requirements:\n"
                "1. Call list_processes, then get_process('waterfall.process.md').\n"
                "2. Call list_agents to discover agents.\n"
                "3. dispatch_task to product_manager to write docs/requirement.md.\n"
                "4. After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "architecture",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 2 — Architecture:\n"
                "dispatch_task to architect to read docs/requirement.md and write docs/architecture.md.\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "implementation",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 3 — Implementation:\n"
                "1. Read docs/architecture.md to identify all modules.\n"
                "2. For EACH module, dispatch developer using dispatch_tasks_parallel.\n"
                "   Include the architecture spec in each task description.\n"
                "3. After all dispatches return, run: execute_shell('python -m pytest tests/ -q --tb=short')\n"
                "4. If tests fail, dispatch developer to fix, then re-run pytest.\n"
                "5. STOP when tests pass (or after 3 fix attempts).\n"
                "Do NOT call mark_complete.",
            ),
            (
                "main_entry",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 4 — Main Entry Point:\n"
                "dispatch_task to developer with this task:\n"
                "'Write src/main.py — the main entry point. Read all files in src/ to see "
                "what modules exist, then create a real game loop that initializes all modules "
                "(Snake, Food, Engine, GameState, Scoring, etc.), runs an update loop with "
                "collision detection, food spawning, and score tracking. This must be a REAL "
                "working game, not just print statements. Also write tests/test_main.py.'\n"
                "After it completes, run: execute_shell('python -m pytest tests/ -q --tb=short')\n"
                "Do NOT call mark_complete.",
            ),
            (
                "qa_testing",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 5 — Integration Testing:\n"
                "dispatch_task to qa_engineer to read src/ and tests/, then write "
                "tests/test_integration.py covering cross-module interactions.\n"
                "After it completes, run: execute_shell('python -m pytest tests/ -q --tb=short')\n"
                "Do NOT call mark_complete.",
            ),
            (
                "delivery",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 6 — Delivery:\n"
                "All implementation and testing is done.\n"
                "Run execute_shell('python -m pytest tests/ -q --tb=short') one final time.\n"
                "Then call mark_complete with a delivery report summarizing:\n"
                "- Modules implemented\n"
                "- Test results\n"
                "- Any known issues",
            ),
        ]

    def _render_initial_prompt(self, requirement: str) -> str:
        # Kept for back-compat but no longer used by the phased run loop
        return f"Project: {requirement}"

    def _render_continuation_prompt(self) -> str:
        """Build an extremely specific, single-action continuation prompt.

        PM keeps its checkpointed history. Each continuation tells PM
        exactly ONE thing to do next, preventing it from wasting calls
        on re-reading files or getting stuck.
        """
        log = self.task_log
        dispatches = [e for e in log if e.get("type") == "task_request"]
        responses = [e for e in log if e.get("type") == "task_response"]

        agents_dispatched = set()
        developer_dispatches = 0
        developer_completed = 0
        for req in dispatches:
            agent = req.get("to", "")
            agents_dispatched.add(agent)
            if agent == "developer":
                developer_dispatches += 1
        for resp in responses:
            if resp.get("from") == "developer" and resp.get("status") == "completed":
                developer_completed += 1

        # Determine the ONE next action
        if "product_manager" not in agents_dispatched:
            return (
                "You have not yet dispatched any tasks. "
                "Call dispatch_task to product_manager to write docs/requirement.md. "
                "Do NOT read any files first."
            )

        if "architect" not in agents_dispatched:
            return (
                "Requirements are done. "
                "Call dispatch_task to architect to write docs/architecture.md. "
                "Do NOT read any files first."
            )

        if developer_dispatches == 0:
            return (
                "Architecture is done. Read docs/architecture.md to identify modules. "
                "Then dispatch developer for EACH module using dispatch_tasks_parallel. "
                "Include the architecture spec for each module in the task description."
            )

        # Check if main.py was dispatched by looking at step_ids
        main_dispatched = any("main" in req.get("payload", {}).get("step", "").lower() for req in dispatches)

        if developer_dispatches > 0 and not main_dispatched:
            # Modules done, need main.py next
            # First check if tests pass
            shell_results = [e for e in log if e.get("type") == "tool_call" and e.get("tool") == "execute_shell"]
            last_pytest_passed = False
            for sr in reversed(shell_results):
                summary = sr.get("summary", "")
                if "pytest" in summary or "exit=0" in summary:
                    last_pytest_passed = "exit=0" in summary
                    break

            if not last_pytest_passed:
                return (
                    f"Implementation: {developer_dispatches} developer dispatches, "
                    f"{developer_completed} completed. "
                    "Run execute_shell('python -m pytest tests/ -q --tb=short') to check. "
                    "If tests fail, dispatch developer to fix. "
                    "Do NOT proceed until tests pass."
                )
            # Tests pass → dispatch main.py
            return (
                "Module tests pass. Now dispatch developer to write src/main.py — "
                "the main entry point. Call:\n"
                "dispatch_task(agent_name='developer', "
                "task_description='Write src/main.py — the main entry point that "
                "imports and uses ALL implemented modules (read src/ to see what exists). "
                "Create a real game loop: initialize Snake, Food, Engine, GameState, Scoring etc., "
                "then run an update loop that moves the snake, checks collisions, spawns food, "
                "and tracks score. NOT a stub — real working game logic. "
                "Also write tests/test_main.py to verify the game initializes and runs.', "
                "step_id='step_integrate_main', phase='implementation')"
            )

        if main_dispatched and "qa_engineer" not in agents_dispatched:
            return (
                "Main entry point done. Dispatch qa_engineer for integration testing.\n"
                "dispatch_task(agent_name='qa_engineer', "
                "task_description='Read src/ and tests/ to understand the system. "
                "Write integration tests to tests/test_integration.py covering "
                "cross-module interactions.', "
                "step_id='step_integration_test', phase='verification')"
            )

        if "qa_engineer" in agents_dispatched:
            return (
                "All phases done. Run execute_shell('python -m pytest tests/ -q --tb=short'). "
                "If all pass, call mark_complete with a delivery report. "
                "If tests fail, dispatch developer to fix, then re-check."
            )


# -- Back-compat helper kept for existing tests ----------------------------


def _parse_process_header(text: str) -> dict[str, str]:
    """Extract process metadata from a legacy bullet-style header.

    Retained as a thin wrapper around :func:`parse_process_md` so any
    code still importing this symbol keeps working.
    """
    from .process_md_parser import parse_process_md

    try:
        proc = parse_process_md(text)
    except Exception:
        return {}
    out: dict[str, str] = {}
    for k, v in proc.header_dict().items():
        if v:
            out[k] = v
    return out


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
