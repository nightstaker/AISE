"""CLI entry point for the AISE multi-agent development team."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
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
from .core.multi_project_session import MultiProjectSession
from .core.orchestrator import Orchestrator
from .core.session import OnDemandSession
from .runtime import AgentRuntime, validate_task_plan_payload
from .runtime.models import Principal
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


def run_project(requirements: str, project_name: str = "My Project") -> list[dict]:
    """Run the full SDLC workflow for given requirements.

    Args:
        requirements: Raw requirements text.
        project_name: Name of the project.

    Returns:
        List of phase results.
    """
    project_root = _prepare_run_project_root(project_name)
    orchestrator = create_team(project_root=str(project_root))
    return orchestrator.run_default_workflow(
        project_input={"raw_requirements": requirements},
        project_name=project_name,
    )


def _slugify_name(text: str) -> str:
    chars: list[str] = []
    prev_sep = False
    for ch in text.lower().strip():
        if ch.isalnum():
            chars.append(ch)
            prev_sep = False
            continue
        if not prev_sep:
            chars.append("-")
        prev_sep = True
    value = "".join(chars).strip("-")
    return value or "project"


def _prepare_run_project_root(project_name: str) -> Path:
    projects_root = Path("projects")
    projects_root.mkdir(parents=True, exist_ok=True)
    ts = int(datetime.now().timestamp())
    run_root = projects_root / f"project_{_next_project_index(projects_root)}-{_slugify_name(project_name)}-{ts}"
    run_root.mkdir(parents=True, exist_ok=True)
    for subdir in ("docs", "src", "tests", "trace"):
        (run_root / subdir).mkdir(parents=True, exist_ok=True)
    return run_root


def _next_project_index(projects_root: Path) -> int:
    max_index = -1
    pattern = re.compile(r"^project_(\d+)-")
    for path in projects_root.iterdir():
        if not path.is_dir():
            continue
        match = pattern.match(path.name)
        if not match:
            continue
        max_index = max(max_index, int(match.group(1)))
    return max_index + 1


def start_demand_session(project_name: str = "My Project") -> OnDemandSession:
    """Create and return an on-demand interactive session.

    Args:
        project_name: Name of the project.

    Returns:
        A configured OnDemandSession ready to start.
    """
    orchestrator = create_team()
    return OnDemandSession(orchestrator, project_name)


def start_multi_project_session() -> MultiProjectSession:
    """Create and return a multi-project interactive session.

    Returns:
        A configured MultiProjectSession ready to start.
    """
    return MultiProjectSession()


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
        help="Optional initial requirements to seed the session",
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
    multi_parser = subparsers.add_parser(
        "multi-project",
        help="Start an interactive multi-project session",
    )
    multi_parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        default=True,
        help="Start interactive session (default)",
    )

    # web command
    web_parser = subparsers.add_parser(
        "web",
        help="Start web project management system",
    )
    web_parser.add_argument("--host", default="127.0.0.1", help="Host for web server")
    web_parser.add_argument("--port", type=int, default=8000, help="Port for web server")
    web_parser.add_argument("--reload", action="store_true", help="Enable auto reload")

    runtime_run_parser = subparsers.add_parser(
        "runtime-run",
        help="Run a task using the new Agent Runtime (sync by default)",
    )
    runtime_run_parser.add_argument("--prompt", "-p", required=True, help="Task prompt text or file path")
    runtime_run_parser.add_argument("--task-name", help="Optional task display name")
    runtime_run_parser.add_argument("--output", "-o", help="Output file for runtime result JSON")
    runtime_run_parser.add_argument(
        "--max-parallelism",
        type=int,
        default=4,
        help="Planner/scheduler max parallelism",
    )
    runtime_run_parser.add_argument(
        "--plan-json",
        help="Optional task plan JSON file used as constraints.task_plan override",
    )

    runtime_validate_parser = subparsers.add_parser(
        "runtime-validate-plan",
        help="Validate a runtime task plan JSON file against the TaskPlan schema",
    )
    runtime_validate_parser.add_argument("--file", "-f", required=True, help="Path to plan JSON file")

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
        project_root = _prepare_run_project_root(args.project_name)
        orchestrator = create_team(config, project_root=str(project_root))
        results = orchestrator.run_default_workflow(
            project_input={"raw_requirements": requirements},
            project_name=args.project_name,
        )

        if args.output:
            with open(args.output, "w") as f:
                json.dump(results, f, indent=2, default=str)
            print(f"Results written to {args.output}")
        else:
            print(f"Project root: {project_root}")
            for result in results:
                phase = result.get("phase", "unknown")
                status = result.get("status", "unknown")
                print(f"Phase: {phase} - Status: {status}")
                tasks = result.get("tasks", {})
                for task_key, task_result in tasks.items():
                    print(f"  {task_key}: {task_result.get('status', 'unknown')}")

    elif args.command == "demand":
        config = _load_cli_project_config(args.project_name)
        _apply_github_config(args, config)
        configure_logging(config.logging, force=True)
        session = start_demand_session(args.project_name)

        # Seed with initial requirements if provided
        if args.requirements:
            reqs = args.requirements
            try:
                with open(reqs) as f:
                    reqs = f.read()
            except (FileNotFoundError, IsADirectoryError, PermissionError):
                pass
            result = session.handle_input(f"add {reqs}")
            print(result.get("output", ""))

        session.start()

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
        orchestrator = create_team(config)
        print("AISE Development Team")
        print("=" * 40)
        for name, agent in orchestrator.agents.items():
            print(f"\n{agent.role.value.replace('_', ' ').title()}: {name}")
            if args.verbose:
                for skill_name, skill in agent.skills.items():
                    print(f"  - {skill_name}: {skill.description}")

    elif args.command == "multi-project":
        config = _load_cli_project_config("Multi Project Session")
        configure_logging(config.logging, force=True)
        session = start_multi_project_session()
        session.start()

    elif args.command == "web":
        start_web_app(host=args.host, port=args.port, reload=args.reload)

    elif args.command == "runtime-run":
        prompt = args.prompt
        try:
            with open(prompt) as f:
                prompt = f.read()
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            pass

        constraints: dict[str, object] = {"max_parallelism": max(1, int(args.max_parallelism))}
        if args.plan_json:
            try:
                with open(args.plan_json) as f:
                    plan_payload = json.load(f)
            except Exception as exc:
                print(f"Failed to read plan JSON: {exc}")
                sys.exit(1)
            if not isinstance(plan_payload, dict):
                print("Invalid plan JSON: root must be an object")
                sys.exit(1)
            try:
                validate_task_plan_payload(plan_payload)
            except Exception as exc:
                print(f"Plan validation failed: {exc}")
                sys.exit(1)
            constraints["task_plan"] = plan_payload

        runtime = AgentRuntime()
        principal = Principal(user_id="cli-user", tenant_id="cli-default", roles=["Admin"])
        task_id = runtime.submit_task(
            prompt=prompt,
            principal=principal,
            task_name=args.task_name,
            constraints=constraints,
            run_sync=True,
        )
        payload = {
            "status": runtime.get_task_status(task_id, principal=principal),
            "result": runtime.get_task_result(task_id, principal=principal),
            "report": runtime.get_task_report(task_id, principal=principal),
        }
        if args.output:
            with open(args.output, "w") as f:
                json.dump(payload, f, indent=2, ensure_ascii=False, default=str)
            print(f"Runtime results written to {args.output}")
        else:
            print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    elif args.command == "runtime-validate-plan":
        try:
            with open(args.file) as f:
                payload = json.load(f)
        except Exception as exc:
            print(f"Failed to read JSON: {exc}")
            sys.exit(1)
        if not isinstance(payload, dict):
            print("Invalid JSON: root must be an object")
            sys.exit(1)
        try:
            validate_task_plan_payload(payload)
        except Exception as exc:
            print(f"INVALID: {exc}")
            sys.exit(2)
        print("VALID")

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
