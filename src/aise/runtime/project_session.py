"""ProjectSession — generic, role-agnostic orchestrator session.

Drives a project from a raw requirement to delivery using only:

- The agents declared in ``src/aise/agents/*.md``
- The processes declared in ``src/aise/processes/*.process.md``
- The runtime safety policy in :class:`RuntimeConfig`

Nothing in this file knows what TDD is, what an "implementation phase"
looks like, or which agent plays which role — that knowledge lives in
the data files. Code only walks the structures it parses out of those
files and exposes generic primitives via :mod:`aise.tools`.

Public surface (kept stable so existing tests/web code continue to work):

- ``ProjectSession(manager, project_root=..., on_event=...)``
- ``run(requirement) -> str``
- ``task_log`` property
- ``current_stage`` property
- ``_make_tools()`` — returns the primitive tools (back-compat alias)
- ``_build_pm_runtime()`` — builds the orchestrator runtime (back-compat alias)
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..tools import ToolContext, WorkflowState, build_orchestrator_tools
from ..utils.logging import get_logger
from .llm_factory import build_llm as _factory_build_llm
from .runtime_config import LLMDefaults, RuntimeConfig

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
        self._process_type = (
            raw_process
            if raw_process in ("waterfall", "agile", "waterfall_v2")
            else "waterfall"
        )
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
        # in any docs/*.md they write (see tools.dispatch.dispatch_task
        # for the prefix format, and architect.md / product_manager.md /
        # qa_engineer.md "Document Language" sections for the rule).
        self._ctx.original_requirement = requirement

        # Auto-scale the dispatch cap to the actual architecture size.
        # The fixed default (128) covers a typical project, but a
        # 60-component architecture would still exhaust it before
        # reaching delivery. Read the stack contract (if architect has
        # already produced one — incremental runs always have one;
        # fresh runs raise the cap again after architecture phase via
        # this same method, see ``_apply_dispatch_floor``) and lift
        # ``max_dispatches`` to ``Σ(1 + components) + buffer`` if the
        # static default is smaller.
        self._apply_dispatch_floor(reason="run_start")

        # waterfall_v2: short-circuit to the new driver. The legacy
        # phase loop below handles "waterfall" / "agile" — both run
        # the orchestrator-LLM-driven _build_*_phase_prompts flow.
        # waterfall_v2 instead walks process.md via PhaseExecutor with
        # explicit acceptance gates + reviewer + halt/resume.
        if self._process_type == "waterfall_v2":
            return self._run_waterfall_v2(requirement)

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
                    "max_dispatches": self._config.safety_limits.max_dispatches,
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

    def _run_waterfall_v2(self, requirement: str) -> str:
        """Drive a project through waterfall_v2 (process.md-based).

        Wires WaterfallV2Driver (commit c4) into ProjectSession by
        adapting (role, prompt, expected) callbacks to the existing
        dispatch_task tool. Reviewer dispatch goes through the same
        tool with the reviewer's role; agent_model_selection in
        project_config decides which model each role talks to.
        """
        # Build dispatch_task once; adapter closures reuse it.
        from ..tools.dispatch import make_dispatch_tools
        from .waterfall_v2_driver import (
            WaterfallV2Driver,
            make_observable_produce_fn,
        )

        tools = make_dispatch_tools(self._ctx)
        dispatch_task = next(t for t in tools if t.name == "dispatch_task")

        def _dispatch(role: str, prompt: str, expected: list[str] | None) -> str:
            raw = dispatch_task.invoke(
                {
                    "agent_name": role,
                    "task_description": prompt,
                    "step_id": f"v2-{role}",
                    "phase": "waterfall_v2",
                    "expected_artifacts": list(expected) if expected else None,
                }
            )
            try:
                parsed = json.loads(raw)
            except (TypeError, ValueError):
                return raw if isinstance(raw, str) else ""
            payload = parsed.get("payload", {}) if isinstance(parsed, dict) else {}
            return payload.get("output_preview", "") or ""

        produce_fn = make_observable_produce_fn(
            lambda role, prompt, expected: _dispatch(role, prompt, list(expected or ()))
        )

        def reviewer_dispatch(role: str, prompt: str) -> str:
            # Reviewers go through the same dispatch_task, no expected_artifacts
            return _dispatch(role, prompt, None)

        if self._project_root is None:
            raise RuntimeError("waterfall_v2 requires a project_root on the session")

        driver = WaterfallV2Driver(
            project_root=self._project_root,
            produce_fn=produce_fn,
            dispatch_reviewer=reviewer_dispatch,
            # Forward phase_plan / phase_start / phase_complete events
            # through the project's ToolContext so the web UI's phase
            # stepper renders correctly. Without this the UI sees only
            # one fallback row because v2 used to be opaque.
            on_event=self._ctx.emit,
        )
        result = driver.run(requirement)
        if result.halted:
            return (
                f"[waterfall_v2 HALTED at phase={result.halt_state.halted_at_phase}]\n"
                f"reason: {result.halt_state.halt_reason}\n"
                f"detail: {result.halt_state.failure_summary[:1000]}\n\n"
                f"Run `aise resume_project <project_id>` to retry from "
                f"the halted phase after fixing the issue."
            )
        return f"[waterfall_v2 COMPLETED] phases: {', '.join(result.completed_phases)}"

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

        def _on_token_usage(counts: dict[str, int]) -> None:
            self._ctx.emit(
                {
                    "type": "token_usage",
                    "agent": self._orchestrator_name,
                    "timestamp": _now(),
                    "input_tokens": int(counts.get("input_tokens", 0) or 0),
                    "output_tokens": int(counts.get("output_tokens", 0) or 0),
                    "total_tokens": int(counts.get("total_tokens", 0) or 0),
                }
            )

        try:
            return self._pm_runtime.handle_message(
                prompt,
                thread_id=self._session_id,
                on_token_usage=_on_token_usage,
            )
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
            max_iterations=480,
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

    # Phase name -> safety_net layer-B expectation factory. The
    # orchestrator runs ``run_post_step_check`` with the phase's
    # expectation set after the phase finishes, so a missing artifact
    # surfaces as a structured event the next dispatch can react to.
    # Multiple phases can share an expectation set (architecture is
    # checked twice — once after waterfall design, once after agile
    # sprint design — using the same factory).
    _POST_PHASE_SAFETY_NET: dict[str, tuple[str, ...]] = {
        "architecture": ("architecture", "entry_point"),  # entry-point list is no-op until contract has lifecycle_inits
        "sprint_design": ("architecture",),
        "main_entry": ("entry_point",),
        "sprint_main_entry": ("entry_point",),
        # ``scenario_implementation`` (Phase 4.5) is the gate that turns
        # docs/behavioral_contract.json into per-scenario test files.
        # Running ``scenarios`` here surfaces missing / failing tests
        # back to the orchestrator; the QA phase re-checks so a
        # regression there blocks delivery too.
        "scenario_implementation": ("scenarios",),
        "qa_testing": ("qa", "ui_smoke", "scenarios"),
        "sprint_review": ("qa", "ui_smoke", "scenarios"),
    }

    def _apply_dispatch_floor(self, *, reason: str) -> None:
        """Auto-scale ``max_dispatches`` to the architect's contract.

        Computes ``Σ(1 + len(components)) + DISPATCH_FLOOR_BUFFER``
        across every subsystem in ``docs/stack_contract.json`` and
        raises the live ``SafetyLimits.max_dispatches`` if the result
        exceeds the current cap. Called once at run start (no-op when
        the contract isn't on disk yet) and again right after the
        architecture phase finishes (when it just got produced).

        Lowers nothing — only ratchets up — so an explicit project-
        level override that's already higher than the dynamic floor
        is preserved.
        """
        if self._project_root is None:
            return
        contract_path = self._project_root / "docs" / "stack_contract.json"
        if not contract_path.is_file():
            return
        try:
            import json as _json

            data = _json.loads(contract_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.debug("dispatch floor: contract unreadable (%s): %s", reason, exc)
            return
        if not isinstance(data, dict):
            return
        subsystems = data.get("subsystems")
        if not isinstance(subsystems, list) or not subsystems:
            return

        from .runtime_config import DISPATCH_FLOOR_BUFFER

        total = 0
        for ss in subsystems:
            if not isinstance(ss, dict):
                continue
            comps = ss.get("components") or []
            # 1 skeleton + N component dispatches per subsystem.
            total += 1 + (len(comps) if isinstance(comps, list) else 0)
        floor = total + DISPATCH_FLOOR_BUFFER
        current = self._config.safety_limits.max_dispatches
        if floor <= current:
            return
        self._config.safety_limits.max_dispatches = floor
        logger.info(
            "Dispatch cap raised: session=%s reason=%s floor=%d (was %d) subsystems=%d components=%d",
            self._session_id,
            reason,
            floor,
            current,
            len(subsystems),
            total - len(subsystems),
        )
        self._ctx.emit(
            {
                "type": "dispatch_cap_raised",
                "reason": reason,
                "from": current,
                "to": floor,
                "subsystems": len(subsystems),
                "components": total - len(subsystems),
                "timestamp": _now(),
            }
        )

    def _run_post_phase_hooks(self, phase_idx: int, phase_name: str) -> None:
        """Pure-Python hooks that run after each successful phase.

        Hooks today:
        - Re-apply the dispatch-cap dynamic floor after every phase so
          a contract produced by the architect mid-run lifts the cap
          before implementation starts.
        - Generate the language-idiomatic root config (pyproject.toml /
          package.json / go.mod / Cargo.toml / pom.xml) once the
          developer has written enough source.
        - Run the phase-specific safety-net expectations
          (architecture / main-entry / QA / UI-smoke). Each expectation
          set covers a distinct contract: a missing artifact triggers
          a structured event the orchestrator surfaces back to the
          relevant agent on the next dispatch, so wiring bugs are
          re-dispatched rather than silently shipped.

        Any failure here is logged and swallowed — a broken post-phase
        hook must never mark the whole run as failed.
        """
        # Always re-apply the dispatch-cap floor — cheap, idempotent,
        # and guards against the case where stack_contract.json
        # appears mid-run (i.e. right after the architecture phase).
        try:
            self._apply_dispatch_floor(reason=f"post_phase_{phase_name}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("dispatch-floor reapplication failed: %s", exc)

        # Run safety-net layer-B checks bound to this phase. Order is
        # phase → expectation set; each set has its own integrity
        # contract and re-dispatch policy.
        try:
            self._run_post_phase_safety_net(phase_idx, phase_name)
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("safety_net post-phase hook failed: %s", exc)

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

    def _run_post_phase_safety_net(self, phase_idx: int, phase_name: str) -> None:
        """Run the safety-net layer-B expectations bound to ``phase_name``.

        For each tag in ``_POST_PHASE_SAFETY_NET[phase_name]``, fetch
        the matching expectation factory from ``aise.safety_net`` and
        invoke ``run_post_step_check``. Results are emitted as
        ``safety_net_check`` events so the dashboard + orchestrator
        prompt can both see what's missing.

        Failure mode: this hook is a strict no-op when the project
        root isn't pinned yet, when the phase has no expectations
        registered, or when the safety_net itself raises (we already
        wrap the caller in a try/except to keep the run going).
        """
        if self._project_root is None:
            return
        tags = self._POST_PHASE_SAFETY_NET.get(phase_name)
        if not tags:
            return

        from ..safety_net import (
            architecture_expectations,
            entry_point_expectations,
            qa_expectations,
            run_post_step_check,
            scenario_expectations,
            ui_smoke_expectations,
        )

        # ``scenarios`` is parametrised by project_root because it
        # has to read ``docs/behavioral_contract.json`` to know what
        # to check; the other factories take no args.
        factories: dict[str, Any] = {
            "architecture": architecture_expectations,
            "entry_point": entry_point_expectations,
            "qa": qa_expectations,
            "ui_smoke": ui_smoke_expectations,
            "scenarios": lambda: scenario_expectations(self._project_root),
        }

        for tag in tags:
            factory = factories.get(tag)
            if factory is None:
                continue
            try:
                outcome = run_post_step_check(
                    self._project_root,
                    step_id=f"post_phase_{phase_name}_{tag}",
                    layer_b_expected=factory(),
                )
            except Exception as exc:
                logger.warning(
                    "safety_net layer-B check failed (phase=%s tag=%s): %s",
                    phase_name,
                    tag,
                    exc,
                )
                continue
            self._ctx.emit(
                {
                    "type": "safety_net_check",
                    "phase_idx": phase_idx,
                    "phase_name": phase_name,
                    "tag": tag,
                    "missing": [a.describe() for a in outcome.layer_b_missing],
                    "repaired": list(outcome.repairs_succeeded),
                    "repair_failures": [k for k, _ in outcome.repairs_failed],
                    "events_emitted": outcome.events_emitted,
                    "timestamp": _now(),
                }
            )
            if outcome.layer_b_missing:
                logger.info(
                    "safety_net: phase=%s tag=%s missing=%s",
                    phase_name,
                    tag,
                    [a.describe() for a in outcome.layer_b_missing],
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
                "Pass expected_artifacts=['docs/architecture.md',\n"
                "'docs/stack_contract.json'] so the runtime retries once\n"
                "if either is missing.\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "implementation",
                f"New requirement to integrate: {requirement}\n\n"
                "Execute Phase 3 — Implementation (INCREMENTAL, TDD,\n"
                "per-subsystem fan-out):\n\n"
                "Fan-out is performed by the orchestration layer, NOT by\n"
                "you drafting tasks_json. You make ONE tool call:\n\n"
                '    dispatch_subsystems(phase="implementation")\n\n'
                "The primitive reads docs/stack_contract.json's\n"
                "subsystems[] and dispatches developer in parallel (up to\n"
                "the runtime cap). Each developer dispatch carries the\n"
                "STACK CONTRACT and ORIGINAL USER REQUIREMENT blocks\n"
                "automatically.\n\n"
                "1. Verify docs/stack_contract.json exists and is valid.\n"
                "   If the incremental requirement extended subsystems[]\n"
                "   or added components, architect should already have\n"
                "   updated the contract; if not, STOP and dispatch\n"
                "   architect to bring the contract in line with\n"
                "   docs/architecture.md.\n"
                "2. Read docs/architecture.md briefly to understand which\n"
                "   subsystems are NEW or CHANGED (purely informational —\n"
                "   the dispatch primitive does not need this from you).\n"
                '3. Call dispatch_subsystems(phase="implementation")\n'
                "   exactly once. Each developer dispatch's task\n"
                "   description carries the full component list for its\n"
                "   subsystem. For CHANGED components the developer is\n"
                "   instructed (via the rendered task) to EDIT in place.\n"
                "4. Do NOT call dispatch_task or dispatch_tasks_parallel\n"
                "   yourself for individual subsystems / components.\n"
                "5. Do NOT run the full suite here — that is Phase 5's job.\n"
                "6. When dispatch_subsystems returns, STOP.\n"
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
                "- Extend the integration test file already on disk (e.g.\n"
                "  tests/test_integration.py for pytest,\n"
                "  tests/integration.test.ts for vitest/jest,\n"
                "  internal/integration_test.go for Go,\n"
                "  tests/integration.rs for Rust,\n"
                "  src/test/java/.../IntegrationTest.java for Java) IN\n"
                "  PLACE — do NOT recreate the file from scratch — with\n"
                "  integration scenarios for the new requirement.\n"
                "  Existing integration tests must keep running.\n"
                "- RUN the FULL suite using the project's test runner:\n"
                "    Python:     python -m pytest tests/ -q --tb=short\n"
                "    TypeScript: npx vitest run  (or npx jest)\n"
                "    Go:         go test ./...\n"
                "    Rust:       cargo test\n"
                "    Java:       mvn test\n"
                "  Iterate up to 3 times until all tests pass.\n"
                "- Report final pass/fail counts in the response.\n"
                "Pass expected_artifacts=[<the chosen integration test\n"
                "file path>].\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "delivery",
                f"New requirement to integrate: {requirement}\n\n"
                "Execute Phase 6 — Delivery Report (INCREMENTAL scope):\n\n"
                "Assemble the report from the QA engineer's structured\n"
                "findings — do NOT re-run the test suite yourself (avoids\n"
                "flakiness covering up QA-flagged failures / product\n"
                "bugs). Read the project's language from\n"
                "docs/architecture.md (or docs/stack_contract.json if\n"
                "present); do NOT default to Python.\n\n"
                "1. Read docs/qa_report.json (REQUIRED — schema in the\n"
                "   waterfall Phase-6 prompt; QA writes it in Phase 5).\n"
                "   If missing or invalid, dispatch qa_engineer to\n"
                "   produce it, then re-read.\n\n"
                "2. Collect incremental DELTA metrics QA does not\n"
                "   produce:\n"
                "   a) New or modified source files since the previous\n"
                "      baseline run. Use git where available:\n"
                "      execute_shell('git status --short 2>/dev/null || echo not-a-git-repo')\n"
                "      execute_shell('git diff --name-only HEAD~1 2>/dev/null || true')\n"
                "      Fall back to find -newer if git is not in play.\n"
                "   b) Current source file count and LOC (full project).\n"
                "      Pick the row matching your project's language. Run\n"
                "      each find twice: once with ``| wc -l`` for the\n"
                "      count, once with ``-exec wc -l {} + | sort -rn |\n"
                "      head -30`` for per-file LOC.\n"
                "      - Python:     find src -type f -name '*.py'\n"
                "      - TypeScript: find src -type f \\( -name '*.ts' -o -name '*.tsx' \\)\n"
                "      - Go:         find . -type f -name '*.go' -not -path './vendor/*'\n"
                "      - Rust:       find src -type f -name '*.rs'\n"
                "      - Java:       find src -type f -name '*.java'\n"
                "3. Dispatch product_manager to write docs/delivery_report.md.\n"
                "   Pass expected_artifacts=['docs/delivery_report.md'].\n"
                "   Require the report to cover:\n"
                "   - Executive Summary — one paragraph scoped to the new\n"
                "     requirement (production-ready iff qa_report says so).\n"
                "   - Incremental Delta — bullet list of modules added and\n"
                "     modules edited. Cite step 2a outputs.\n"
                "   - Full Implementation Metrics — counts from step 2b.\n"
                "   - Testing Metrics — copy qa_report.pytest fields\n"
                "     verbatim (passed/failed/skipped + pass rate).\n"
                "   - UI Validation — copy qa_report.ui_validation\n"
                "     verbatim.\n"
                "   - Known Issues — list every entry from\n"
                "     qa_report.product_bugs verbatim AND every test in\n"
                "     qa_report.pytest.failed_tests verbatim, or 'none'\n"
                "     when both are empty AND ui_validation passed.\n"
                "   - Conclusion — one or two sentences on readiness\n"
                "     AFTER the incremental change.\n"
                "   EMBED the raw qa_report.json + step 2 tool outputs in\n"
                "   the task description so PM cites them verbatim.\n\n"
                "4. After product_manager returns, call mark_complete\n"
                "   with a short paragraph referencing\n"
                "   docs/delivery_report.md. Include: project name,\n"
                "   'incremental', pass rate (from qa_report), number of\n"
                "   new + edited modules, and whether the entry point\n"
                "   verified successfully in Phase 4.",
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
                "Pass expected_artifacts=['docs/sprint_design.md',\n"
                "'docs/stack_contract.json'].\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "sprint_execution",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 2b — Sprint Execution (AGILE, per-subsystem fan-out):\n\n"
                "Fan-out is performed by the orchestration layer, NOT by\n"
                "you drafting tasks_json. You make ONE tool call:\n\n"
                '    dispatch_subsystems(phase="sprint_execution")\n\n'
                "The primitive reads docs/stack_contract.json's\n"
                "subsystems[] and dispatches developer in parallel (up to\n"
                "the runtime cap). Each developer dispatch carries the\n"
                "STACK CONTRACT and ORIGINAL USER REQUIREMENT blocks\n"
                "automatically.\n\n"
                "1. Verify docs/stack_contract.json exists and is valid.\n"
                "   If missing or malformed, STOP and dispatch architect.\n"
                "2. Read docs/sprint_design.md briefly (informational).\n"
                '3. Call dispatch_subsystems(phase="sprint_execution")\n'
                "   exactly once. Each developer dispatch's task\n"
                "   description includes the subsystem's components from\n"
                "   the contract.\n"
                "4. Do NOT call dispatch_task or dispatch_tasks_parallel\n"
                "   yourself for individual subsystems / components.\n"
                "5. When dispatch_subsystems returns, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "sprint_main_entry",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 2c — Working Entry Point (AGILE):\n"
                "1. dispatch_task to developer: 'Write the project's main\n"
                "   entry-point file that wires all MVP modules together so\n"
                "   the sprint output can be demoed at review. Use the\n"
                "   language convention (src/main.py for Python, src/index.ts\n"
                "   for TypeScript, cmd/<app>/main.go for Go, src/main.rs\n"
                "   for Rust, src/main/java/.../App.java for Java,\n"
                "   src/Program.cs for .NET). The file MUST boot directly\n"
                "   with a single terminal command (python src/main.py /\n"
                "   node src/index.js / go run ./cmd/server / cargo run /\n"
                "   java -jar ... / dotnet run). End your response with\n"
                "   ONE line:\n"
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
                "- Write ONE integration test file at the path matching\n"
                "  the project's test runner (e.g. tests/test_integration.py\n"
                "  for pytest, tests/integration.test.ts for vitest/jest,\n"
                "  internal/integration_test.go for Go, tests/integration.rs\n"
                "  for Rust, src/test/java/.../IntegrationTest.java for\n"
                "  Java). ONLY integration tests — developers already wrote\n"
                "  per-module unit tests. Cover every MVP user story's\n"
                "  acceptance criteria end-to-end.\n"
                "- RUN the FULL suite using the project's test runner\n"
                "  (python -m pytest tests/ / npx vitest run / go test ./...\n"
                "  / cargo test / mvn test) and iterate up to 3 times\n"
                "  until tests pass.\n"
                "- Write docs/sprint_review.md with a per-user-story\n"
                "  PASS/FAIL table so the product owner can verify delivery\n"
                "  during review. Include the final test summary.\n"
                "Pass expected_artifacts=[<the integration test file path>,\n"
                "'docs/sprint_review.md', 'docs/qa_report.json'].\n"
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
                "report. Do NOT guess numbers. Read the project's language\n"
                "from docs/architecture.md (or docs/stack_contract.json if\n"
                "present) BEFORE picking the file globs and test runner;\n"
                "do NOT default to Python.\n\n"
                "1. Read docs/qa_report.json (REQUIRED — schema in the\n"
                "   waterfall Phase-6 prompt; QA writes it during Sprint\n"
                "   Review). If missing or invalid, dispatch qa_engineer\n"
                "   to produce it, then re-read.\n"
                "2. Collect non-test metrics via execute_shell. Pick the\n"
                "   row matching the project's language. Run each find\n"
                "   twice: once with ``| wc -l`` for the count, once with\n"
                "   ``-exec wc -l {} + | sort -rn | head -30`` for LOC.\n"
                "      - Python:     find src -type f -name '*.py'\n"
                "      - TypeScript: find src -type f \\( -name '*.ts' -o -name '*.tsx' \\)\n"
                "      - Go:         find . -type f -name '*.go' -not -path './vendor/*'\n"
                "      - Rust:       find src -type f -name '*.rs'\n"
                "      - Java:       find src -type f -name '*.java'\n"
                "3. Dispatch product_manager to write docs/delivery_report.md.\n"
                "   Pass expected_artifacts=['docs/delivery_report.md'].\n"
                "   Require the report to cover:\n"
                "   1. MVP Summary — one paragraph on what shipped this\n"
                "      sprint and whether it meets the DoD of the in-scope\n"
                "      stories (production-ready iff qa_report says so).\n"
                "   2. User Stories Shipped vs Deferred — table with story\n"
                "      ID, title, status (shipped / deferred / blocked).\n"
                "   3. Design — bullets from docs/sprint_design.md.\n"
                "   4. Implementation Metrics — source file count, LOC,\n"
                "      entry point RUN command.\n"
                "   5. Test Metrics — copy qa_report.pytest fields\n"
                "      verbatim (passed/failed/skipped + pass rate). Do\n"
                "      NOT re-run tests yourself.\n"
                "   6. UI Validation — copy qa_report.ui_validation\n"
                "      verbatim.\n"
                "   7. Known Issues — list every entry from\n"
                "      qa_report.product_bugs verbatim AND every test in\n"
                "      qa_report.pytest.failed_tests verbatim, or 'none'.\n"
                "   8. Retrospective Highlights — 3-5 bullets from\n"
                "      docs/sprint_retrospective.md.\n"
                "   9. Next-Sprint Candidates — deferred stories + retro\n"
                "      action items.\n"
                "   EMBED the raw qa_report.json + step-2 tool outputs in\n"
                "   the task description so the PM cites them verbatim.\n\n"
                "4. After product_manager returns, call mark_complete\n"
                "   with a short paragraph referencing\n"
                "   docs/delivery_report.md. Include: project name,\n"
                "   'agile sprint', pass rate (from qa_report), shipped\n"
                "   user stories count, deferred stories count, entry\n"
                "   point verification outcome.",
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
                "Pass expected_artifacts=['docs/sprint_design.md',\n"
                "'docs/stack_contract.json'].\n"
                "STOP. Do NOT call mark_complete.",
            ),
            (
                "sprint_execution",
                f"New requirement for the next sprint: {requirement}\n\n"
                "Execute Phase 2b — Sprint Execution (AGILE, INCREMENTAL,\n"
                "per-subsystem fan-out):\n\n"
                "Fan-out is performed by the orchestration layer. Make ONE\n"
                "tool call:\n\n"
                '    dispatch_subsystems(phase="sprint_execution")\n\n'
                "1. Verify docs/stack_contract.json is up to date with the\n"
                "   incremental sprint design. If architect should have\n"
                "   amended subsystems[] / components[] but didn't, STOP\n"
                "   and dispatch architect to bring the contract in line.\n"
                "2. Read docs/sprint_design.md briefly (informational).\n"
                '3. Call dispatch_subsystems(phase="sprint_execution")\n'
                "   exactly once. Each developer dispatch's task\n"
                "   description includes the subsystem's components from\n"
                "   the contract; CHANGED components are addressed via\n"
                "   the rendered TDD instructions (edit-in-place when the\n"
                "   file already exists).\n"
                "4. Do NOT call dispatch_task or dispatch_tasks_parallel\n"
                "   yourself for individual subsystems / components.\n"
                "5. STOP. Do NOT call mark_complete.",
            ),
            (
                "sprint_main_entry",
                f"New requirement for the next sprint: {requirement}\n\n"
                "Execute Phase 2c — Working Entry Point (AGILE,\n"
                "INCREMENTAL, verify-only):\n"
                "1. Check whether an entry file exists (src/main.py,\n"
                "   src/index.ts, cmd/<app>/main.go, src/main.rs,\n"
                "   src/main/java/.../App.java, src/Program.cs). If yes,\n"
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
                "- EDIT the existing integration test file IN PLACE (e.g.\n"
                "  tests/test_integration.py for pytest,\n"
                "  tests/integration.test.ts for vitest/jest,\n"
                "  internal/integration_test.go for Go,\n"
                "  tests/integration.rs for Rust,\n"
                "  src/test/java/.../IntegrationTest.java for Java) — do\n"
                "  NOT rewrite — to add scenarios for the new MVP stories.\n"
                "- RUN the FULL suite using the project's test runner\n"
                "  (python -m pytest tests/ / npx vitest run / go test ./...\n"
                "  / cargo test / mvn test) and iterate up to 3 times\n"
                "  until tests pass.\n"
                "- EDIT docs/sprint_review.md — append a new section for\n"
                "  this sprint with per-user-story PASS/FAIL.\n"
                "Pass expected_artifacts=[<the integration test file path>,\n"
                "'docs/sprint_review.md', 'docs/qa_report.json'].\n"
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
                "Assemble the report from the QA engineer's structured\n"
                "findings — do NOT re-run tests yourself. Read the\n"
                "project's language from docs/architecture.md (or\n"
                "docs/stack_contract.json if present); do NOT default to\n"
                "Python.\n"
                "1. Read docs/qa_report.json (REQUIRED — schema in the\n"
                "   waterfall Phase-6 prompt; QA writes it during Sprint\n"
                "   Review). If missing or invalid, dispatch qa_engineer\n"
                "   to produce it, then re-read.\n"
                "2. Collect delta + non-test metrics:\n"
                "   a) New or modified files since baseline:\n"
                "      execute_shell('git status --short 2>/dev/null || true')\n"
                "      execute_shell('git diff --name-only HEAD~1 2>/dev/null || true')\n"
                "   b) Full file / LOC count, pick the row matching your\n"
                "      project's language. Run each find twice: once with\n"
                "      ``| wc -l`` for the count, once with\n"
                "      ``-exec wc -l {} + | sort -rn | head -30`` for LOC.\n"
                "      - Python:     find src -type f -name '*.py'\n"
                "      - TypeScript: find src -type f \\( -name '*.ts' -o -name '*.tsx' \\)\n"
                "      - Go:         find . -type f -name '*.go' -not -path './vendor/*'\n"
                "      - Rust:       find src -type f -name '*.rs'\n"
                "      - Java:       find src -type f -name '*.java'\n"
                "3. Dispatch product_manager to EDIT docs/delivery_report.md\n"
                "   (append a new sprint section — do NOT recreate). Cover:\n"
                "   1. Sprint Delta Summary — new requirement + shipped /\n"
                "      deferred stories.\n"
                "   2. Modules added vs modules edited (from step 2a).\n"
                "   3. Updated implementation metrics (step 2b).\n"
                "   4. Test metrics — copy qa_report.pytest verbatim.\n"
                "   5. UI Validation — copy qa_report.ui_validation\n"
                "      verbatim.\n"
                "   6. Known Issues — list every entry from\n"
                "      qa_report.product_bugs verbatim AND every test in\n"
                "      qa_report.pytest.failed_tests verbatim, or 'none'.\n"
                "   7. Retrospective bullets for this sprint.\n"
                "Pass expected_artifacts=['docs/delivery_report.md'].\n"
                "After it returns, call mark_complete with: project name,\n"
                "'agile sprint <incremental>', pass rate (from qa_report),\n"
                "shipped stories count, entry verification outcome.",
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
                "Pass expected_artifacts=['docs/architecture.md',\n"
                "'docs/stack_contract.json'] so the runtime retries once\n"
                "if either is missing.\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "implementation",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 3 — Implementation (TDD, per-subsystem fan-out):\n\n"
                "Fan-out is performed by the orchestration layer, NOT by you\n"
                "drafting tasks_json. You make ONE tool call:\n\n"
                '    dispatch_subsystems(phase="implementation")\n\n'
                "The primitive reads docs/stack_contract.json's subsystems[]\n"
                "(written by architect in Phase 2), builds one developer\n"
                "task description per subsystem deterministically (from the\n"
                "contract's language / test_runner / static_analyzer +\n"
                "components[] list — no LLM in the loop), and dispatches\n"
                "developer in parallel up to the runtime cap\n"
                "(safety_limits.max_concurrent_subsystem_dispatches, default\n"
                "4). Each developer dispatch carries the STACK CONTRACT and\n"
                "ORIGINAL USER REQUIREMENT blocks automatically.\n\n"
                "1. Verify docs/stack_contract.json exists and is valid by\n"
                "   reading it once with read_file. If missing or malformed,\n"
                "   STOP and dispatch architect to produce it; do NOT guess\n"
                "   the stack.\n"
                '2. Call dispatch_subsystems(phase="implementation")\n'
                "   exactly once. The tool returns an aggregate result with\n"
                "   per-subsystem pass/fail and component artifact verification.\n"
                "3. Do NOT call dispatch_task or dispatch_tasks_parallel\n"
                "   yourself for individual subsystems / components — the\n"
                "   primitive does the fan-out so a weak orchestrator LLM\n"
                "   that can only emit one tool call per turn still gets\n"
                "   real parallelism on the worker side.\n"
                "4. Do NOT run the full test suite — developers run their\n"
                "   own per-component tests inside each subsystem dispatch,\n"
                "   and the QA engineer runs the full suite in Phase 5.\n"
                "5. When dispatch_subsystems returns, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "main_entry",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 4 — Main Entry Point (language-agnostic):\n\n"
                "1. dispatch_task to developer with this task:\n"
                "'Write the project's main entry-point file. Use the path\n"
                "and format your project's language conventions dictate —\n"
                "e.g. src/main.py (Python), src/index.ts (TypeScript),\n"
                "cmd/<app>/main.go (Go), src/main.rs (Rust),\n"
                "src/main/java/.../App.java (Java), src/Program.cs (.NET).\n"
                "Read the existing source files first to understand the\n"
                "module APIs. The file MUST be a real BOOT SCRIPT that can\n"
                "be launched directly with a single terminal command. It\n"
                "is NOT enough to expose a class with a run() method —\n"
                "the file itself must start the app. Use whatever hook\n"
                'your language needs (e.g. ``if __name__ == "__main__":``\n'
                "for Python, top-level invocation for Node, ``func main()``\n"
                "for Go, ``fn main()`` for Rust, ``public static void main``\n"
                "for Java, ``Program.Main`` for .NET).\n"
                "Also write the corresponding unit test file (using the\n"
                "language's test runner) and verify it passes for that\n"
                "module only (do NOT run the full suite).\n"
                "Test ONLY the constructor and the initialize / setup\n"
                "step. Do NOT call the entry's run / main / event loop\n"
                "from tests, even with mocks — a mocked blocking loop\n"
                "still does not return and the test process leaks memory\n"
                "until the host OOMs.\n"
                "Wrap the test command with an OS-level time + memory\n"
                "cap so a leaky test cannot take down the host:\n"
                "    ulimit -v 2097152 && timeout 60 <test command>\n"
                "(Equivalent on systems without bash:\n"
                "    prlimit --as=2147483648 -- timeout 60 <cmd>.)\n"
                "End your response with ONE line in the EXACT format:\n"
                "    RUN: <command to launch the app from project root>\n"
                "Examples (alphabetical, pick the row matching your stack):\n"
                "    RUN: cargo run --release\n"
                "    RUN: dotnet run --project src/\n"
                "    RUN: go run ./cmd/server\n"
                "    RUN: java -jar target/app.jar\n"
                "    RUN: node src/index.js\n"
                "    RUN: npm run dev\n"
                "    RUN: npx tsx src/index.ts\n"
                "    RUN: python src/main.py'\n\n"
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
                "   - exit_code != 0 with output containing ImportError /\n"
                "     ModuleNotFoundError / NameError / AttributeError\n"
                "     (Python), Cannot find module / TypeError\n"
                "     (Node / TS), undefined: ... / cannot find package\n"
                "     (Go), error[E0...] / unresolved import (Rust),\n"
                "     ClassNotFoundException / NoSuchMethodError (Java),\n"
                "     ``No such file``, or similar startup failures is\n"
                "     FAILURE.\n"
                "   - No RUN: line present in the response is FAILURE.\n\n"
                "3. If step 2 reported FAILURE, dispatch developer AGAIN\n"
                "   with the failure text and request a fix. Allow up to 3\n"
                "   attempts total.\n\n"
                "4. STOP after verification succeeds OR 3 attempts are\n"
                "   exhausted.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "scenario_implementation",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 4.5 — Behavioral Scenarios (language-agnostic):\n\n"
                "1. Read docs/behavioral_contract.json. If the file is\n"
                "   missing, dispatch architect with this task:\n"
                "   'Produce docs/behavioral_contract.json per the schema\n"
                "    in your agent definition. Cover at minimum: process\n"
                "    boot, the first interaction on the initial screen or\n"
                "    endpoint, every named view / route, and any state\n"
                "    persistence the requirement implies.'\n"
                "   Pass expected_artifacts=['docs/behavioral_contract.json'].\n"
                "   When it returns, re-read the file and continue.\n\n"
                "2. For EVERY scenario in scenarios[], build one task entry\n"
                "   for dispatch_tasks_parallel of this shape:\n"
                '     {agent_name: "developer",\n'
                '      step_id: "scenario_<id>",\n'
                '      phase: "scenario_implementation",\n'
                "      task_description: 'Implement scenario_id=<id>.\\n"
                "        Trigger: <trigger json>\\n"
                "        Effect: <effect json>\\n"
                "        Description: <scenario.description>\\n"
                "        Preconditions: <preconditions list>\\n\\n"
                "        Write tests/scenarios/<id>.<test_ext> using the\n"
                "        project test_runner. Drive the trigger and\n"
                "        assert the effect. Do NOT inspect class or\n"
                "        method names — the contract is observable\n"
                "        behavior only. When the test goes red, fix the\n"
                "        source files (under src/ or the language\n"
                "        idiomatic root) until it passes green. Iterate\n"
                "        up to 3 attempts. Run ONLY the scenario test\n"
                "        (<test_runner> tests/scenarios/<id>.<test_ext>),\n"
                "        not the whole suite.',\n"
                '      expected_artifacts: ["tests/scenarios/<id>.<test_ext>"]}\n'
                "   The <test_ext> mapping is fixed by language:\n"
                "   python→.py, typescript→.ts, javascript→.js,\n"
                "   go→.go, rust→.rs, java→.java, dart→.dart.\n\n"
                "3. Call dispatch_tasks_parallel with the JSON-encoded array\n"
                "   of all scenario tasks. The runtime cap throttles\n"
                "   concurrency; you do not need to batch.\n\n"
                "4. After it returns, inspect parallel_results[]. For each\n"
                "   entry whose status != 'completed', dispatch_task to\n"
                "   developer ONCE more with the failure detail. Do not\n"
                "   exceed 2 retry rounds.\n\n"
                "5. STOP. Do NOT call mark_complete. Do NOT run the full\n"
                "   test suite — that is Phase 5's job.",
            ),
            (
                "qa_testing",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 5 — Integration Testing (QA runs the suite):\n"
                "dispatch_task to qa_engineer with this task:\n"
                "'Write ONE integration test file at the path matching the\n"
                "project's test runner — e.g. tests/test_integration.py\n"
                "(pytest), tests/integration.test.ts (vitest / jest),\n"
                "internal/integration_test.go (Go), tests/integration.rs\n"
                "(Rust), src/test/java/.../IntegrationTest.java (Java).\n"
                "Cover cross-module interactions and end-to-end flows.\n"
                "Do NOT write per-module unit tests (developer already did\n"
                "that in Phase 3). After writing, RUN the full suite\n"
                "yourself using the project's full-suite test command:\n"
                "  - Python:     python -m pytest tests/ -q --tb=short\n"
                "  - TypeScript: npx vitest run  (or npx jest)\n"
                "  - Go:         go test ./...\n"
                "  - Rust:       cargo test\n"
                "  - Java:       mvn test\n"
                "Iterate up to 3 times until tests pass. Report the final\n"
                "test result in your response.'\n"
                "Pass expected_artifacts=[<the chosen integration test\n"
                "file path>, 'docs/qa_report.json'] so the runtime\n"
                "retries once if either is missing.\n"
                "After it completes, STOP.\n"
                "Do NOT call mark_complete.",
            ),
            (
                "delivery",
                f"Project requirement: {requirement}\n\n"
                "Execute Phase 6 — Delivery Report:\n\n"
                "Your job is to assemble a delivery report from the QA\n"
                "engineer's structured findings — NOT to re-run the test\n"
                "suite yourself. Re-running pytest / vitest / etc. here\n"
                "introduces flakiness (a test that intermittently fails\n"
                "may pass this time and the QA-flagged failure / product\n"
                "bugs disappear from the final report).\n\n"
                "1. Read docs/qa_report.json (REQUIRED). The QA engineer\n"
                "   wrote it in Phase 5. Schema:\n"
                "     {\n"
                '       "pytest": {"command": str, "passed": int,\n'
                '                  "failed": int, "skipped": int,\n'
                '                  "failed_tests": [str, ...]},\n'
                '       "ui_validation": {"required": bool,\n'
                '                          "verdict": "PASS|FAILED|\n'
                '                                       SKIPPED_HEADLESS_ONLY",\n'
                '                          "reason": str},\n'
                '       "product_bugs": [{"module": str, "function":\n'
                '                          str, "summary": str}, ...],\n'
                '       "integration_tests": {"file": str,\n'
                '                              "scenario_count": int}\n'
                "     }\n"
                "   If docs/qa_report.json is MISSING or invalid JSON, do\n"
                "   NOT fabricate numbers and do NOT silently re-run\n"
                "   tests. Instead: dispatch qa_engineer to produce the\n"
                "   missing report (the QA agent's prompt requires it),\n"
                "   then re-read the file. Only after a valid report is\n"
                "   on disk continue to step 2.\n\n"
                "2. Collect non-test development metrics that QA does NOT\n"
                "   produce — source file count + per-file LOC. Read the\n"
                "   project's language from docs/architecture.md (or\n"
                "   docs/stack_contract.json if present) BEFORE picking\n"
                "   the file glob; do NOT default to Python. Run each\n"
                "   find twice: once with ``| wc -l`` for the count,\n"
                "   once with ``-exec wc -l {} + | sort -rn | head -30``\n"
                "   for per-file LOC.\n"
                "      - Python:     find src -type f -name '*.py'\n"
                "      - TypeScript: find src -type f \\( -name '*.ts' -o -name '*.tsx' \\)\n"
                "      - Go:         find . -type f -name '*.go' -not -path './vendor/*'\n"
                "      - Rust:       find src -type f -name '*.rs'\n"
                "      - Java:       find src -type f -name '*.java'\n"
                "      - C# / .NET:  find . -type f -name '*.cs' -not -path './bin/*' -not -path './obj/*'\n"
                "3. Dispatch product_manager to write the final report.\n"
                "   Pass expected_artifacts=['docs/delivery_report.md'].\n"
                "   Embed the qa_report.json fields VERBATIM into the\n"
                "   task description so product_manager cannot rewrite\n"
                "   the conclusion. Use a task description like:\n\n"
                "   'Write docs/delivery_report.md — the project delivery\n"
                "   report. Use the data I pass you; do not invent\n"
                "   numbers. The Known Issues section MUST list every\n"
                "   entry from qa_report.product_bugs verbatim AND every\n"
                "   test in qa_report.pytest.failed_tests verbatim. If\n"
                "   product_bugs is empty AND failed_tests is empty AND\n"
                "   ui_validation.verdict is PASS or SKIPPED_HEADLESS_ONLY,\n"
                '   write "none". Otherwise enumerate them. Required\n'
                "   sections:\n"
                "   1. Executive Summary — one paragraph, what was built\n"
                "      and whether it is production-ready (DERIVE from\n"
                "      qa_report — production-ready iff failed==0 AND\n"
                "      product_bugs is empty AND ui_validation.verdict\n"
                "      != FAILED).\n"
                "   2. Design — summarize docs/architecture.md (read it\n"
                "      yourself) in a few bullets: module decomposition,\n"
                "      key technology choices (language, frameworks).\n"
                "   3. Implementation Metrics — source file count, LOC,\n"
                "      top files by LOC, entry point location + RUN cmd.\n"
                "   4. Testing Metrics — copy qa_report.pytest fields\n"
                "      verbatim: passed / failed / skipped counts and\n"
                "      pass rate (passed / (passed+failed+skipped)).\n"
                "      Do NOT re-run pytest yourself.\n"
                "   5. UI Validation — copy qa_report.ui_validation\n"
                "      verbatim (required, verdict, reason).\n"
                "   6. Known Issues — list as required above.\n"
                "   7. Conclusion — one or two sentences on readiness.\n\n"
                "   RAW QA REPORT JSON (cite verbatim, do not paraphrase):\n"
                "   <paste the contents of docs/qa_report.json>\n"
                "   RAW LOC TOOL OUTPUTS (from step 2):\n"
                "   <paste the find / wc -l outputs>'\n\n"
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
                    "Run the project's full-suite test command to check "
                    "(python -m pytest tests/ for Python, npx vitest run for "
                    "TypeScript/vitest, npx jest for jest, go test ./... for Go, "
                    "cargo test for Rust, mvn test for Java). "
                    "If tests fail, dispatch developer to fix. "
                    "Do NOT proceed until tests pass."
                )
            # Tests pass → dispatch main entry point
            return (
                "Module tests pass. Now dispatch developer to write the main "
                "entry-point file at the path matching the project's language "
                "(src/main.py for Python, src/index.ts for TypeScript, "
                "cmd/<app>/main.go for Go, src/main.rs for Rust, "
                "src/main/java/.../App.java for Java, src/Program.cs for .NET). "
                "Call:\n"
                "dispatch_task(agent_name='developer', "
                "task_description='Write the main entry point that "
                "imports and uses ALL implemented modules (read src/ to see what exists). "
                "Create real bootstrap logic — initialise the modules and run the "
                "main loop / start the server / open the window etc. NOT a stub. "
                "Also write the corresponding unit test file in the language\\'s "
                "idiomatic test location to verify the entry initialises and runs.', "
                "step_id='step_integrate_main', phase='implementation')"
            )

        if main_dispatched and "qa_engineer" not in agents_dispatched:
            return (
                "Main entry point done. Dispatch qa_engineer for integration testing.\n"
                "dispatch_task(agent_name='qa_engineer', "
                "task_description='Read src/ and tests/ (or the language\\'s "
                "idiomatic source/test directories) to understand the system. "
                "Write integration tests at the path matching the project\\'s "
                "test runner (tests/test_integration.py for pytest, "
                "tests/integration.test.ts for vitest/jest, "
                "internal/integration_test.go for Go, tests/integration.rs for "
                "Rust, src/test/java/.../IntegrationTest.java for Java) covering "
                "cross-module interactions.', "
                "step_id='step_integration_test', phase='verification')"
            )

        if "qa_engineer" in agents_dispatched:
            return (
                "All phases done. Run the project's full-suite test command "
                "(python -m pytest tests/ / npx vitest run / npx jest / "
                "go test ./... / cargo test / mvn test). "
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
