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
        mode: str = "initial",
        process_type: str = "waterfall",
        start_phase_idx: int = 0,
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
            mode: ``"initial"`` (default — clean-slate run) or
                ``"incremental"`` (dispatch new requirement on a project
                that already has a baseline). Incremental mode rewrites
                the phase prompts to instruct agents to READ existing
                artifacts first and only add / update what the new
                requirement demands.
            process_type: ``"waterfall"`` (default) or ``"agile"``.
                Selects the phase-prompt set that drives the orchestrator.
                Agile swaps the waterfall linear lifecycle for an MVP-
                centered sprint sequence (planning → execution → review
                → retrospective → delivery).
            start_phase_idx: Zero-based phase index to begin at. Defaults
                to 0 (run every phase). Retry-from-failure wraps this
                so a resumed session skips phases that already finished
                — the artifacts on disk from the prior attempt stay in
                place, and downstream agents re-read them as usual.
        """
        self._manager = manager
        self._session_id = uuid.uuid4().hex[:12]
        self._project_root: Path | None = Path(project_root) if project_root else None
        self._config = runtime_config or RuntimeConfig()
        self._workflow_state = WorkflowState()
        raw_mode = str(mode or "initial").strip().lower()
        self._mode = raw_mode if raw_mode in ("initial", "incremental") else "initial"
        raw_process = str(process_type or "waterfall").strip().lower()
        self._process_type = raw_process if raw_process in ("waterfall", "agile") else "waterfall"
        try:
            start_idx = int(start_phase_idx)
        except (TypeError, ValueError):
            start_idx = 0
        self._start_phase_idx = max(0, start_idx)

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
        # Make the raw requirement visible to every dispatch so workers
        # can read it directly and mirror the user's natural language
        # in any docs/*.md they write (see tool_primitives.dispatch_task
        # for the prefix format, and architect.md / product_manager.md /
        # qa_engineer.md "Document Language" sections for the rule).
        self._ctx.original_requirement = requirement
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
            total_phases = len(phases)
            # Broadcast the planned phase layout so the UI can pre-render
            # the stepper even before the first agent dispatch. Emitting
            # once at the top keeps downstream event processing simple.
            self._ctx.emit(
                {
                    "type": "phase_plan",
                    "phases": [name for name, _prompt in phases],
                    "total": total_phases,
                    "start_phase_idx": self._start_phase_idx,
                    "timestamp": _now(),
                }
            )
            if self._start_phase_idx and self._start_phase_idx < total_phases:
                logger.info(
                    "Resuming session=%s at phase %d/%d",
                    self._session_id,
                    self._start_phase_idx + 1,
                    total_phases,
                )
                self._ctx.emit(
                    {
                        "type": "phase_resume",
                        "phase_idx": self._start_phase_idx,
                        "phase_name": phases[self._start_phase_idx][0],
                        "total": total_phases,
                        "timestamp": _now(),
                    }
                )

            for phase_idx, (phase_name, phase_prompt) in enumerate(phases):
                if phase_idx < self._start_phase_idx:
                    # Resumed session skipping an earlier, already-completed
                    # phase. Don't emit phase_start / phase_complete for
                    # skipped phases — the UI uses missing events as the
                    # signal that the phase was not re-run this session.
                    continue

                is_last_phase = phase_idx == total_phases - 1

                # Only honor mark_complete in the LAST phase. PM often
                # calls it prematurely (e.g. after implementation, skipping
                # main.py and QA). Reset the flag before non-final phases.
                if not is_last_phase and self._workflow_state.is_complete:
                    logger.info(
                        "Ignoring premature mark_complete at phase %d/%d [%s]",
                        phase_idx + 1,
                        total_phases,
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
                    total_phases,
                    phase_name,
                    self._session_id,
                    self._ctx.dispatch_count(),
                )
                # Bracket each phase with start/complete events so the
                # retry-from-failure path has a deterministic record of
                # which phase was the last to BEGIN (but never complete).
                self._ctx.emit(
                    {
                        "type": "phase_start",
                        "phase_idx": phase_idx,
                        "phase_name": phase_name,
                        "total": total_phases,
                        "timestamp": _now(),
                    }
                )

                # Fresh PM runtime per phase — no context accumulation
                self._pm_runtime = self._build_pm_runtime()
                response = self._invoke_pm(phase_prompt)

                self._ctx.emit(
                    {
                        "type": "phase_complete",
                        "phase_idx": phase_idx,
                        "phase_name": phase_name,
                        "total": total_phases,
                        "timestamp": _now(),
                    }
                )

                # Post-phase hooks (pure-Python, LLM-free). Run after
                # every phase so incremental runs can still refresh the
                # project-root config if the dominant language changed.
                self._run_post_phase_hooks(phase_idx, phase_name)

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
            max_iterations=240,
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

    # Phases after which the language-config generator should run. Kept
    # as a small set so adding a new process_type with different phase
    # names (e.g. a hypothetical ``kanban``) just means extending this
    # tuple. Running after ``main_entry`` / ``sprint_main_entry``
    # guarantees the entry command is known; running after QA adds a
    # safety net for processes that skip the main-entry phase entirely.
    _POST_PHASE_LANG_CONFIG = frozenset(
        {
            "main_entry",
            "sprint_main_entry",
            "qa_testing",
            "sprint_review",
        }
    )

    def _run_post_phase_hooks(self, phase_idx: int, phase_name: str) -> None:
        """Pure-Python hooks that run after each successful phase.

        The only hook today is the language-idiomatic root config
        generator (pyproject.toml / package.json / go.mod / Cargo.toml
        / pom.xml). It's gated by phase so it doesn't run before the
        developer has produced any source. Any failure here is logged
        and swallowed — a broken post-phase hook must never mark the
        whole run as failed.
        """
        if phase_name not in self._POST_PHASE_LANG_CONFIG:
            return
        if self._project_root is None:
            return
        from .lang_config import generate_root_config

        try:
            project_name = self._project_root.name or ""
            # Strip the leading "project_N-" prefix so the package name
            # is the human-friendly slug, not the internal id.
            if "-" in project_name:
                _prefix, _sep, remainder = project_name.partition("-")
                if _prefix.startswith("project_"):
                    project_name = remainder or project_name
            run_command = self._extract_last_run_command()
            result = generate_root_config(
                self._project_root,
                project_name=project_name,
                run_command=run_command,
            )
        except Exception as exc:
            logger.warning(
                "Language config generation failed (post-phase %s): %s",
                phase_name,
                exc,
            )
            return
        self._ctx.emit(
            {
                "type": "language_config",
                "phase_idx": phase_idx,
                "phase_name": phase_name,
                "language": result.get("language"),
                "path": result.get("path"),
                "created": bool(result.get("created")),
                "skipped": bool(result.get("skipped")),
                "reason": result.get("reason", ""),
                "timestamp": _now(),
            }
        )
        if result.get("created"):
            logger.info(
                "Generated %s (%s) after phase %s",
                result.get("path"),
                result.get("language"),
                phase_name,
            )

    def _extract_last_run_command(self) -> str:
        """Pull the most recent ``RUN: <cmd>`` line out of the task log.

        The main-entry phase instructs the developer to end its response
        with exactly one line of the form ``RUN: <command>``. That
        command is echoed back through the orchestrator's
        ``task_response`` event as ``output_preview``. The language-
        config generator uses it to fill in per-language entry-point
        metadata (e.g. the ``[project.scripts]`` table for Python).
        """
        log = self.task_log
        for event in reversed(log):
            if event.get("type") != "task_response":
                continue
            preview = str(event.get("output_preview", "") or event.get("output", ""))
            if not preview:
                continue
            for line in preview.splitlines():
                stripped = line.strip()
                if stripped.upper().startswith("RUN:"):
                    return stripped.split(":", 1)[1].strip()
        return ""

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

        Branches on ``self._mode``: ``"incremental"`` produces a
        different prompt set that instructs every agent to READ the
        existing artifacts first and only add / update what the new
        requirement demands. The QA phase stays full (runs the whole
        test suite, not just new tests) regardless of mode.
        """
        if self._process_type == "agile":
            if self._mode == "incremental":
                return self._build_agile_incremental_phase_prompts(requirement)
            return self._build_agile_initial_phase_prompts(requirement)
        if self._mode == "incremental":
            return self._build_incremental_phase_prompts(requirement)
        return self._build_initial_phase_prompts(requirement)

    def _build_incremental_phase_prompts(self, requirement: str) -> list[tuple[str, str]]:
        """Phase prompts for a follow-up requirement on an established
        project. The contract is:

        - Phase 1 (requirement) — APPEND to ``docs/requirement.md``
          under a dated "Incremental Requirement" section. Do not
          rewrite or reorder the existing document.
        - Phase 2 (architecture) — read the existing architecture
          document and ADD / UPDATE only the sections the new
          requirement affects. The document should grow, not shrink.
        - Phase 3 (implementation) — developers read the existing
          ``src/`` and only implement the NEW or CHANGED modules the
          new requirement needs. Unrelated modules stay untouched.
        - Phase 4 (main entry) — re-verify the existing entry still
          boots; only write a new entry if none exists.
        - Phase 5 (qa testing) — **FULL** test suite, not just new
          integration tests. Incremental changes can silently break
          existing flows; the full pass is the safety net.
        - Phase 6 (delivery) — report scoped to the new requirement:
          what was added, what existing modules were touched, pass
          rate of the full suite after the change.
        """
        return [
            (
                "requirements",
                f"New requirement to integrate: {requirement}\n\n"
                "Execute Phase 1 — Requirements (INCREMENTAL):\n"
                "1. Call list_processes, then get_process('waterfall.process.md').\n"
                "2. Call list_agents to discover agents.\n"
                "3. dispatch_task to product_manager. In the task description,\n"
                "   require the PM to FIRST read docs/requirement.md (the\n"
                "   existing requirement document from prior runs), then\n"
                "   APPEND a new '## Incremental Requirement (<ISO date>)'\n"
                "   section at the end. Do NOT rewrite, renumber, or reorder\n"
                "   existing requirements. Every new requirement bullet in\n"
                "   the appended section MUST carry its own Mermaid use case\n"
                "   diagram (flowchart LR with actor / use case nodes — see\n"
                "   product_manager.md). After writing, the PM validates\n"
                "   every ```mermaid block via the mermaid skill and fixes\n"
                "   any syntax error before responding.\n"
                "   Pass expected_artifacts=['docs/requirement.md'].\n"
                "4. After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "architecture",
                f"New requirement to integrate: {requirement}\n\n"
                "Execute Phase 2 — Architecture (INCREMENTAL):\n"
                "dispatch_task to architect. Require the architect to FIRST\n"
                "read docs/architecture.md (the existing architecture from\n"
                "prior runs) + docs/requirement.md (including the new\n"
                "Incremental Requirement section). Then ADD / UPDATE only\n"
                "the sections the new requirement affects: new modules, new\n"
                "data flows, new API contracts, updated C4 diagrams for\n"
                "containers / components that gained responsibilities.\n"
                "Preserve every existing section that the new requirement\n"
                "does not touch. The document should grow, not shrink.\n"
                "Architecture views MUST stay C4 (C4Context / C4Container /\n"
                "C4Component); behavioral views stay on standard Mermaid\n"
                "types. Validate every ```mermaid block via the mermaid\n"
                "skill and fix any syntax error before responding.\n"
                "Pass expected_artifacts=['docs/architecture.md'].\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "implementation",
                f"New requirement to integrate: {requirement}\n\n"
                "Execute Phase 3 — Implementation (INCREMENTAL, TDD):\n"
                "1. Read docs/architecture.md to see which modules are NEW or\n"
                "   CHANGED because of the incremental requirement. Existing\n"
                "   modules the requirement does not touch must stay\n"
                "   untouched — read them only to understand interfaces.\n"
                "2. For EACH new-or-changed module, dispatch developer via\n"
                "   dispatch_tasks_parallel. In each task description:\n"
                "   - Include the relevant architecture spec.\n"
                "   - Instruct strict TDD: write tests/test_<module>.py, then\n"
                "     src/<module>.py, then run ONLY that module's test file\n"
                "     (python -m pytest tests/test_<module>.py -q --tb=short).\n"
                "     Up to 3 fix attempts.\n"
                "   - For CHANGED modules, the task description must say\n"
                "     explicitly that the file already exists and the\n"
                "     developer must EDIT it in place (edit_file), not\n"
                "     rewrite. Existing tests must keep passing — new tests\n"
                "     extend the file, not replace it.\n"
                "   - Set expected_artifacts=['src/<module>.py',\n"
                "     'tests/test_<module>.py'].\n"
                "3. Do NOT run the full suite here. That is Phase 5's job.\n"
                "4. When all dispatches return, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "main_entry",
                f"New requirement to integrate: {requirement}\n\n"
                "Execute Phase 4 — Main Entry Point (INCREMENTAL, verify-only):\n"
                "1. Check whether a main entry already exists (list src/ for\n"
                "   main.py / index.js / main.go / main.rs / etc.). If it\n"
                "   does, SKIP dispatching to the developer and jump straight\n"
                "   to step 3 using the existing RUN command.\n"
                "2. If no entry exists (rare for incremental runs), follow\n"
                "   the initial-mode Phase 4 protocol — dispatch developer\n"
                "   to write the entry file, extract the RUN: line.\n"
                "3. Run the RUN command with execute_shell(timeout=5).\n"
                "   Same interpretation as initial mode:\n"
                "   - timeout after 5s → SUCCESS (main loop entered).\n"
                "   - exit_code 0 with normal output → SUCCESS.\n"
                "   - exit_code != 0 with ImportError / SyntaxError /\n"
                "     ModuleNotFoundError / NameError / AttributeError at\n"
                "     top level or startup failure → FAILURE.\n"
                "4. If the verification FAILS, dispatch developer with the\n"
                "   failure text and request a fix. Up to 3 attempts.\n"
                "5. STOP after verification succeeds OR 3 attempts exhausted.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "qa_testing",
                f"New requirement to integrate: {requirement}\n\n"
                "Execute Phase 5 — Integration Testing (FULL suite, not\n"
                "partial). Even though implementation was incremental, the\n"
                "test run is FULL — new changes can silently break existing\n"
                "flows and only the full suite catches that.\n"
                "dispatch_task to qa_engineer. The task description must:\n"
                "- Instruct the QA agent to read docs/requirement.md\n"
                "  (including the new Incremental Requirement section) and\n"
                "  docs/architecture.md so it knows what to cover.\n"
                "- Extend tests/test_integration.py (edit in place — do\n"
                "  NOT recreate the file from scratch) with integration\n"
                "  scenarios for the new requirement. Existing integration\n"
                "  tests must keep running.\n"
                "- RUN the FULL suite:\n"
                '  execute(command="python -m pytest tests/ -q --tb=short")\n'
                "  and iterate up to 3 times until all tests pass.\n"
                "- Report final pass/fail counts in the response.\n"
                "Pass expected_artifacts=['tests/test_integration.py'].\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "delivery",
                f"New requirement to integrate: {requirement}\n\n"
                "Execute Phase 6 — Delivery Report (INCREMENTAL scope):\n\n"
                "Collect delta metrics for this incremental run and have\n"
                "product_manager write a scoped delivery report. Cite real\n"
                "tool outputs — do not guess numbers.\n\n"
                "1. Collect incremental metrics:\n"
                "   a) New or modified source files since the previous\n"
                "      baseline run. Use git where available:\n"
                "      execute_shell('git status --short 2>/dev/null || echo not-a-git-repo')\n"
                "      execute_shell('git diff --name-only HEAD~1 2>/dev/null || true')\n"
                "      Fall back to find -newer if git is not in play.\n"
                "   b) Current source file count and LOC (full project):\n"
                "      execute_shell('find src -type f -name \"*.py\" | wc -l')\n"
                "      execute_shell('find src -type f -name \"*.py\" -exec wc -l {} + | sort -rn | head -30')\n"
                "   c) Test count + FULL suite result:\n"
                "      execute_shell('find tests -type f -name \"test_*.py\" 2>/dev/null | wc -l')\n"
                "      execute_shell('python -m pytest tests/ --collect-only -q 2>&1 | tail -5')\n"
                "      execute_shell('python -m pytest tests/ -q --tb=line 2>&1 | tail -20')\n\n"
                "2. Dispatch product_manager to write docs/delivery_report.md.\n"
                "   Pass expected_artifacts=['docs/delivery_report.md'].\n"
                "   Require the report to cover:\n"
                "   - Executive Summary — one paragraph scoped to the new\n"
                "     requirement and whether the project remains production-ready.\n"
                "   - Incremental Delta — bullet list of modules added and\n"
                "     modules edited. Cite step a) outputs.\n"
                "   - Full Implementation Metrics — counts from step b).\n"
                "   - Testing Metrics — FULL-suite pass/fail/skipped from\n"
                "     step c). Pass rate as a percentage.\n"
                "   - Known Issues — failing tests with short descriptions,\n"
                "     or 'none' if green.\n"
                "   - Conclusion — one or two sentences on readiness AFTER\n"
                "     the incremental change.\n"
                "   EMBED the raw tool outputs into the task description so\n"
                "   PM cites them verbatim (same protocol as initial Phase 6).\n\n"
                "3. After product_manager returns, call mark_complete with a\n"
                "   short paragraph that references docs/delivery_report.md.\n"
                "   Include: project name, 'incremental', pass rate, number\n"
                "   of new modules + edited modules, and whether the entry\n"
                "   point verified successfully in Phase 4.",
            ),
        ]

    def _build_agile_initial_phase_prompts(self, requirement: str) -> list[tuple[str, str]]:
        """Agile phase prompts for a clean-slate project.

        Follows ``src/aise/processes/agile.process.md`` — a sprint-centric
        lifecycle: Sprint Planning → Sprint Execution (light design +
        rapid TDD + working main) → Sprint Review → Retrospective →
        Delivery. The structure is explicitly different from waterfall:
        design is LIGHTWEIGHT, implementation is MVP-scoped, and a
        retrospective phase captures process feedback.
        """
        return [
            (
                "sprint_planning",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 1 — Sprint Planning (AGILE):\n"
                "1. Call list_processes, then get_process('agile.process.md').\n"
                "2. Call list_agents to discover agents.\n"
                "3. dispatch_task to product_manager. Require the PM to:\n"
                "   - Break the raw requirement into user stories using the\n"
                "     'As a <role>, I want <goal>, so that <value>' pattern.\n"
                "   - For each story write Acceptance Criteria (Given/When/Then)\n"
                "     and a Definition of Done (DoD).\n"
                "   - Mark which stories are IN SCOPE for the first sprint's\n"
                "     MVP vs deferred. Favor shipping something end-to-end\n"
                "     over completeness.\n"
                "   - Write everything to docs/product_backlog.md. Every\n"
                "     story MUST carry its own Mermaid use case diagram\n"
                "     (flowchart LR with actor/use-case nodes — see\n"
                "     product_manager.md).\n"
                "   - Validate every ```mermaid block via the mermaid skill\n"
                "     and fix any syntax error before responding.\n"
                "   Pass expected_artifacts=['docs/product_backlog.md'].\n"
                "4. STOP. Do NOT call mark_complete.",
            ),
            (
                "sprint_design",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 2a — Lightweight Sprint Design (AGILE):\n"
                "dispatch_task to architect. Require the architect to:\n"
                "- Read docs/product_backlog.md.\n"
                "- Produce docs/sprint_design.md with a LIGHTWEIGHT design\n"
                "  scoped to the MVP stories only. Include: module\n"
                "  decomposition (tables of modules with 1-line responsibility\n"
                "  and public interface), data flow, and just ONE C4Container\n"
                "  diagram (skip deep C4Component unless strictly necessary —\n"
                "  this is a sprint, not a waterfall design phase).\n"
                "- Keep deferred stories out of the design; they will drive\n"
                "  a future sprint.\n"
                "- Validate every ```mermaid block via the mermaid skill and\n"
                "  fix any syntax error before responding.\n"
                "Pass expected_artifacts=['docs/sprint_design.md'].\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "sprint_execution",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 2b — Sprint Execution (AGILE, rapid TDD):\n"
                "1. Read docs/sprint_design.md to identify the MVP modules.\n"
                "2. For EACH MVP module, dispatch developer via\n"
                "   dispatch_tasks_parallel. Each task description must:\n"
                "   - Include the module's spec from sprint_design.md.\n"
                "   - Instruct strict TDD: write tests/test_<module>.py,\n"
                "     then src/<module>.py, then run ONLY that module's test\n"
                "     file (python -m pytest tests/test_<module>.py -q\n"
                "     --tb=short). Up to 3 fix attempts.\n"
                "   - Keep each module small enough to ship within the sprint.\n"
                "     If a design element is large, reduce scope rather than\n"
                "     stretching the sprint.\n"
                "   - Set expected_artifacts=['src/<module>.py',\n"
                "     'tests/test_<module>.py'].\n"
                "3. When all dispatches return, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "sprint_main_entry",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 2c — Working Entry Point (AGILE):\n"
                "1. dispatch_task to developer: 'Write the project's main\n"
                "   entry-point file that wires all MVP modules together so\n"
                "   the sprint output can be demoed at review. Use the\n"
                "   language convention (src/main.py for Python, src/index.js\n"
                "   for Node, cmd/<app>/main.go for Go, etc.). The file MUST\n"
                "   boot directly (python src/main.py, node src/index.js,\n"
                "   go run …). End your response with ONE line:\n"
                "       RUN: <command to launch>'\n"
                "2. Run the RUN command with execute_shell(timeout=5).\n"
                "   - timeout after 5s → SUCCESS (entered main loop).\n"
                "   - exit_code 0 with normal output → SUCCESS.\n"
                "   - exit_code != 0 with ImportError / SyntaxError /\n"
                "     ModuleNotFoundError / NameError / AttributeError or\n"
                "     missing-module startup failures → FAILURE.\n"
                "3. If FAILURE, dispatch developer again with the failure\n"
                "   text. Up to 3 attempts total.\n"
                "4. STOP. Do NOT call mark_complete.",
            ),
            (
                "sprint_review",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 3 — Sprint Review & Demo (AGILE):\n"
                "dispatch_task to qa_engineer. Require the QA agent to:\n"
                "- Read docs/product_backlog.md AND docs/sprint_design.md.\n"
                "- Write tests/test_integration.py (ONLY integration tests —\n"
                "  developers already wrote per-module unit tests). Cover\n"
                "  every MVP user story's acceptance criteria end-to-end.\n"
                '- RUN the FULL suite: execute(command="python -m pytest\n'
                '  tests/ -q --tb=short") and iterate up to 3 times until\n'
                "  tests pass.\n"
                "- Write docs/sprint_review.md with a per-user-story\n"
                "  PASS/FAIL table so the product owner can verify delivery\n"
                "  during review. Include pytest final summary.\n"
                "Pass expected_artifacts=['tests/test_integration.py',\n"
                "'docs/sprint_review.md'].\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "sprint_retrospective",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 4 — Sprint Retrospective (AGILE):\n"
                "dispatch_task to project_manager. Require the PM to write\n"
                "docs/sprint_retrospective.md covering:\n"
                "- What went well (which agents finished cleanly, which\n"
                "  tests passed first try).\n"
                "- What did not go well (failed dispatches, retries burned,\n"
                "  modules that stretched).\n"
                "- Action items for the next sprint (process changes,\n"
                "  scope adjustments, additional tests to write).\n"
                "The retrospective should ground itself in observable\n"
                "metrics — have the PM look at docs/, src/, tests/ and\n"
                "describe real outcomes, not speculation.\n"
                "Pass expected_artifacts=['docs/sprint_retrospective.md'].\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "delivery",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 5 — Sprint Delivery Report (AGILE):\n\n"
                "Collect real metrics then have product_manager write the\n"
                "report. Do NOT guess numbers.\n\n"
                "1. Collect metrics via execute_shell:\n"
                "   a) Source file count:\n"
                "      execute_shell('find src -type f -name \"*.py\" | wc -l')\n"
                "   b) Source LOC (top files + total):\n"
                "      execute_shell('find src -type f -name \"*.py\" -exec wc -l {} + | sort -rn | head -30')\n"
                "   c) Test files + collected cases:\n"
                "      execute_shell('find tests -type f -name \"test_*.py\" 2>/dev/null | wc -l')\n"
                "      execute_shell('python -m pytest tests/ --collect-only -q 2>&1 | tail -5')\n"
                "   d) Final pytest summary:\n"
                "      execute_shell('python -m pytest tests/ -q --tb=line 2>&1 | tail -20')\n\n"
                "2. Dispatch product_manager to write docs/delivery_report.md.\n"
                "   Pass expected_artifacts=['docs/delivery_report.md'].\n"
                "   Require the report to cover:\n"
                "   1. MVP Summary — one paragraph on what shipped this sprint\n"
                "      and whether it meets the DoD of the in-scope stories.\n"
                "   2. User Stories Shipped vs Deferred — table with story ID,\n"
                "      title, status (shipped / deferred / blocked).\n"
                "   3. Design — bullets from docs/sprint_design.md.\n"
                "   4. Implementation Metrics — source file count, LOC, entry\n"
                "      point RUN command.\n"
                "   5. Test Metrics — FULL-suite pass/fail/skipped from step d,\n"
                "      pass rate percentage.\n"
                "   6. Retrospective Highlights — 3-5 bullets from\n"
                "      docs/sprint_retrospective.md.\n"
                "   7. Next-Sprint Candidates — deferred stories + retro\n"
                "      action items.\n"
                "   EMBED the raw tool outputs verbatim so the PM cites real\n"
                "   numbers.\n\n"
                "3. After product_manager returns, call mark_complete with a\n"
                "   short paragraph referencing docs/delivery_report.md.\n"
                "   Include: project name, 'agile sprint', pass rate, shipped\n"
                "   user stories count, deferred stories count, entry point\n"
                "   verification outcome.",
            ),
        ]

    def _build_agile_incremental_phase_prompts(self, requirement: str) -> list[tuple[str, str]]:
        """Agile phase prompts for a follow-up sprint.

        Each incremental requirement on an agile project is treated as a
        NEW sprint: append stories to the backlog, design only what the
        new stories touch, implement, review, retro, deliver. The full
        test suite still runs in review — an agile sprint delivering a
        broken baseline is not a sprint review.
        """
        return [
            (
                "sprint_planning",
                f"New requirement for the next sprint: {requirement}\n\n"
                "Execute Phase 1 — Sprint Planning (AGILE, INCREMENTAL):\n"
                "dispatch_task to product_manager. Require the PM to:\n"
                "- Read docs/product_backlog.md if present.\n"
                "- APPEND a new '## Sprint <N> (ISO date)' section with\n"
                "  stories derived from the new requirement. Mark MVP scope.\n"
                "- Keep earlier stories untouched.\n"
                "- Every new story keeps its own Mermaid use case diagram.\n"
                "- Validate every ```mermaid block via the mermaid skill.\n"
                "Pass expected_artifacts=['docs/product_backlog.md'].\n"
                "STOP. Do NOT call mark_complete.",
            ),
            (
                "sprint_design",
                f"New requirement for the next sprint: {requirement}\n\n"
                "Execute Phase 2a — Lightweight Sprint Design (AGILE,\n"
                "INCREMENTAL):\n"
                "dispatch_task to architect. Require the architect to:\n"
                "- Read docs/sprint_design.md + docs/product_backlog.md.\n"
                "- APPEND / UPDATE only the sections the new stories touch.\n"
                "  Existing design stays. Keep C4 for architecture views.\n"
                "- Validate every ```mermaid block via the mermaid skill.\n"
                "Pass expected_artifacts=['docs/sprint_design.md'].\n"
                "STOP. Do NOT call mark_complete.",
            ),
            (
                "sprint_execution",
                f"New requirement for the next sprint: {requirement}\n\n"
                "Execute Phase 2b — Sprint Execution (AGILE, INCREMENTAL):\n"
                "1. Read docs/sprint_design.md. Identify NEW/CHANGED MVP\n"
                "   modules for this sprint only.\n"
                "2. dispatch_tasks_parallel to developer for each module:\n"
                "   - NEW modules: strict TDD. Write tests then source then\n"
                "     run per-module tests. Up to 3 fix attempts.\n"
                "   - CHANGED modules: task MUST say the file exists and\n"
                "     developer must EDIT in place (edit_file) — never\n"
                "     rewrite. Existing tests must keep passing.\n"
                "   - expected_artifacts=['src/<module>.py',\n"
                "     'tests/test_<module>.py'].\n"
                "3. STOP. Do NOT call mark_complete.",
            ),
            (
                "sprint_main_entry",
                f"New requirement for the next sprint: {requirement}\n\n"
                "Execute Phase 2c — Working Entry Point (AGILE,\n"
                "INCREMENTAL, verify-only):\n"
                "1. Check whether an entry file exists (src/main.py,\n"
                "   src/index.js, cmd/<app>/main.go, src/main.rs). If yes,\n"
                "   jump to step 3 with its RUN command; if no, dispatch\n"
                "   developer to create one with a RUN: line.\n"
                "2. Run RUN command via execute_shell(timeout=5). Same\n"
                "   interpretation as initial mode (timeout/exit-0 success;\n"
                "   startup-failure exit codes fail).\n"
                "3. On FAILURE dispatch developer to fix. Up to 3 attempts.\n"
                "4. STOP. Do NOT call mark_complete.",
            ),
            (
                "sprint_review",
                f"New requirement for the next sprint: {requirement}\n\n"
                "Execute Phase 3 — Sprint Review & Demo (AGILE,\n"
                "INCREMENTAL):\n"
                "dispatch_task to qa_engineer:\n"
                "- Read docs/product_backlog.md + docs/sprint_design.md\n"
                "  (including the new sections).\n"
                "- EDIT tests/test_integration.py in place (do NOT rewrite)\n"
                "  to add scenarios for the new MVP stories.\n"
                '- RUN the FULL suite: execute(command="python -m pytest\n'
                '  tests/ -q --tb=short") and iterate up to 3 times until\n'
                "  tests pass.\n"
                "- EDIT docs/sprint_review.md — append a new section for\n"
                "  this sprint with per-user-story PASS/FAIL.\n"
                "Pass expected_artifacts=['tests/test_integration.py',\n"
                "'docs/sprint_review.md'].\n"
                "STOP. Do NOT call mark_complete.",
            ),
            (
                "sprint_retrospective",
                f"New requirement for the next sprint: {requirement}\n\n"
                "Execute Phase 4 — Sprint Retrospective (AGILE,\n"
                "INCREMENTAL):\n"
                "dispatch_task to project_manager. APPEND a new sprint\n"
                "section to docs/sprint_retrospective.md. Keep earlier\n"
                "retros untouched. Cover went-well, did-not-go-well, and\n"
                "action items — scoped to THIS sprint.\n"
                "Pass expected_artifacts=['docs/sprint_retrospective.md'].\n"
                "STOP. Do NOT call mark_complete.",
            ),
            (
                "delivery",
                f"New requirement for the next sprint: {requirement}\n\n"
                "Execute Phase 5 — Sprint Delivery Report (AGILE,\n"
                "INCREMENTAL):\n\n"
                "Collect delta + full metrics:\n"
                "   a) New or modified files since baseline:\n"
                "      execute_shell('git status --short 2>/dev/null || true')\n"
                "      execute_shell('git diff --name-only HEAD~1 2>/dev/null || true')\n"
                "   b) Full file / LOC count:\n"
                "      execute_shell('find src -type f -name \"*.py\" | wc -l')\n"
                "      execute_shell('find src -type f -name \"*.py\" -exec wc -l {} + | sort -rn | head -30')\n"
                "   c) Test suite:\n"
                "      execute_shell('find tests -type f -name \"test_*.py\" 2>/dev/null | wc -l')\n"
                "      execute_shell('python -m pytest tests/ --collect-only -q 2>&1 | tail -5')\n"
                "      execute_shell('python -m pytest tests/ -q --tb=line 2>&1 | tail -20')\n\n"
                "Dispatch product_manager to EDIT docs/delivery_report.md\n"
                "(append a new sprint section — do NOT recreate). Cover:\n"
                "  1. Sprint Delta Summary — new requirement + shipped /\n"
                "     deferred stories.\n"
                "  2. Modules added vs modules edited (from step a).\n"
                "  3. Updated implementation metrics (step b).\n"
                "  4. FULL-suite test metrics (step c).\n"
                "  5. Retrospective bullets for this sprint.\n"
                "Pass expected_artifacts=['docs/delivery_report.md'].\n"
                "After it returns, call mark_complete with: project name,\n"
                "'agile sprint <incremental>', pass rate, shipped stories\n"
                "count, entry verification outcome.",
            ),
        ]

    def _build_initial_phase_prompts(self, requirement: str) -> list[tuple[str, str]]:
        """Phase prompts for the first (clean-slate) requirement on a project."""
        return [
            (
                "requirements",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 1 — Requirements:\n"
                "1. Call list_processes, then get_process('waterfall.process.md').\n"
                "2. Call list_agents to discover agents.\n"
                "3. dispatch_task to product_manager to write docs/requirement.md.\n"
                "   In the task description, require that EVERY individual\n"
                "   requirement (or tightly-coupled group of requirements)\n"
                "   be accompanied by a Mermaid use case diagram drawn as a\n"
                "   ``flowchart LR`` with actor nodes (shape\n"
                '   ``actor_<id>(["👤 Display Name"])``) and use-case nodes\n'
                '   (shape ``uc_<id>(("Verb Phrase"))``) connected by\n'
                "   edges. After writing, the PM must validate every\n"
                "   ```mermaid block using the ``mermaid`` skill and fix\n"
                "   any syntax error before responding.\n"
                "   Pass expected_artifacts=['docs/requirement.md'] so the\n"
                "   runtime retries once with context if the file is missing.\n"
                "4. After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "architecture",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 2 — Architecture:\n"
                "dispatch_task to architect to read docs/requirement.md and write docs/architecture.md.\n"
                "In the task description, require that every diagram in the\n"
                "document be a Mermaid diagram inside a fenced ```mermaid\n"
                "code block. Architecture views MUST use the C4 model\n"
                "(``C4Context``, ``C4Container``, ``C4Component``, and\n"
                "``C4Dynamic`` / ``C4Deployment`` where relevant). The\n"
                "document must include at minimum one ``C4Context``, one\n"
                "``C4Container``, and one ``C4Component`` diagram.\n"
                "Behavioral / data views (sequence, state machine, ER)\n"
                "use the corresponding standard Mermaid types.\n"
                "No ASCII art and no external image links.\n"
                "After writing, the architect MUST validate every\n"
                "```mermaid block using the ``mermaid`` skill and fix\n"
                "any syntax error before responding.\n"
                "Pass expected_artifacts=['docs/architecture.md'] so the\n"
                "runtime retries once with context if the file is missing.\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "implementation",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 3 — Implementation (TDD, per-module):\n"
                "1. Read docs/architecture.md to identify all modules.\n"
                "2. For EACH module, dispatch developer using dispatch_tasks_parallel.\n"
                "   In each task description, include the architecture spec AND\n"
                "   explicitly instruct the developer to follow strict TDD:\n"
                "   first write tests/test_<module>.py, then src/<module>.py,\n"
                "   then run ONLY that module's test file with\n"
                '   execute(command="python -m pytest tests/test_<module>.py -q --tb=short")\n'
                "   and iterate (up to 3 attempts) until that module's tests pass.\n"
                "   After the module's tests pass, the developer MUST run the\n"
                "   ``code_inspection`` skill's language-appropriate static\n"
                "   analyzer against each source file written (for Python:\n"
                "   ``ruff check <file>`` + ``mypy <file>``) and fix every\n"
                "   finding before reporting the module done.\n"
                "   For each task object in the JSON, set\n"
                "   expected_artifacts=['src/<module>.py', 'tests/test_<module>.py']\n"
                "   so the runtime retries once with context if either file is missing.\n"
                "3. Do NOT run the full pytest suite yourself — developers run\n"
                "   their own per-module tests, and the QA engineer will run\n"
                "   the full suite in Phase 5. Running full pytest here while\n"
                "   parallel developer dispatches are still writing files\n"
                "   causes races and noisy failures.\n"
                "4. When all dispatches return, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "main_entry",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 4 — Main Entry Point (language-agnostic):\n\n"
                "1. dispatch_task to developer with this task:\n"
                "'Write the project's main entry-point file. Use whatever\n"
                "path and format your language\\'s conventions dictate — e.g.\n"
                "src/main.py (Python), src/index.js (Node), cmd/<app>/main.go\n"
                "(Go), src/main.rs (Rust). Read the existing source files\n"
                "first to understand the module APIs. The file MUST be a\n"
                "real BOOT SCRIPT that can be launched directly (python\n"
                "src/main.py, node src/index.js, go run …). It is NOT enough\n"
                "to expose a class with a run() method — the file itself\n"
                "must start the app. Use whatever hook your language needs\n"
                '(``if __name__ == "__main__":`` for Python, top-level\n'
                "invocation for Node, ``func main()`` for Go, etc.).\n"
                "Also write the corresponding unit test file and verify it\n"
                "passes for that module only (do NOT run the full suite).\n"
                "End your response with ONE line in the EXACT format:\n"
                "    RUN: <command to launch the app from project root>\n"
                "Examples:\n"
                "    RUN: python src/main.py\n"
                "    RUN: node src/index.js\n"
                "    RUN: go run ./cmd/server'\n\n"
                "2. After the dispatch returns, extract the RUN: line from\n"
                "   the response's output_preview (format: ``RUN: <cmd>``).\n"
                "   Run the extracted command with execute_shell using\n"
                "   timeout=5. Interpret the result:\n"
                "   - A timeout (``command timed out after 5s``) is SUCCESS:\n"
                "     the app entered its main loop and was still running\n"
                "     when killed. This is the expected outcome for games\n"
                "     and servers.\n"
                "   - exit_code == 0 with normal output is also SUCCESS:\n"
                "     the app booted and exited cleanly (CLI-style tools).\n"
                "   - exit_code != 0 with output containing ImportError,\n"
                "     SyntaxError, ModuleNotFoundError, NameError,\n"
                "     AttributeError at top level, ``No such file``,\n"
                "     ``cannot find module``, or similar startup failures\n"
                "     is FAILURE.\n"
                "   - No RUN: line present in the response is FAILURE.\n\n"
                "3. If step 2 reported FAILURE, dispatch developer AGAIN\n"
                "   with the failure text and request a fix. Allow up to 3\n"
                "   attempts total.\n\n"
                "4. STOP after verification succeeds OR 3 attempts are\n"
                "   exhausted.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "qa_testing",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 5 — Integration Testing (QA runs the suite):\n"
                "dispatch_task to qa_engineer with this task:\n"
                "'Write tests/test_integration.py ONLY — integration tests for\n"
                "cross-module interactions and end-to-end flows. Do NOT write\n"
                "per-module unit tests (developer already did that in Phase 3).\n"
                "After writing, RUN the full suite yourself with\n"
                'execute(command="python -m pytest tests/ -q --tb=short")\n'
                "and iterate up to 3 times until tests pass. Report the final\n"
                "pytest result in your response.'\n"
                "Pass expected_artifacts=['tests/test_integration.py'] so the\n"
                "runtime retries once with context if the file is missing.\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "delivery",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 6 — Delivery Report:\n\n"
                "Your job is to collect hard metrics about what was built,\n"
                "then have the product_manager agent write them up as a\n"
                "proper delivery report. Do NOT guess numbers — every\n"
                "figure in the report must come from a real tool output.\n\n"
                "1. Collect development metrics. Use execute_shell to run\n"
                "   each command below and keep the output text. If a\n"
                "   command fails or returns nothing, note that fact and\n"
                "   continue — do not retry more than once per command.\n\n"
                "   a) Source file count. Pick the right find expression\n"
                "      for the language(s) used in this project — typical\n"
                "      source extensions are .py .js .ts .go .rs .java\n"
                "      .cpp .c .cs etc. Example:\n"
                "      execute_shell('find src -type f -name \"*.py\" | wc -l')\n"
                "   b) Source lines of code. Top files first, then total:\n"
                "      execute_shell('find src -type f -name \"*.py\" -exec wc -l {} + | sort -rn | head -30')\n"
                "   c) Test file list + counts:\n"
                "      execute_shell('find tests -type f -name \"test_*.py\" 2>/dev/null | wc -l')\n"
                "      execute_shell('python -m pytest tests/ --collect-only -q 2>&1 | tail -5')\n"
                "   d) Test pass/fail summary (final run):\n"
                "      execute_shell('python -m pytest tests/ -q --tb=line 2>&1 | tail -20')\n"
                "   e) Coverage (optional — may fail if pytest-cov not installed):\n"
                "      execute_shell('python -m pytest tests/ --cov=src --cov-report=term 2>&1 | tail -25')\n\n"
                "2. Dispatch product_manager to write the final report.\n"
                "   Pass expected_artifacts=['docs/delivery_report.md'] so\n"
                "   the runtime retries once with context if the file is\n"
                "   missing.\n"
                "   Embed the ACTUAL tool outputs you gathered above into\n"
                "   the task description so product_manager has the raw\n"
                "   numbers to cite. Use a task description like:\n\n"
                "   'Write docs/delivery_report.md — the project delivery\n"
                "   report. Use the data I pass you; do not invent numbers.\n"
                "   Required sections:\n"
                "   1. Executive Summary — one paragraph, what was built\n"
                "      and whether it is production-ready.\n"
                "   2. Design — summarize docs/architecture.md (read it\n"
                "      yourself) in a few bullets: module decomposition,\n"
                "      key technology choices.\n"
                "   3. Implementation Metrics:\n"
                "      - Source file count\n"
                "      - Total lines of code (from wc -l output)\n"
                "      - Per-module breakdown (top files by LOC)\n"
                "      - Entry point location and RUN command\n"
                "   4. Testing Metrics:\n"
                "      - Test file count\n"
                "      - Total test cases collected (pytest --collect-only)\n"
                "      - Pass / fail / skipped counts (pytest final run)\n"
                "      - Overall pass rate as a percentage\n"
                "      - Coverage percentage IF available (otherwise\n"
                '        explicitly state "coverage not measured")\n'
                "   5. Known Issues — list any failing tests with short\n"
                '      descriptions, or "none" if all green.\n'
                "   6. Conclusion — one or two sentences on readiness.\n\n"
                "   RAW TOOL OUTPUTS (cite these, do not fabricate):\n"
                "   <paste the actual execute_shell outputs from step 1>'\n\n"
                "3. After product_manager returns, call mark_complete with\n"
                "   a short paragraph summary that references\n"
                "   docs/delivery_report.md for details. The summary\n"
                "   should include: project name, pass rate, total LOC,\n"
                "   and whether the entry point verified successfully in\n"
                "   Phase 4.",
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
