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

    # waterfall_v2: resume a halted run
    resume_parser = subparsers.add_parser(
        "resume_project",
        help="Resume a waterfall_v2 project that halted at a phase failure",
    )
    resume_parser.add_argument("project_id", help="Project ID to resume")
    resume_parser.add_argument(
        "--web-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the running aise web server (default: http://127.0.0.1:8000)",
    )

    # waterfall_v2: abort a running task
    abort_parser = subparsers.add_parser(
        "abort_task",
        help="Send an abort signal to a running task in the aise web server",
    )
    abort_parser.add_argument("task_id", help="Task ID to abort (from /api/tasks/active)")
    abort_parser.add_argument(
        "--web-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the running aise web server (default: http://127.0.0.1:8000)",
    )

    # waterfall_v2: list active tasks (no LLM impact, just observability)
    active_parser = subparsers.add_parser(
        "active_tasks",
        help="List in-flight tasks tracked by the aise web server",
    )
    active_parser.add_argument(
        "--web-url",
        default="http://127.0.0.1:8000",
        help="Base URL of the running aise web server (default: http://127.0.0.1:8000)",
    )

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

    elif args.command == "resume_project":
        _cmd_resume_project(args.project_id, args.web_url)
    elif args.command == "abort_task":
        _cmd_abort_task(args.task_id, args.web_url)
    elif args.command == "active_tasks":
        _cmd_active_tasks(args.web_url)
    else:
        parser.print_help()
        sys.exit(1)


# -- waterfall_v2 CLI helpers ------------------------------------------


def _http_post(url: str, json_body: dict | None = None) -> dict:
    """POST to local aise web server. Login is via cookie session;
    the dev-login auth path is the path of least resistance for CLI
    users on a single-user dev install."""
    import httpx

    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            # Best-effort dev login (no-op when auth is disabled or
            # already logged in).
            try:
                client.get(f"{url.rstrip('/')}/auth/dev-login")
            except Exception:
                pass
            r = client.post(url, json=json_body or {})
        return {"status_code": r.status_code, "body": r.text}
    except httpx.HTTPError as exc:
        return {"status_code": -1, "error": str(exc)}


def _http_get(url: str) -> dict:
    import httpx

    try:
        with httpx.Client(timeout=10.0, follow_redirects=True) as client:
            try:
                client.get(f"{url.rstrip('/')}/auth/dev-login")
            except Exception:
                pass
            r = client.get(url)
        return {"status_code": r.status_code, "body": r.text}
    except httpx.HTTPError as exc:
        return {"status_code": -1, "error": str(exc)}


def _cmd_resume_project(project_id: str, web_url: str) -> None:
    url = f"{web_url.rstrip('/')}/api/projects/{project_id}/resume"
    result = _http_post(url)
    if result["status_code"] == -1:
        print(f"resume_project failed: {result['error']}")
        print(f"  is the aise web server running at {web_url}?")
        sys.exit(1)
    if result["status_code"] >= 400:
        print(f"resume_project rejected ({result['status_code']}): {result['body']}")
        sys.exit(2)
    print(f"resume_project accepted: {result['body']}")


def _cmd_abort_task(task_id: str, web_url: str) -> None:
    url = f"{web_url.rstrip('/')}/api/tasks/{task_id}/abort"
    result = _http_post(url)
    if result["status_code"] == -1:
        print(f"abort_task failed: {result['error']}")
        sys.exit(1)
    if result["status_code"] == 404:
        print(f"task {task_id} not registered (already completed or never started)")
        sys.exit(2)
    if result["status_code"] >= 400:
        print(f"abort_task rejected ({result['status_code']}): {result['body']}")
        sys.exit(2)
    print(f"abort_task signal sent: {result['body']}")


def _cmd_active_tasks(web_url: str) -> None:
    url = f"{web_url.rstrip('/')}/api/tasks/active"
    result = _http_get(url)
    if result["status_code"] == -1:
        print(f"active_tasks failed: {result['error']}")
        sys.exit(1)
    if result["status_code"] >= 400:
        print(f"active_tasks rejected ({result['status_code']}): {result['body']}")
        sys.exit(2)
    try:
        import json as _json

        data = _json.loads(result["body"])
        tasks = data.get("active_tasks", [])
    except Exception:
        print(result["body"])
        return
    if not tasks:
        print("(no in-flight tasks)")
        return
    print(f"{'TASK':12s}  {'AGENT':18s}  {'STEP':35s}  {'ELAPSED':>9s}  {'LLM':>5s}  {'LOOP':>5s}")
    for t in tasks:
        print(
            f"{str(t.get('task_id', ''))[:12]:12s}  "
            f"{str(t.get('agent', ''))[:18]:18s}  "
            f"{str(t.get('step', ''))[:35]:35s}  "
            f"{t.get('elapsed_seconds', 0):>9.1f}  "
            f"{t.get('llm_call_count', 0):>5d}  "
            f"{t.get('loop_detector_hits', 0):>5d}"
        )


if __name__ == "__main__":
    main()
