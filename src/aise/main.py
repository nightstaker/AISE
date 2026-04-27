"""CLI entry point for the AISE multi-agent development team."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from .agents import (
    ArchitectAgent,
    DeveloperAgent,
    ProductManagerAgent,
    ProjectManagerAgent,
    QAEngineerAgent,
    RDDirectorAgent,
    ReviewerAgent,
)
from .config import ProjectConfig
from .core.agent import AgentRole
from .core.orchestrator import Orchestrator
from .utils.logging import configure_logging
from .whatsapp.client import WhatsAppConfig
from .whatsapp.session import WhatsAppGroupSession


def _get_agent_class(role: AgentRole):
    """Map AgentRole to agent class constructor.

    Args:
        role: The agent role

    Returns:
        Agent class constructor

    Raises:
        ValueError: If role is unknown
    """
    mapping = {
        AgentRole.PRODUCT_MANAGER: ProductManagerAgent,
        AgentRole.ARCHITECT: ArchitectAgent,
        AgentRole.DEVELOPER: DeveloperAgent,
        AgentRole.QA_ENGINEER: QAEngineerAgent,
        AgentRole.PROJECT_MANAGER: ProjectManagerAgent,
        AgentRole.RD_DIRECTOR: RDDirectorAgent,
        AgentRole.REVIEWER: ReviewerAgent,
    }
    if role not in mapping:
        raise ValueError(f"Unknown agent role: {role}")
    return mapping[role]


def create_team(
    config: ProjectConfig | None = None,
    agent_counts: dict[AgentRole, int] | None = None,
    *,
    project_root: str | None = None,
) -> Orchestrator:
    """Create a fully configured development team.

    Args:
        config: Optional project configuration
        agent_counts: Optional dict mapping AgentRole to count.
                     Default: 1 agent per role (backward compatible)
                     Example: {AgentRole.DEVELOPER: 3, AgentRole.QA_ENGINEER: 2}

    Returns:
        An Orchestrator with all agents registered and ready.
    """
    config = config or ProjectConfig()
    configure_logging(config.logging)

    # Default: 1 agent per role (backward compatible).
    # Reviewer is only included in GitHub mode.
    if agent_counts is None:
        agent_counts = {role: 1 for role in AgentRole if role != AgentRole.REVIEWER}
        if config.is_github_mode:
            agent_counts[AgentRole.REVIEWER] = 1

    orchestrator = Orchestrator(project_root=project_root)
    bus = orchestrator.message_bus
    store = orchestrator.artifact_store

    # Create agents based on agent_counts
    for role, count in agent_counts.items():
        if count < 1:
            continue  # Skip if count is 0 or negative

        agent_class = _get_agent_class(role)

        for i in range(1, count + 1):
            # Generate agent name
            if count == 1:
                # Single agent: keep simple name for backward compatibility
                agent_name = role.value
            else:
                # Multiple agents: use indexed names
                agent_name = f"{role.value}_{i}"

            # Create agent instance
            agent = agent_class(
                message_bus=bus,
                artifact_store=store,
                model_config=config.get_model_config(role.value),
            )

            # Override agent name
            agent.name = agent_name

            # Check if agent is enabled in config
            agent_config = config.agents.get(role.value)
            if agent_config is None or agent_config.enabled:
                orchestrator.register_agent(agent)

    return orchestrator


def run_project(requirements: str, project_name: str = "My Project") -> str:
    """Run the full project workflow via RuntimeManager + ProjectSession.

    The project_manager agent autonomously selects a process, assembles
    a team, plans the workflow, and drives execution via A2A protocol.

    Args:
        requirements: Raw requirements text.
        project_name: Name of the project.

    Returns:
        The project_manager's delivery report.
    """
    from .runtime import ProjectSession, RuntimeManager

    config = _load_cli_project_config(project_name)
    manager = RuntimeManager(config=config)
    manager.start()
    try:
        # Create project output directory
        projects_root = Path("projects")
        projects_root.mkdir(parents=True, exist_ok=True)
        project_dir = projects_root / project_name.lower().replace(" ", "-")
        project_dir.mkdir(parents=True, exist_ok=True)

        session = ProjectSession(manager, project_root=str(project_dir))
        return session.run(requirements)
    finally:
        manager.stop()


def _project_root_for(project_name: str) -> Path:
    """Return ``projects/<slug>/`` for a CLI-provided project name.

    Creates the directory if missing. The slug lower-cases the name and
    replaces spaces with dashes so ``"My Project"`` and ``"my-project"``
    resolve to the same root across invocations.
    """
    projects_root = Path("projects")
    projects_root.mkdir(parents=True, exist_ok=True)
    pdir = projects_root / project_name.lower().replace(" ", "-")
    pdir.mkdir(parents=True, exist_ok=True)
    return pdir


def _read_requirements_arg(value: str | None) -> str | None:
    """Resolve a ``--requirements`` CLI value to text.

    Treats the value as a file path first; falls back to raw text if the
    path does not exist or is unreadable.
    """
    if not value:
        return None
    try:
        with open(value) as f:
            return f.read()
    except (FileNotFoundError, IsADirectoryError, PermissionError):
        return value


def _multi_project_repl(config: ProjectConfig) -> None:
    """Small REPL backed by ``ProjectSession`` for multi-project work.

    Replaces the legacy ``MultiProjectSession`` (which composed the older
    ``aise.core.project_manager.ProjectManager`` + ``DeepOrchestrator``
    indirection). The shape here is deliberately minimal — create a
    project root, optionally switch between several, and dispatch one
    requirement at a time through the same ``RuntimeManager`` that the
    web service uses.
    """
    from .runtime import ProjectSession, RuntimeManager

    manager = RuntimeManager(config=config)
    manager.start()

    projects: dict[str, Path] = {}
    current: str | None = None

    def _help() -> None:
        print("Commands:")
        print("  create <name>          Create projects/<slug>/ and switch to it")
        print("  list                   List known projects")
        print("  switch <name>          Make <name> the current project")
        print("  run <requirement>      Run ProjectSession against the current project")
        print("  help                   Show this message")
        print("  quit                   Exit")

    print("AISE multi-project REPL — type 'help' for commands, Ctrl-D to exit.")
    try:
        while True:
            try:
                line = input("aise> ").strip()
            except EOFError:
                print()
                break
            if not line:
                continue
            cmd, _, rest = line.partition(" ")
            cmd = cmd.lower()
            if cmd in {"quit", "exit"}:
                break
            elif cmd == "help":
                _help()
            elif cmd == "create":
                name = rest.strip()
                if not name:
                    print("Usage: create <name>")
                    continue
                pdir = _project_root_for(name)
                projects[name] = pdir
                current = name
                print(f"Created project '{name}' at {pdir}.")
            elif cmd == "list":
                if not projects:
                    print("(no projects yet — use 'create <name>')")
                else:
                    for n, p in projects.items():
                        marker = " *" if n == current else ""
                        print(f"  {n} → {p}{marker}")
            elif cmd == "switch":
                name = rest.strip()
                if name not in projects:
                    print(f"Unknown project '{name}'. Use 'list' to see available.")
                    continue
                current = name
                print(f"Switched to '{name}'.")
            elif cmd == "run":
                if current is None:
                    print("No project selected. Use 'create <name>' or 'switch <name>' first.")
                    continue
                requirement = rest.strip()
                if not requirement:
                    print("Usage: run <requirement text>")
                    continue
                session = ProjectSession(manager, project_root=str(projects[current]))
                result = session.run(requirement)
                print(result)
            else:
                print(f"Unknown command '{cmd}'. Type 'help'.")
    finally:
        manager.stop()


def start_whatsapp_session(
    project_name: str = "My Project",
    config: ProjectConfig | None = None,
    owner_name: str = "",
    owner_phone: str = "",
) -> WhatsAppGroupSession:
    """Create a WhatsApp group chat session with the agent team.

    Args:
        project_name: Name of the project.
        config: Optional project configuration with WhatsApp settings.
        owner_name: Name of the human owner to auto-join.
        owner_phone: Phone number of the human owner.

    Returns:
        A configured WhatsAppGroupSession ready to start.
    """
    config = config or ProjectConfig()
    config.project_name = project_name
    orchestrator = create_team(config)

    wa_config = WhatsAppConfig(
        phone_number_id=config.whatsapp.phone_number_id,
        access_token=config.whatsapp.access_token,
        verify_token=config.whatsapp.verify_token,
        business_account_id=config.whatsapp.business_account_id,
        webhook_port=config.whatsapp.webhook_port,
        webhook_path=config.whatsapp.webhook_path,
    )

    session = WhatsAppGroupSession(
        orchestrator=orchestrator,
        project_name=project_name,
        whatsapp_config=wa_config,
    )

    if owner_name:
        session.add_human(owner_name, owner_phone, is_owner=True)

    return session


def start_web_app(
    host: str = "127.0.0.1",
    port: int = 8000,
    reload: bool = False,
) -> None:
    """Start the AISE web system."""
    try:
        import uvicorn
    except Exception as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("uvicorn is required for web mode. Install with: pip install -e '.[web]'") from exc

    from .web import create_app

    uvicorn.run(create_app(), host=host, port=port, reload=reload)


def _add_github_args(sub_parser: argparse.ArgumentParser) -> None:
    """Add GitHub token / repo CLI arguments to a sub-parser."""
    sub_parser.add_argument(
        "--github-token",
        default=os.environ.get("GITHUB_TOKEN", ""),
        help="GitHub personal access token (env: GITHUB_TOKEN)",
    )
    sub_parser.add_argument(
        "--github-repo-owner",
        default=os.environ.get("GITHUB_REPO_OWNER", ""),
        help="GitHub repository owner (env: GITHUB_REPO_OWNER)",
    )
    sub_parser.add_argument(
        "--github-repo-name",
        default=os.environ.get("GITHUB_REPO_NAME", ""),
        help="GitHub repository name (env: GITHUB_REPO_NAME)",
    )


def _apply_github_config(args: argparse.Namespace, config: ProjectConfig) -> None:
    """Copy CLI / env GitHub values into the project config."""
    if getattr(args, "github_token", ""):
        config.github.token = args.github_token
    if getattr(args, "github_repo_owner", ""):
        config.github.repo_owner = args.github_repo_owner
    if getattr(args, "github_repo_name", ""):
        config.github.repo_name = args.github_repo_name


def _load_cli_project_config(project_name: str) -> ProjectConfig:
    candidates = [
        Path("config/global_project_config.json"),
        Path("global_project_config.json"),
    ]
    for path in candidates:
        if not path.exists():
            continue
        try:
            config = ProjectConfig.from_json_file(path)
            config.project_name = project_name
            return config
        except Exception:
            continue
    return ProjectConfig(project_name=project_name)


def main() -> None:
    """CLI entry point."""
    configure_logging(_load_cli_project_config("Untitled Project").logging)
    parser = argparse.ArgumentParser(
        description="AISE - Multi-Agent Software Development Team",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run command
    run_parser = subparsers.add_parser("run", help="Run the development workflow")
    run_parser.add_argument("--requirements", "-r", required=True, help="Requirements text or file path")
    run_parser.add_argument("--project-name", "-p", default="My Project", help="Project name")
    run_parser.add_argument("--output", "-o", help="Output file for results (JSON)")
    _add_github_args(run_parser)

    # demand command
    demand_parser = subparsers.add_parser(
        "demand",
        help="Start an interactive on-demand session",
    )
    demand_parser.add_argument("--project-name", "-p", default="My Project", help="Project name")
    demand_parser.add_argument(
        "--requirements",
        "-r",
        help="Requirement text or path to a file containing it. If omitted, the requirement is read from stdin.",
    )
    _add_github_args(demand_parser)

    # whatsapp command
    wa_parser = subparsers.add_parser(
        "whatsapp",
        help="Start a WhatsApp group chat session with the agent team",
    )
    wa_parser.add_argument("--project-name", "-p", default="My Project", help="Project name")
    wa_parser.add_argument("--owner", default="", help="Your display name in the group")
    wa_parser.add_argument("--phone", default="", help="Your WhatsApp phone number")
    wa_parser.add_argument(
        "--webhook",
        action="store_true",
        help="Start webhook server for real WhatsApp integration",
    )
    wa_parser.add_argument(
        "--webhook-port",
        type=int,
        default=8080,
        help="Port for the webhook server (default: 8080)",
    )
    wa_parser.add_argument(
        "--phone-number-id",
        default=os.environ.get("WHATSAPP_PHONE_NUMBER_ID", ""),
        help="WhatsApp Business phone number ID (env: WHATSAPP_PHONE_NUMBER_ID)",
    )
    wa_parser.add_argument(
        "--access-token",
        default=os.environ.get("WHATSAPP_ACCESS_TOKEN", ""),
        help="WhatsApp Business API access token (env: WHATSAPP_ACCESS_TOKEN)",
    )
    wa_parser.add_argument(
        "--verify-token",
        default=os.environ.get("WHATSAPP_VERIFY_TOKEN", ""),
        help="Webhook verification token (env: WHATSAPP_VERIFY_TOKEN)",
    )
    wa_parser.add_argument(
        "--requirements",
        "-r",
        help="Optional initial requirements to seed the session",
    )
    _add_github_args(wa_parser)

    # team command
    team_parser = subparsers.add_parser("team", help="Show team information")
    team_parser.add_argument("--verbose", "-v", action="store_true", help="Show agent skills")

    # multi-project command
    subparsers.add_parser(
        "multi-project",
        help="Interactive multi-project REPL backed by ProjectSession (create/list/switch/run)",
    )

    # web command
    web_parser = subparsers.add_parser(
        "web",
        help="Start web project management system",
    )
    web_parser.add_argument("--host", default="127.0.0.1", help="Host for web server")
    web_parser.add_argument("--port", type=int, default=8000, help="Port for web server")
    web_parser.add_argument("--reload", action="store_true", help="Enable auto reload")

    retry_parser = subparsers.add_parser(
        "task-retry",
        help="Retry a single workflow task in a web-managed project run",
    )
    retry_parser.add_argument("--project-id", required=True, help="Project ID")
    retry_parser.add_argument("--run-id", required=True, help="Run ID")
    retry_parser.add_argument("--phase", required=True, help="Phase key")
    retry_parser.add_argument("--task-key", required=True, help="Task key from run detail UI")
    retry_parser.add_argument("--mode", choices=["current", "downstream"], default="current", help="Retry mode")
    retry_parser.add_argument("--wait", action="store_true", help="Wait for completion")
    retry_parser.add_argument("--poll-interval", type=float, default=2.0, help="Polling interval seconds")
    retry_parser.add_argument("--show-task-state", action="store_true", help="Print task memory state after completion")

    # develop command — concurrent development sessions
    dev_parser = subparsers.add_parser(
        "develop",
        help="Start concurrent development sessions",
    )
    dev_parser.add_argument("--project-name", "-p", default="My Project", help="Project name")
    dev_parser.add_argument(
        "--max-sessions",
        "-n",
        type=int,
        default=5,
        help="Maximum concurrent developer sessions (default: 5)",
    )
    dev_parser.add_argument(
        "--mode",
        choices=["local", "github"],
        default="local",
        help="Development mode (default: local)",
    )
    dev_parser.add_argument(
        "--repo-root",
        default=".",
        help="Path to the git repository root (default: current directory)",
    )
    _add_github_args(dev_parser)

    args = parser.parse_args()

    if args.command == "run":
        requirements = args.requirements
        # Check if it's a file path
        try:
            with open(requirements) as f:
                requirements = f.read()
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            pass  # Use as raw text

        config = _load_cli_project_config(args.project_name)
        _apply_github_config(args, config)
        configure_logging(config.logging, force=True)

        from .runtime import ProjectSession, RuntimeManager

        manager = RuntimeManager(config=config)
        manager.start()

        print(f"Agents initialized: {', '.join(manager.runtimes.keys())}")
        print(f"Requirement: {requirements[:120]}{'...' if len(requirements) > 120 else ''}")
        print()

        session = ProjectSession(manager)
        result = session.run(requirements)

        if args.output:
            output = {
                "result": result,
                "task_log": session.task_log,
            }
            with open(args.output, "w") as f:
                json.dump(output, f, indent=2, default=str, ensure_ascii=False)
            print(f"Results written to {args.output}")
        else:
            print(result)
            if session.task_log:
                print(f"\n--- A2A task log: {len(session.task_log)} messages ---")
                for msg in session.task_log:
                    direction = "->" if msg["type"] == "task_request" else "<-"
                    agent = msg.get("to") if msg["type"] == "task_request" else msg.get("from")
                    status = msg.get("status", "")
                    print(f"  {direction} {agent} [{msg['type']}] {status}")

        manager.stop()

    elif args.command == "demand":
        config = _load_cli_project_config(args.project_name)
        _apply_github_config(args, config)
        configure_logging(config.logging, force=True)

        from .runtime import ProjectSession, RuntimeManager

        requirements = _read_requirements_arg(args.requirements)
        if requirements is None:
            print("Enter your requirement (end with Ctrl-D / EOF):")
            try:
                requirements = sys.stdin.read().strip()
            except KeyboardInterrupt:
                print("\nCancelled.")
                sys.exit(0)
            if not requirements:
                print("Empty requirement; nothing to do.")
                sys.exit(1)

        project_dir = _project_root_for(args.project_name)
        manager = RuntimeManager(config=config)
        manager.start()
        try:
            print(f"Project: {args.project_name} (root: {project_dir})")
            print(f"Agents: {', '.join(manager.runtimes.keys())}")
            print(f"Requirement: {requirements[:120]}{'...' if len(requirements) > 120 else ''}")
            print()

            session = ProjectSession(manager, project_root=str(project_dir))
            result = session.run(requirements)
            print(result)
        finally:
            manager.stop()

    elif args.command == "whatsapp":
        config = _load_cli_project_config(args.project_name)
        _apply_github_config(args, config)
        if args.phone_number_id:
            config.whatsapp.phone_number_id = args.phone_number_id
        if args.access_token:
            config.whatsapp.access_token = args.access_token
        if args.verify_token:
            config.whatsapp.verify_token = args.verify_token
        config.whatsapp.webhook_port = args.webhook_port
        configure_logging(config.logging, force=True)

        session = start_whatsapp_session(
            project_name=args.project_name,
            config=config,
            owner_name=args.owner or "Owner",
            owner_phone=args.phone,
        )

        # Seed with initial requirements if provided
        if args.requirements:
            reqs = args.requirements
            try:
                with open(reqs) as f:
                    reqs = f.read()
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                pass
            humans = session.group_chat.human_members
            sender = humans[0].name if humans else "Owner"
            session.send_requirement(sender, reqs)

        session.start(start_webhook=args.webhook)

    elif args.command == "team":
        config = _load_cli_project_config("AISE Team")
        configure_logging(config.logging, force=True)

        from .runtime import RuntimeManager

        manager = RuntimeManager(config=config)
        manager.start()

        print("AISE Development Team (Runtime)")
        print("=" * 40)
        for status in manager.get_agents_status():
            card = status.get("agent_card", {})
            print(f"\n{status['role_display']}: {status['name']}  [{status['status']}]")
            model = status.get("model", {})
            if model.get("model"):
                print(f"  Model: {model.get('provider', '')}/{model['model']}")
            if args.verbose:
                for skill in card.get("skills", []):
                    print(f"  - {skill['id']}: {skill.get('description', '')}")

        manager.stop()

    elif args.command == "multi-project":
        config = _load_cli_project_config("Multi Project Session")
        configure_logging(config.logging, force=True)
        _multi_project_repl(config)

    elif args.command == "web":
        start_web_app(host=args.host, port=args.port, reload=args.reload)

    elif args.command == "task-retry":
        from .web.app import WebProjectService

        service = WebProjectService()
        try:
            result = service.retry_task(
                args.project_id,
                args.run_id,
                phase_key=args.phase,
                task_key=args.task_key,
                mode=args.mode,
            )
        except RuntimeError as exc:
            print(f"Retry rejected: {exc}")
            sys.exit(2)
        except Exception as exc:
            print(f"Retry failed to start: {exc}")
            sys.exit(1)

        print(
            f"Retry accepted: op_id={result.get('op_id')} project={args.project_id} "
            f"run={args.run_id} phase={args.phase} task={args.task_key} mode={args.mode}"
        )
        if args.wait:
            poll_interval = args.poll_interval if args.poll_interval > 0 else 2.0
            while True:
                run = service.get_run(args.project_id, args.run_id)
                if not isinstance(run, dict):
                    print("Run not found while polling")
                    sys.exit(1)
                active = run.get("active_operation")
                if not isinstance(active, dict) or str(active.get("status", "")) != "running":
                    status = str(run.get("status", "unknown"))
                    print(f"Retry finished: run_status={status}")
                    if run.get("error"):
                        print(f"Error: {run.get('error')}")
                    if args.show_task_state:
                        task_state = service.get_task_state(
                            args.project_id,
                            args.run_id,
                            phase_key=args.phase,
                            task_key=args.task_key,
                        )
                        print(json.dumps(task_state or {"task_state": None}, ensure_ascii=False, indent=2))
                    if status == "failed":
                        sys.exit(1)
                    break
                time.sleep(poll_interval)

    elif args.command == "develop":
        import asyncio

        from .core.dev_session import SessionManager

        config = _load_cli_project_config(args.project_name)
        config.development_mode = args.mode
        config.session.max_concurrent_sessions = args.max_sessions
        _apply_github_config(args, config)
        configure_logging(config.logging, force=True)

        # For local mode, enforce single session
        effective_sessions = args.max_sessions
        if config.is_local_mode:
            effective_sessions = 1

        orchestrator = create_team(config)

        # Validate prerequisite: STATUS_TRACKING artifact must exist
        from .core.artifact import ArtifactType

        status_artifact = orchestrator.artifact_store.get_latest(ArtifactType.STATUS_TRACKING)
        if status_artifact is None:
            print(
                "Error: No STATUS_TRACKING artifact found.\n"
                "The architect pipeline must run first:\n"
                "  1. system_feature_analysis (SF)\n"
                "  2. system_requirement_analysis (SR)\n"
                "  3. architecture_requirement_analysis (AR)\n"
                "  4. functional_design (FN)\n"
                "  5. status_tracking\n\n"
                "Run 'aise run' or 'aise demand' first to generate these artifacts."
            )
            sys.exit(1)

        session_manager = SessionManager(
            orchestrator=orchestrator,
            config=config,
            max_concurrent_sessions=effective_sessions,
            repo_root=args.repo_root,
        )

        print(f"Starting development sessions (mode={args.mode}, max_sessions={effective_sessions})")
        asyncio.run(session_manager.start())
        print("Development sessions completed.")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
