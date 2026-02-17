"""On-demand interactive session for the multi-agent development team."""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable

from .artifact import ArtifactType
from .message import MessageType
from .orchestrator import Orchestrator
from .workflow import WorkflowEngine


class UserCommand(Enum):
    """Commands available in on-demand mode."""

    ADD_REQUIREMENT = "add"
    BUG = "bug"
    STATUS = "status"
    ARTIFACTS = "artifacts"
    RUN_PHASE = "phase"
    RUN_WORKFLOW = "workflow"
    ASK = "ask"
    HELP = "help"
    QUIT = "quit"


# Maps first token to command enum
_COMMAND_ALIASES: dict[str, UserCommand] = {
    "add": UserCommand.ADD_REQUIREMENT,
    "requirement": UserCommand.ADD_REQUIREMENT,
    "req": UserCommand.ADD_REQUIREMENT,
    "bug": UserCommand.BUG,
    "fix": UserCommand.BUG,
    "status": UserCommand.STATUS,
    "artifacts": UserCommand.ARTIFACTS,
    "artifact": UserCommand.ARTIFACTS,
    "phase": UserCommand.RUN_PHASE,
    "workflow": UserCommand.RUN_WORKFLOW,
    "run": UserCommand.RUN_WORKFLOW,
    "ask": UserCommand.ASK,
    "help": UserCommand.HELP,
    "quit": UserCommand.QUIT,
    "exit": UserCommand.QUIT,
    "q": UserCommand.QUIT,
}


def parse_command(raw: str) -> tuple[UserCommand, str]:
    """Parse a raw input line into a command and its argument text.

    Returns:
        Tuple of (command, remaining_text).  ``remaining_text`` is the
        original input stripped of the leading command token.
    """
    stripped = raw.strip()
    if not stripped:
        return UserCommand.HELP, ""

    parts = stripped.split(None, 1)
    token = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    cmd = _COMMAND_ALIASES.get(token)
    if cmd is None:
        # Treat unrecognised input as a new requirement by default
        return UserCommand.ADD_REQUIREMENT, stripped

    return cmd, rest


class OnDemandSession:
    """Interactive session that keeps the agent team alive for ad-hoc commands.

    The session wraps an :class:`Orchestrator` and provides a REPL-style
    interface.  Users can add new requirements, report bugs, check status,
    and trigger workflow phases at any time.
    """

    PROMPT = "aise> "

    def __init__(
        self,
        orchestrator: Orchestrator,
        project_name: str = "My Project",
        *,
        output: Callable[[str], None] | None = None,
    ) -> None:
        self.orchestrator = orchestrator
        self.project_name = project_name
        self._print = output or print
        self._running = False
        self._history: list[dict[str, Any]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def history(self) -> list[dict[str, Any]]:
        """Command execution history."""
        return list(self._history)

    def handle_input(self, raw: str) -> dict[str, Any]:
        """Process a single user input line and return a result dict.

        This is the main entry-point for both the interactive loop and
        programmatic usage (e.g. testing).
        """
        cmd, text = parse_command(raw)
        result: dict[str, Any]

        dispatch: dict[UserCommand, Callable[[str], dict[str, Any]]] = {
            UserCommand.ADD_REQUIREMENT: self._handle_add_requirement,
            UserCommand.BUG: self._handle_bug,
            UserCommand.STATUS: self._handle_status,
            UserCommand.ARTIFACTS: self._handle_artifacts,
            UserCommand.RUN_PHASE: self._handle_run_phase,
            UserCommand.RUN_WORKFLOW: self._handle_run_workflow,
            UserCommand.ASK: self._handle_ask,
            UserCommand.HELP: self._handle_help,
            UserCommand.QUIT: self._handle_quit,
        }

        handler = dispatch.get(cmd, self._handle_help)
        result = handler(text)
        result["command"] = cmd.value
        self._history.append(result)
        return result

    def start(self, *, input_fn: Callable[[], str] | None = None) -> None:
        """Start the interactive REPL loop.

        Args:
            input_fn: Optional callable that returns user input (for testing).
                      Defaults to ``input()``.
        """
        self._running = True
        self._print(_BANNER)
        self._print(f"Project: {self.project_name}")
        self._print("Type 'help' for available commands.\n")

        read_input = input_fn or (lambda: input(self.PROMPT))

        while self._running:
            try:
                raw = read_input()
            except (EOFError, KeyboardInterrupt):
                self._print("\nSession ended.")
                break

            result = self.handle_input(raw)

            # Print human-friendly output
            output = result.get("output", "")
            if output:
                self._print(output)

        self._running = False

    # ------------------------------------------------------------------
    # Command handlers
    # ------------------------------------------------------------------

    def _handle_add_requirement(self, text: str) -> dict[str, Any]:
        if not text.strip():
            return {
                "status": "error",
                "output": "Please provide a requirement. Usage: add <requirement text>",
            }

        try:
            # Run the requirement through the PM agent pipeline
            artifact_id = self.orchestrator.execute_task(
                "product_manager",
                "requirement_analysis",
                {"raw_requirements": text},
                self.project_name,
            )
            artifact = self.orchestrator.artifact_store.get(artifact_id)
            content = artifact.content if artifact else {}
            n_func = len(content.get("functional_requirements", []))
            n_nfunc = len(content.get("non_functional_requirements", []))

            # Also generate user stories for the new requirement
            story_id = None
            try:
                story_id = self.orchestrator.execute_task(
                    "product_manager",
                    "user_story_writing",
                    {"raw_requirements": text},
                    self.project_name,
                )
            except Exception:
                pass  # non-critical

            output_lines = [
                f"Requirement added and analysed (artifact {artifact_id}).",
                f"  Functional: {n_func}  |  Non-functional: {n_nfunc}",
            ]
            if story_id:
                output_lines.append(f"  User stories generated (artifact {story_id}).")

            # Notify all agents via message bus
            self.orchestrator.message_bus.publish(
                _make_notification(
                    "user",
                    "broadcast",
                    f"New requirement added: {text[:120]}",
                )
            )

            return {
                "status": "ok",
                "artifact_id": artifact_id,
                "output": "\n".join(output_lines),
            }

        except Exception as e:
            return {"status": "error", "output": f"Failed to add requirement: {e}"}

    def _handle_bug(self, text: str) -> dict[str, Any]:
        if not text.strip():
            return {
                "status": "error",
                "output": "Please describe the bug. Usage: bug <description>",
            }

        try:
            bug_reports = [{"id": "BUG-USER", "description": text}]
            artifact_id = self.orchestrator.execute_task(
                "developer",
                "bug_fix",
                {"bug_reports": bug_reports},
                self.project_name,
            )
            artifact = self.orchestrator.artifact_store.get(artifact_id)
            content = artifact.content if artifact else {}
            fixed = content.get("fixed_count", 0)
            needs_inv = content.get("needs_investigation", 0)

            output_lines = [
                f"Bug report processed (artifact {artifact_id}).",
                f"  Fixed: {fixed}  |  Needs investigation: {needs_inv}",
            ]

            self.orchestrator.message_bus.publish(
                _make_notification("user", "broadcast", f"Bug reported: {text[:120]}")
            )

            return {
                "status": "ok",
                "artifact_id": artifact_id,
                "output": "\n".join(output_lines),
            }

        except Exception as e:
            return {"status": "error", "output": f"Failed to process bug report: {e}"}

    def _handle_status(self, text: str) -> dict[str, Any]:
        store = self.orchestrator.artifact_store
        agents = self.orchestrator.agents
        bus = self.orchestrator.message_bus

        lines = [f"Project: {self.project_name}", ""]

        # Agents summary
        lines.append(f"Agents registered: {len(agents)}")
        for name, agent in agents.items():
            lines.append(f"  {agent.role.value:20s}  {name}")

        # Artifacts summary
        all_artifacts = store.all()
        lines.append(f"\nArtifacts: {len(all_artifacts)}")
        type_counts: dict[str, int] = {}
        for a in all_artifacts:
            type_counts[a.artifact_type.value] = type_counts.get(a.artifact_type.value, 0) + 1
        for atype, count in sorted(type_counts.items()):
            lines.append(f"  {atype:25s}  {count}")

        # Messages summary
        messages = bus.get_history()
        lines.append(f"\nMessages exchanged: {len(messages)}")

        # Commands issued in this session
        lines.append(f"Commands in this session: {len(self._history)}")

        return {"status": "ok", "output": "\n".join(lines)}

    def _handle_artifacts(self, text: str) -> dict[str, Any]:
        store = self.orchestrator.artifact_store
        all_artifacts = store.all()

        if not all_artifacts:
            return {"status": "ok", "output": "No artifacts yet."}

        # Optional filter
        filter_type = text.strip().lower() if text.strip() else None

        lines = []
        for artifact in sorted(all_artifacts, key=lambda a: a.created_at):
            if filter_type and filter_type not in artifact.artifact_type.value:
                continue
            lines.append(
                f"  {artifact.id}  {artifact.artifact_type.value:25s}  "
                f"v{artifact.version}  {artifact.status.value:10s}  by {artifact.producer}"
            )

        if not lines:
            return {"status": "ok", "output": f"No artifacts matching '{filter_type}'."}

        header = f"Artifacts ({len(lines)}):"
        return {"status": "ok", "output": "\n".join([header] + lines)}

    def _handle_run_phase(self, text: str) -> dict[str, Any]:
        phase_name = text.strip().lower()
        if not phase_name:
            return {
                "status": "error",
                "output": "Please specify a phase. Usage: phase <requirements|design|implementation|testing>",
            }

        workflow = WorkflowEngine.create_default_workflow()

        # Find the matching phase
        target_phase = None
        for i, phase in enumerate(workflow.phases):
            if phase.name == phase_name:
                target_phase = phase
                workflow.current_phase_index = i
                break

        if target_phase is None:
            available = ", ".join(p.name for p in workflow.phases)
            return {
                "status": "error",
                "output": f"Unknown phase '{phase_name}'. Available: {available}",
            }

        # Build a single-phase workflow to execute
        from .workflow import Workflow

        single = Workflow(name=f"on_demand_{phase_name}")
        single.add_phase(target_phase)

        try:
            results = self.orchestrator.run_workflow(
                single,
                {"raw_requirements": self._gather_requirements()},
                self.project_name,
            )

            lines = [f"Phase '{phase_name}' completed."]
            for r in results:
                status = r.get("status", "unknown")
                lines.append(f"  Status: {status}")
                for tkey, tres in r.get("tasks", {}).items():
                    lines.append(f"    {tkey}: {tres.get('status', '?')}")
                review = r.get("review")
                if review:
                    lines.append(f"  Review: {'approved' if review.get('approved') else 'rejected'}")

            return {"status": "ok", "output": "\n".join(lines)}

        except Exception as e:
            return {"status": "error", "output": f"Phase execution failed: {e}"}

    def _handle_run_workflow(self, text: str) -> dict[str, Any]:
        reqs = self._gather_requirements()
        if not reqs:
            return {
                "status": "error",
                "output": "No requirements found. Add requirements first with: add <text>",
            }

        try:
            results = self.orchestrator.run_default_workflow(
                {"raw_requirements": reqs},
                self.project_name,
            )

            lines = ["Workflow completed."]
            for r in results:
                phase = r.get("phase", "?")
                status = r.get("status", "?")
                lines.append(f"  {phase}: {status}")

            return {"status": "ok", "results": results, "output": "\n".join(lines)}

        except Exception as e:
            return {"status": "error", "output": f"Workflow execution failed: {e}"}

    def _handle_ask(self, text: str) -> dict[str, Any]:
        """Route a freeform question to the Project Manager for a progress update."""
        if not text.strip():
            return {"status": "error", "output": "Usage: ask <question or instruction>"}

        # Use the project manager's progress_tracking to report current state
        try:
            artifact_id = self.orchestrator.execute_task(
                "project_manager",
                "progress_tracking",
                {},
                self.project_name,
            )
            artifact = self.orchestrator.artifact_store.get(artifact_id)
            content = artifact.content if artifact else {}
            phases = content.get("phases", {})
            progress = content.get("progress_percentage", 0)

            lines = [f"Project Manager status report (progress: {progress:.0f}%):"]
            if isinstance(phases, dict):
                for phase_name, phase_info in phases.items():
                    complete = "done" if phase_info.get("complete") else "in_progress"
                    lines.append(f"  {phase_name:20s}  {complete}")
            else:
                for phase in phases:
                    lines.append(
                        f"  {phase.get('phase', '?'):20s}  "
                        f"{phase.get('completion_percentage', 0):.0f}%  "
                        f"{phase.get('status', '?')}"
                    )

            return {
                "status": "ok",
                "artifact_id": artifact_id,
                "output": "\n".join(lines),
            }

        except Exception as e:
            return {"status": "error", "output": f"Failed: {e}"}

    def _handle_help(self, text: str) -> dict[str, Any]:
        return {"status": "ok", "output": _HELP_TEXT}

    def _handle_quit(self, text: str) -> dict[str, Any]:
        self._running = False
        return {"status": "ok", "output": "Goodbye!"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _gather_requirements(self) -> str:
        """Collect all stored requirements into a single text block."""
        store = self.orchestrator.artifact_store
        artifacts = store.get_by_type(ArtifactType.REQUIREMENTS)
        if not artifacts:
            return ""

        parts = []
        for art in artifacts:
            raw = art.content.get("raw_input", "")
            if raw:
                parts.append(str(raw))
        return "\n".join(parts)


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _make_notification(sender: str, receiver: str, text: str):
    """Create a notification Message without importing at module level."""
    from .message import Message

    return Message(
        sender=sender,
        receiver=receiver,
        msg_type=MessageType.NOTIFICATION,
        content={"text": text},
    )


_BANNER = r"""
 ___  ___  ___  ___
|   ||   ||__ ||   |  Multi-Agent Development Team
|___||___| __|||___|  On-Demand Interactive Mode
"""

_HELP_TEXT = """\
Available commands:
  add <text>         Add a new requirement and run analysis
  bug <description>  Report a bug for the developer to fix
  status             Show project and team status
  artifacts [type]   List artifacts (optionally filter by type)
  phase <name>       Run a specific phase (requirements|design|implementation|testing)
  workflow           Run the full SDLC workflow
  ask <question>     Ask the Project Manager for a progress report
  help               Show this help message
  quit               Exit the session
"""
