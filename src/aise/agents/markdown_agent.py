"""Markdown-driven agent loader and generic agent implementation."""

from __future__ import annotations

import inspect
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import ModelConfig
from ..core.agent import Agent, AgentRole
from ..core.artifact import ArtifactStore
from ..core.message import Message, MessageBus, MessageType
from ..core.skill import Skill
from ..skills import *  # noqa: F403
from ..utils.logging import get_logger
from .prompts import resolve_agent_prompt_md_path

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentMarkdownSpec:
    """Normalized agent spec parsed from ``src/aise/agents/*_agent.md``."""

    agent_name: str
    role: AgentRole
    skills: tuple[str, ...]
    source_path: Path


def _parse_role(raw_role: str) -> AgentRole:
    normalized = raw_role.strip().upper()
    for role in AgentRole:
        if role.name == normalized or role.value.upper() == normalized:
            return role
    raise ValueError(f"Unknown agent role in markdown: {raw_role!r}")


def _extract_markdown_section(text: str, heading: str) -> str:
    lines = text.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.strip().lower() == f"## {heading}".lower():
            start = idx + 1
            break
    if start is None:
        return ""

    end = len(lines)
    for idx in range(start, len(lines)):
        line = lines[idx].strip()
        if line.startswith("## "):
            end = idx
            break
    return "\n".join(lines[start:end]).strip()


def _extract_skills_from_section(section: str) -> list[str]:
    skills: list[str] = []
    for line in section.splitlines():
        m = re.search(r"`([^`]+)`", line)
        if not m:
            continue
        value = m.group(1).strip()
        if not value:
            continue
        lowered = value.lower()
        if lowered == "n/a" or "prompt-driven" in lowered:
            continue
        skills.append(value)
    return skills


def parse_agent_markdown_spec(agent_name: str) -> AgentMarkdownSpec:
    path = resolve_agent_prompt_md_path(agent_name)
    if path is None:
        raise FileNotFoundError(f"Agent markdown not found for {agent_name!r}")

    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"Agent markdown is empty: {path}")

    role_match = re.search(r"^-\s*Role:\s*`([^`]+)`", text, re.MULTILINE)
    if role_match is None:
        raise ValueError(f"Missing role metadata in markdown: {path}")
    role = _parse_role(role_match.group(1))

    skills = _extract_skills_from_section(_extract_markdown_section(text, "Current Skills (from Python class)"))
    if not skills:
        skills = _extract_skills_from_section(_extract_markdown_section(text, "Current Skills"))

    deduped: list[str] = []
    seen: set[str] = set()
    for skill in skills:
        if skill in seen:
            continue
        seen.add(skill)
        deduped.append(skill)

    return AgentMarkdownSpec(
        agent_name=agent_name,
        role=role,
        skills=tuple(deduped),
        source_path=path,
    )


@lru_cache(maxsize=1)
def _skill_class_by_name() -> dict[str, type[Skill]]:
    registry: dict[str, type[Skill]] = {}
    namespace = globals()
    for obj in namespace.values():
        if not inspect.isclass(obj):
            continue
        if not issubclass(obj, Skill) or obj is Skill:
            continue
        try:
            instance = obj()
        except Exception:
            # Some skills may need optional constructor args (for example agent_role);
            # instantiate with a harmless default to discover canonical skill name.
            try:
                instance = obj(agent_role=None)
            except Exception:
                continue
        registry[instance.name] = obj
    return registry


def _create_skill_instance(skill_name: str, role: AgentRole) -> Skill:
    skill_class = _skill_class_by_name().get(skill_name)
    if skill_class is None:
        raise ValueError(f"Unknown skill '{skill_name}' referenced in markdown")

    init_params = inspect.signature(skill_class).parameters
    if "agent_role" in init_params:
        return skill_class(agent_role=role)
    return skill_class()


class MarkdownConfiguredAgent(Agent):
    """Generic Agent wired entirely from markdown metadata."""

    def __init__(
        self,
        *,
        agent_name: str,
        role: AgentRole,
        message_bus: MessageBus,
        artifact_store: ArtifactStore,
        model_config: ModelConfig | None = None,
        skills: tuple[str, ...],
    ) -> None:
        super().__init__(
            name=agent_name,
            role=role,
            message_bus=message_bus,
            artifact_store=artifact_store,
            model_config=model_config,
        )
        for skill_name in skills:
            self.register_skill(_create_skill_instance(skill_name, role))

    def handle_message(self, message: Message) -> Message | None:
        # Keep legacy Project Manager HA notification behavior.
        if self.role == AgentRole.PROJECT_MANAGER and message.msg_type == MessageType.NOTIFICATION:
            event = message.content.get("event", "")
            if event in ("agent_crashed", "agent_stuck"):
                return self._handle_ha_event(message)
        return super().handle_message(message)

    def _handle_ha_event(self, message: Message) -> Message:
        event = message.content.get("event", "")
        agent_name = message.content.get("agent", "unknown")
        tasks = message.content.get("tasks", [])

        if event == "agent_crashed":
            action = "restart"
            directive = f"Agent '{agent_name}' has crashed. Initiating restart — tasks will be re-queued."
        else:
            action = "interrupt_and_reassign"
            directive = (
                f"Agent '{agent_name}' session is deadlocked "
                f"with {len(tasks)} in-progress task(s). "
                "Interrupting session and reassigning tasks."
            )

        self.send_message(
            receiver="broadcast",
            msg_type=MessageType.NOTIFICATION,
            content={
                "event": "ha_recovery",
                "source_event": event,
                "agent": agent_name,
                "action": action,
                "directive": directive,
                "tasks": tasks,
            },
        )

        return message.reply(
            content={
                "status": "acknowledged",
                "action": action,
                "agent": agent_name,
                "directive": directive,
            },
            msg_type=MessageType.RESPONSE,
        )

    # Compatibility helper methods previously defined on concrete agent classes.
    def run_full_architecture_workflow(
        self,
        *,
        project_name: str = "",
        output_dir: str | None = None,
        requirements: dict[str, Any] | None = None,
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        if "deep_architecture_workflow" not in self.skill_names:
            raise ValueError(f"Agent '{self.name}' does not support deep_architecture_workflow")

        step_artifacts: dict[str, str] = {}
        common_parameters = dict(parameters or {})
        resolved_output_dir = output_dir
        if not resolved_output_dir:
            project_root = common_parameters.get("project_root")
            if isinstance(project_root, str) and project_root.strip():
                resolved_output_dir = str(Path(project_root) / "docs")
            else:
                resolved_output_dir = "docs"

        artifact = self.execute_skill(
            "deep_architecture_workflow",
            {
                "output_dir": resolved_output_dir,
                "source_dir": str(Path(resolved_output_dir).parent / "src"),
                "requirements": requirements or {},
            },
            project_name=project_name,
            parameters=common_parameters,
        )
        step_artifacts["deep_architecture_workflow"] = artifact.id
        return step_artifacts

    def run_full_requirements_workflow(
        self,
        raw_requirements: str | list[str],
        *,
        project_name: str = "",
        output_dir: str = ".",
        user_memory: list[str] | None = None,
        pr_title: str | None = None,
        pr_head: str | None = None,
        pr_body: str = "",
        pr_base: str = "main",
        pr_number: int | None = None,
        pr_feedback: str = "Requirements documents reviewed and approved.",
        merge_pr: bool = False,
        merge_method: str = "merge",
        parameters: dict[str, Any] | None = None,
    ) -> dict[str, str]:
        if "deep_product_workflow" not in self.skill_names:
            raise ValueError(f"Agent '{self.name}' does not support deep_product_workflow")

        step_artifacts: dict[str, str] = {}
        common_parameters = parameters or {}

        def run_step(step_name: str, skill_name: str, input_data: dict[str, Any]):
            artifact = self.execute_skill(
                skill_name,
                input_data,
                project_name=project_name,
                parameters=common_parameters,
            )
            step_artifacts[step_name] = artifact.id
            return artifact

        deep_artifact = run_step(
            "deep_product_workflow",
            "deep_product_workflow",
            {
                "raw_requirements": raw_requirements,
                "user_memory": user_memory or [],
                "output_dir": output_dir,
            },
        )

        if pr_head:
            generated_files = deep_artifact.content.get("generated_files", [])
            auto_body = pr_body.strip()
            if not auto_body:
                auto_body = "Submit generated requirements documents.\n\nFiles:\n"
                for path in generated_files:
                    auto_body += f"- {path}\n"
            run_step(
                "pr_submission",
                "pr_submission",
                {
                    "title": pr_title or "docs: add/update requirements documentation",
                    "body": auto_body,
                    "head": pr_head,
                    "base": pr_base,
                },
            )

        if pr_number is not None:
            run_step(
                "pr_review",
                "pr_review",
                {
                    "pr_number": pr_number,
                    "feedback": pr_feedback,
                    "event": "APPROVE",
                },
            )
            if merge_pr:
                run_step(
                    "pr_merge",
                    "pr_merge",
                    {
                        "pr_number": pr_number,
                        "merge_method": merge_method,
                        "commit_title": "Merge requirements documentation PR",
                    },
                )

        return step_artifacts

    def check_agent_health(
        self,
        agent_registry: dict[str, Any],
        message_history: list[dict[str, Any]],
        task_statuses: list[dict[str, Any]] | None = None,
        stuck_threshold_seconds: int = 300,
        project_name: str = "",
    ) -> dict[str, Any]:
        if "team_health" not in self.skill_names:
            raise ValueError(f"Agent '{self.name}' does not support team_health")

        artifact = self.execute_skill(
            "team_health",
            {
                "agent_registry": agent_registry,
                "message_history": message_history,
                "task_statuses": task_statuses or [],
                "stuck_threshold_seconds": stuck_threshold_seconds,
            },
            project_name=project_name,
        )
        return artifact.content

    def form_team(
        self,
        roles: dict[str, dict[str, Any]],
        development_mode: str = "local",
        project_name: str = "",
    ) -> dict[str, Any]:
        if "team_formation" not in self.skill_names:
            raise ValueError(f"Agent '{self.name}' does not support team_formation")

        artifact = self.execute_skill(
            "team_formation",
            {
                "roles": roles,
                "development_mode": development_mode,
                "project_name": project_name,
            },
            project_name,
        )
        report = artifact.content

        self.send_message(
            receiver="broadcast",
            msg_type=MessageType.NOTIFICATION,
            content={
                "text": (
                    f"RD Director formed the project team: "
                    f"{report['total_roles']} role(s), "
                    f"{report['total_agents']} agent(s), "
                    f"mode={development_mode}"
                ),
                "team_roster": report.get("team_roster", []),
                "development_mode": development_mode,
            },
        )

        return report

    def distribute_requirements(
        self,
        product_requirements: str | list[str],
        architecture_requirements: str | list[str] = "",
        project_name: str = "",
        recipients: list[str] | None = None,
    ) -> dict[str, Any]:
        if "requirement_distribution" not in self.skill_names:
            raise ValueError(f"Agent '{self.name}' does not support requirement_distribution")

        input_data: dict[str, Any] = {
            "product_requirements": product_requirements,
            "architecture_requirements": architecture_requirements,
            "project_name": project_name,
        }
        if recipients is not None:
            input_data["recipients"] = recipients

        artifact = self.execute_skill("requirement_distribution", input_data, project_name)
        record = artifact.content["distribution"]

        self.send_message(
            receiver="broadcast",
            msg_type=MessageType.NOTIFICATION,
            content={
                "text": (
                    f"RD Director distributed requirements for '{project_name}': "
                    f"{record['product_requirement_count']} product requirement(s), "
                    f"{record['architecture_requirement_count']} architecture requirement(s)"
                ),
                "distribution": record,
            },
        )

        return record


def create_agent_from_markdown(
    *,
    agent_name: str,
    message_bus: MessageBus,
    artifact_store: ArtifactStore,
    model_config: ModelConfig | None = None,
    expected_role: AgentRole | None = None,
) -> MarkdownConfiguredAgent:
    """Create a runtime Agent from ``<agent_name>_agent.md`` metadata."""

    spec = parse_agent_markdown_spec(agent_name)
    if expected_role is not None and spec.role != expected_role:
        raise ValueError(
            f"Role mismatch for {agent_name!r}: markdown={spec.role.value} expected={expected_role.value}"
        )

    if not spec.skills:
        logger.warning("Agent markdown has no registered skills: agent=%s path=%s", agent_name, spec.source_path)

    return MarkdownConfiguredAgent(
        agent_name=spec.agent_name,
        role=spec.role,
        message_bus=message_bus,
        artifact_store=artifact_store,
        model_config=model_config,
        skills=spec.skills,
    )
