"""CLI entry point for the AISE multi-agent development team."""

from __future__ import annotations

import argparse
import json
import os
import sys

from .agents import (
    ArchitectAgent,
    DeveloperAgent,
    ProductManagerAgent,
    QAEngineerAgent,
    TeamLeadAgent,
)
from .config import ProjectConfig
from .core.orchestrator import Orchestrator
from .core.session import OnDemandSession
from .whatsapp.client import WhatsAppConfig
from .whatsapp.session import WhatsAppGroupSession


def create_team(config: ProjectConfig | None = None) -> Orchestrator:
    """Create a fully configured development team.

    Returns:
        An Orchestrator with all agents registered and ready.
    """
    config = config or ProjectConfig()
    orchestrator = Orchestrator()

    bus = orchestrator.message_bus
    store = orchestrator.artifact_store

    agents = [
        ProductManagerAgent(bus, store, config.get_model_config("product_manager")),
        ArchitectAgent(bus, store, config.get_model_config("architect")),
        DeveloperAgent(bus, store, config.get_model_config("developer")),
        QAEngineerAgent(bus, store, config.get_model_config("qa_engineer")),
        TeamLeadAgent(bus, store, config.get_model_config("team_lead")),
    ]

    for agent in agents:
        agent_config = config.agents.get(agent.name)
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
    orchestrator = create_team()
    return orchestrator.run_default_workflow(
        project_input={"raw_requirements": requirements},
        project_name=project_name,
    )


def start_demand_session(project_name: str = "My Project") -> OnDemandSession:
    """Create and return an on-demand interactive session.

    Args:
        project_name: Name of the project.

    Returns:
        A configured OnDemandSession ready to start.
    """
    orchestrator = create_team()
    return OnDemandSession(orchestrator, project_name)


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


def main() -> None:
    """CLI entry point."""
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

    args = parser.parse_args()

    if args.command == "run":
        requirements = args.requirements
        # Check if it's a file path
        try:
            with open(requirements) as f:
                requirements = f.read()
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            pass  # Use as raw text

        config = ProjectConfig(project_name=args.project_name)
        _apply_github_config(args, config)
        orchestrator = create_team(config)
        results = orchestrator.run_default_workflow(
            project_input={"raw_requirements": requirements},
            project_name=args.project_name,
        )

        if args.output:
            with open(args.output, "w") as f:
                json.dump(results, f, indent=2, default=str)
            print(f"Results written to {args.output}")
        else:
            for result in results:
                phase = result.get("phase", "unknown")
                status = result.get("status", "unknown")
                print(f"Phase: {phase} - Status: {status}")
                tasks = result.get("tasks", {})
                for task_key, task_result in tasks.items():
                    print(f"  {task_key}: {task_result.get('status', 'unknown')}")

    elif args.command == "demand":
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
        config = ProjectConfig(project_name=args.project_name)
        _apply_github_config(args, config)
        if args.phone_number_id:
            config.whatsapp.phone_number_id = args.phone_number_id
        if args.access_token:
            config.whatsapp.access_token = args.access_token
        if args.verify_token:
            config.whatsapp.verify_token = args.verify_token
        config.whatsapp.webhook_port = args.webhook_port

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
        orchestrator = create_team()
        print("AISE Development Team")
        print("=" * 40)
        for name, agent in orchestrator.agents.items():
            print(f"\n{agent.role.value.replace('_', ' ').title()}: {name}")
            if args.verbose:
                for skill_name, skill in agent.skills.items():
                    print(f"  - {skill_name}: {skill.description}")

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
