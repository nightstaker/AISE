"""Multi-project interactive session for managing multiple concurrent projects."""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable

from ..config import GitHubConfig, ProjectConfig
from ..core.agent import AgentRole
from .project_manager import ProjectManager


class MultiProjectCommand(Enum):
    """Commands available in multi-project mode."""

    CREATE = "create"
    SWITCH = "switch"
    LIST = "list"
    STATUS = "status"
    ADD = "add"
    RUN = "run"
    DELETE = "delete"
    PAUSE = "pause"
    RESUME = "resume"
    COMPLETE = "complete"
    HELP = "help"
    QUIT = "quit"


# Maps first token to command enum
_COMMAND_ALIASES: dict[str, MultiProjectCommand] = {
    "create": MultiProjectCommand.CREATE,
    "new": MultiProjectCommand.CREATE,
    "switch": MultiProjectCommand.SWITCH,
    "use": MultiProjectCommand.SWITCH,
    "list": MultiProjectCommand.LIST,
    "ls": MultiProjectCommand.LIST,
    "projects": MultiProjectCommand.LIST,
    "status": MultiProjectCommand.STATUS,
    "info": MultiProjectCommand.STATUS,
    "add": MultiProjectCommand.ADD,
    "requirement": MultiProjectCommand.ADD,
    "req": MultiProjectCommand.ADD,
    "run": MultiProjectCommand.RUN,
    "workflow": MultiProjectCommand.RUN,
    "delete": MultiProjectCommand.DELETE,
    "remove": MultiProjectCommand.DELETE,
    "rm": MultiProjectCommand.DELETE,
    "pause": MultiProjectCommand.PAUSE,
    "resume": MultiProjectCommand.RESUME,
    "complete": MultiProjectCommand.COMPLETE,
    "finish": MultiProjectCommand.COMPLETE,
    "help": MultiProjectCommand.HELP,
    "h": MultiProjectCommand.HELP,
    "?": MultiProjectCommand.HELP,
    "quit": MultiProjectCommand.QUIT,
    "exit": MultiProjectCommand.QUIT,
    "q": MultiProjectCommand.QUIT,
}


def parse_command(raw: str) -> tuple[MultiProjectCommand, str]:
    """Parse a raw input line into a command and its argument text.

    Returns:
        Tuple of (command, remaining_text)
    """
    stripped = raw.strip()
    if not stripped:
        return MultiProjectCommand.HELP, ""

    parts = stripped.split(None, 1)
    token = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    cmd = _COMMAND_ALIASES.get(token)
    if cmd is None:
        return MultiProjectCommand.HELP, stripped

    return cmd, rest


class MultiProjectSession:
    """Interactive session for managing multiple concurrent projects.

    Provides a REPL interface to create, switch, and manage multiple projects,
    each with its own isolated team of agents.
    """

    PROMPT = "aise-multi> "

    def __init__(
        self,
        *,
        output: Callable[[str], None] | None = None,
    ) -> None:
        """Initialize multi-project session.

        Args:
            output: Optional output function (default: print)
        """
        self.project_manager = ProjectManager()
        self.current_project_id: str | None = None
        self._print = output or print
        self._running = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Check if session is running."""
        return self._running

    def start(self) -> None:
        """Start the interactive session (REPL)."""
        self._running = True
        self._print("\nAISE Multi-Project Session")
        self._print("=" * 50)
        self._print("Type 'help' for available commands, 'quit' to exit\n")

        while self._running:
            try:
                user_input = input(self.PROMPT)
                result = self.handle_input(user_input)
                output_text = result.get("output", "")
                if output_text:
                    self._print(output_text)
            except (KeyboardInterrupt, EOFError):
                self._print("\nExiting...")
                self._running = False
                break

    def handle_input(self, user_input: str) -> dict[str, Any]:
        """Handle a user input command.

        Args:
            user_input: Raw user input string

        Returns:
            Dictionary with 'output' key containing response text
        """
        cmd, args = parse_command(user_input)

        handlers = {
            MultiProjectCommand.CREATE: self._handle_create,
            MultiProjectCommand.SWITCH: self._handle_switch,
            MultiProjectCommand.LIST: self._handle_list,
            MultiProjectCommand.STATUS: self._handle_status,
            MultiProjectCommand.ADD: self._handle_add,
            MultiProjectCommand.RUN: self._handle_run,
            MultiProjectCommand.DELETE: self._handle_delete,
            MultiProjectCommand.PAUSE: self._handle_pause,
            MultiProjectCommand.RESUME: self._handle_resume,
            MultiProjectCommand.COMPLETE: self._handle_complete,
            MultiProjectCommand.HELP: self._handle_help,
            MultiProjectCommand.QUIT: self._handle_quit,
        }

        handler = handlers.get(cmd)
        if handler:
            return handler(args)

        return {"output": "Unknown command. Type 'help' for available commands."}

    # ------------------------------------------------------------------
    # Command Handlers
    # ------------------------------------------------------------------

    def _handle_create(self, args: str) -> dict[str, Any]:
        """Create a new project.

        Usage: create <project_name> [--github] [--agents role:count,...]

        Examples:
            create my-app
            create ecommerce --github --agents developer:3,qa_engineer:2
        """
        if not args:
            return {"output": "Usage: create <project_name> [--github] [--agents role:count,...]"}

        parts = args.split()
        project_name = parts[0]

        # Parse flags
        github_mode = "--github" in args
        agent_counts_str = None
        for i, part in enumerate(parts):
            if part == "--agents" and i + 1 < len(parts):
                agent_counts_str = parts[i + 1]
                break

        # Parse agent counts
        agent_counts = self._parse_agent_counts(agent_counts_str) if agent_counts_str else None

        # Create config
        config = ProjectConfig(
            project_name=project_name,
            development_mode="github" if github_mode else "local",
        )

        # Create project
        try:
            project_id = self.project_manager.create_project(
                project_name,
                config,
                agent_counts,
            )

            # Auto-switch to new project
            self.current_project_id = project_id

            project = self.project_manager.get_project(project_id)
            total_agents = project.agent_count if project else 0

            output = f"✓ Created project '{project_name}' (ID: {project_id})\n"
            output += f"  Mode: {config.development_mode}\n"
            output += f"  Agents: {total_agents}\n"
            output += f"  Status: Active (current project)"

            return {"output": output}

        except Exception as e:
            return {"output": f"Error creating project: {e}"}

    def _handle_switch(self, args: str) -> dict[str, Any]:
        """Switch to a different project.

        Usage: switch <project_id>
        """
        if not args:
            return {"output": "Usage: switch <project_id>"}

        project_id = args.strip()
        project = self.project_manager.get_project(project_id)

        if not project:
            return {"output": f"Error: Project '{project_id}' not found"}

        self.current_project_id = project_id
        return {"output": f"✓ Switched to project '{project.project_name}' ({project_id})"}

    def _handle_list(self, args: str) -> dict[str, Any]:
        """List all projects.

        Usage: list
        """
        projects = self.project_manager.list_projects()

        if not projects:
            return {"output": "No projects yet. Use 'create <name>' to start a new project."}

        output = f"\nProjects ({len(projects)}):\n"
        output += "=" * 70 + "\n"

        for project in projects:
            current_marker = " *" if project.project_id == self.current_project_id else "  "
            output += f"{current_marker} {project.project_id}: {project.project_name}\n"
            output += f"     Status: {project.status.value} | "
            output += f"Mode: {project.development_mode} | "
            output += f"Agents: {project.agent_count}\n"

        return {"output": output}

    def _handle_status(self, args: str) -> dict[str, Any]:
        """Show current project status.

        Usage: status
        """
        if not self.current_project_id:
            return {"output": "No project selected. Use 'list' to see projects or 'create' to start one."}

        project = self.project_manager.get_project(self.current_project_id)
        if not project:
            return {"output": "Error: Current project not found"}

        info = project.get_info()
        output = f"\nProject: {info['project_name']} ({info['project_id']})\n"
        output += "=" * 70 + "\n"
        output += f"Status: {info['status']}\n"
        output += f"Mode: {info['development_mode']}\n"
        output += f"Agents: {info['agent_count']}\n"
        output += f"Created: {info['created_at']}\n"
        output += f"Updated: {info['updated_at']}\n"

        # List agents
        output += "\nAgents:\n"
        for name, agent in project.orchestrator.agents.items():
            output += f"  - {name} ({agent.role.value})\n"

        return {"output": output}

    def _handle_add(self, args: str) -> dict[str, Any]:
        """Add requirement to current project.

        Usage: add <requirement text>
        """
        if not self.current_project_id:
            return {"output": "No project selected. Use 'switch <project_id>' first."}

        if not args:
            return {"output": "Usage: add <requirement text>"}

        project = self.project_manager.get_project(self.current_project_id)
        if not project:
            return {"output": "Error: Current project not found"}

        # Store requirement as an artifact
        from .artifact import Artifact, ArtifactType

        artifact = Artifact(
            type=ArtifactType.REQUIREMENTS,
            content={"raw_requirements": args},
            metadata={"source": "user_input"},
        )
        project.orchestrator.artifact_store.store(artifact, project.project_name)

        return {"output": f"✓ Added requirement to '{project.project_name}':\n  {args}"}

    def _handle_run(self, args: str) -> dict[str, Any]:
        """Run workflow for current project.

        Usage: run [requirement text]
        """
        if not self.current_project_id:
            return {"output": "No project selected. Use 'switch <project_id>' first."}

        project = self.project_manager.get_project(self.current_project_id)
        if not project:
            return {"output": "Error: Current project not found"}

        # Get requirement text
        requirement_text = args if args else "Build the requested features"

        output = f"Running workflow for '{project.project_name}'...\n"

        try:
            results = self.project_manager.run_project_workflow(
                self.current_project_id,
                {"raw_requirements": requirement_text},
            )

            output += f"\nCompleted {len(results)} phases:\n"
            for i, result in enumerate(results, 1):
                phase_name = result.get("phase", f"Phase {i}")
                status = result.get("status", "unknown")
                output += f"  {i}. {phase_name}: {status}\n"

            return {"output": output}

        except Exception as e:
            return {"output": f"Error running workflow: {e}"}

    def _handle_delete(self, args: str) -> dict[str, Any]:
        """Delete a project.

        Usage: delete <project_id>
        """
        if not args:
            return {"output": "Usage: delete <project_id>"}

        project_id = args.strip()
        project = self.project_manager.get_project(project_id)

        if not project:
            return {"output": f"Error: Project '{project_id}' not found"}

        project_name = project.project_name
        success = self.project_manager.delete_project(project_id)

        if success:
            if self.current_project_id == project_id:
                self.current_project_id = None
            return {"output": f"✓ Deleted project '{project_name}' ({project_id})"}

        return {"output": "Error deleting project"}

    def _handle_pause(self, args: str) -> dict[str, Any]:
        """Pause a project.

        Usage: pause [project_id]
        """
        project_id = args.strip() if args else self.current_project_id

        if not project_id:
            return {"output": "Usage: pause [project_id]"}

        success = self.project_manager.pause_project(project_id)
        if success:
            return {"output": f"✓ Paused project {project_id}"}
        return {"output": f"Error: Could not pause project {project_id}"}

    def _handle_resume(self, args: str) -> dict[str, Any]:
        """Resume a paused project.

        Usage: resume [project_id]
        """
        project_id = args.strip() if args else self.current_project_id

        if not project_id:
            return {"output": "Usage: resume [project_id]"}

        success = self.project_manager.resume_project(project_id)
        if success:
            return {"output": f"✓ Resumed project {project_id}"}
        return {"output": f"Error: Could not resume project {project_id}"}

    def _handle_complete(self, args: str) -> dict[str, Any]:
        """Mark a project as completed.

        Usage: complete [project_id]
        """
        project_id = args.strip() if args else self.current_project_id

        if not project_id:
            return {"output": "Usage: complete [project_id]"}

        success = self.project_manager.complete_project(project_id)
        if success:
            return {"output": f"✓ Marked project {project_id} as completed"}
        return {"output": f"Error: Could not complete project {project_id}"}

    def _handle_help(self, args: str) -> dict[str, Any]:
        """Show help message."""
        help_text = """
Available Commands:
═══════════════════════════════════════════════════════════════════

Project Management:
  create <name> [--github] [--agents role:count,...]
      Create a new project
      Examples:
        create my-app
        create ecommerce --github --agents developer:3,qa_engineer:2

  switch <project_id>
      Switch to a different project

  list
      List all projects

  status
      Show current project status

  delete <project_id>
      Delete a project

  pause [project_id]
      Pause a project

  resume [project_id]
      Resume a paused project

  complete [project_id]
      Mark a project as completed

Workflow:
  add <requirement>
      Add a requirement to the current project

  run [requirement]
      Run the workflow for the current project

General:
  help
      Show this help message

  quit
      Exit the session

Agent Counts Format:
  --agents role:count,role:count,...
  Available roles: developer, qa_engineer, architect, product_manager,
                  team_lead, team_manager
  Example: --agents developer:3,qa_engineer:2,architect:1
"""
        return {"output": help_text}

    def _handle_quit(self, args: str) -> dict[str, Any]:
        """Quit the session."""
        self._running = False
        return {"output": "Goodbye!"}

    # ------------------------------------------------------------------
    # Helper Methods
    # ------------------------------------------------------------------

    def _parse_agent_counts(self, counts_str: str | None) -> dict[AgentRole, int] | None:
        """Parse agent counts string.

        Format: role:count,role:count,...
        Example: developer:3,qa_engineer:2

        Returns:
            Dictionary mapping AgentRole to count, or None if parsing fails
        """
        if not counts_str:
            return None

        role_mapping = {
            "product_manager": AgentRole.PRODUCT_MANAGER,
            "architect": AgentRole.ARCHITECT,
            "developer": AgentRole.DEVELOPER,
            "qa_engineer": AgentRole.QA_ENGINEER,
            "team_lead": AgentRole.TEAM_LEAD,
            "team_manager": AgentRole.TEAM_MANAGER,
        }

        agent_counts: dict[AgentRole, int] = {}

        try:
            pairs = counts_str.split(",")
            for pair in pairs:
                role_str, count_str = pair.split(":")
                role_str = role_str.strip().lower()
                count = int(count_str.strip())

                if role_str in role_mapping:
                    agent_counts[role_mapping[role_str]] = count

            return agent_counts if agent_counts else None

        except (ValueError, KeyError):
            return None
