"""CLI entry point for the AISE multi-agent development team."""

from __future__ import annotations

import argparse
import json
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

        results = run_project(requirements, args.project_name)

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
