"""Team health skill - monitors overall team wellbeing and productivity."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ...core.artifact import Artifact, ArtifactType
from ...core.skill import Skill, SkillContext

# Seconds without a message after which an in-progress agent is considered stuck
_STUCK_THRESHOLD_SECONDS = 300  # 5 minutes


class TeamHealthSkill(Skill):
    """Assess team health, flag risk areas, and recommend corrective actions.

    In addition to workload indicators (blocked/overdue tasks), the skill
    performs lightweight HA checks:

    * **Crash detection** — an agent listed in ``agent_registry`` that has
      never sent or received a message is flagged as potentially crashed or
      never started.
    * **Stuck-session detection** — an agent whose last message activity
      pre-dates the ``stuck_threshold_seconds`` window and that still has
      in-progress tasks is flagged as deadlocked.

    Recovery actions are emitted for every detected HA event so that the
    Project Manager (or an orchestrator) can act on them.
    """

    @property
    def name(self) -> str:
        return "team_health"

    @property
    def description(self) -> str:
        return "Assess team health indicators and recommend corrective actions"

    def execute(self, input_data: dict[str, Any], context: SkillContext) -> Artifact:
        agent_statuses: dict[str, Any] = input_data.get("agent_statuses", {})
        blocked_tasks: list[str] = input_data.get("blocked_tasks", [])
        overdue_tasks: list[str] = input_data.get("overdue_tasks", [])

        # HA inputs
        message_history: list[dict[str, Any]] = input_data.get("message_history", [])
        task_statuses: list[dict[str, Any]] = input_data.get("task_statuses", [])
        agent_registry: dict[str, Any] = input_data.get("agent_registry", {})
        stuck_threshold: int = input_data.get("stuck_threshold_seconds", _STUCK_THRESHOLD_SECONDS)

        store = context.artifact_store

        # Count artifacts by type to gauge delivery progress
        artifact_counts: dict[str, int] = {}
        for art in store.all():
            key = art.artifact_type.value
            artifact_counts[key] = artifact_counts.get(key, 0) + 1

        # ---------------------------------------------------------------
        # HA detection
        # ---------------------------------------------------------------
        crashed_agents: list[dict[str, Any]] = []
        stuck_agents: list[dict[str, Any]] = []
        recovery_actions: list[dict[str, Any]] = []

        if agent_registry:
            # Build per-agent message activity index from history
            last_activity: dict[str, datetime | None] = {name: None for name in agent_registry}
            for msg in message_history:
                for field in ("sender", "receiver"):
                    agent_name = msg.get(field)
                    if agent_name not in last_activity:
                        continue
                    ts_raw = msg.get("timestamp")
                    if ts_raw is None:
                        continue
                    if isinstance(ts_raw, datetime):
                        ts = ts_raw
                    else:
                        try:
                            ts = datetime.fromisoformat(str(ts_raw))
                        except ValueError:
                            continue
                    if last_activity[agent_name] is None or ts > last_activity[agent_name]:
                        last_activity[agent_name] = ts

            # Collect in-progress tasks per agent
            in_progress: dict[str, list[str]] = {}
            for task in task_statuses:
                if task.get("status") == "in_progress":
                    assignee = task.get("assignee", "")
                    if assignee:
                        in_progress.setdefault(assignee, []).append(task.get("task_id", "unknown"))

            now = datetime.now(timezone.utc)

            for agent_name in agent_registry:
                activity = last_activity.get(agent_name)

                # Crash detection: agent never appeared in message history
                if activity is None:
                    crashed_agents.append(
                        {
                            "agent": agent_name,
                            "reason": "no_message_activity",
                            "detail": "Agent has never sent or received a message",
                        }
                    )
                    recovery_actions.append(
                        {
                            "agent": agent_name,
                            "action": "restart",
                            "reason": "Agent appears to have never started or crashed at boot",
                        }
                    )
                    continue

                # Stuck detection: agent has in-progress tasks and has been silent too long
                agent_tasks = in_progress.get(agent_name, [])
                if agent_tasks:
                    # Make both datetimes timezone-aware for comparison
                    if activity.tzinfo is None:
                        activity = activity.replace(tzinfo=timezone.utc)
                    idle_seconds = (now - activity).total_seconds()
                    if idle_seconds > stuck_threshold:
                        stuck_agents.append(
                            {
                                "agent": agent_name,
                                "idle_seconds": int(idle_seconds),
                                "in_progress_tasks": agent_tasks,
                                "detail": (
                                    f"Agent silent for {int(idle_seconds)}s with {len(agent_tasks)} in-progress task(s)"
                                ),
                            }
                        )
                        recovery_actions.append(
                            {
                                "agent": agent_name,
                                "action": "interrupt_and_reassign",
                                "reason": (f"Session deadlocked: no activity for {int(idle_seconds)}s"),
                                "tasks": agent_tasks,
                            }
                        )

        # ---------------------------------------------------------------
        # Health score and status
        # ---------------------------------------------------------------
        risk_factors: list[str] = []
        if len(blocked_tasks) > 3:
            risk_factors.append(f"{len(blocked_tasks)} blocked tasks")
        if len(overdue_tasks) > 2:
            risk_factors.append(f"{len(overdue_tasks)} overdue tasks")
        if not artifact_counts:
            risk_factors.append("No artifacts produced yet — delivery not started")
        if crashed_agents:
            risk_factors.append(f"{len(crashed_agents)} agent(s) crashed or unreachable")
        if stuck_agents:
            risk_factors.append(f"{len(stuck_agents)} agent session(s) stuck/deadlocked")

        ha_penalty = len(crashed_agents) * 20 + len(stuck_agents) * 15
        health_score = max(
            0,
            100 - len(blocked_tasks) * 10 - len(overdue_tasks) * 5 - ha_penalty,
        )
        health_status = "healthy" if health_score >= 70 else ("at_risk" if health_score >= 40 else "critical")

        recommendations: list[str] = []
        if blocked_tasks:
            recommendations.append(f"Resolve {len(blocked_tasks)} blocked task(s) immediately")
        if overdue_tasks:
            recommendations.append(f"Re-schedule or escalate {len(overdue_tasks)} overdue task(s)")
        if crashed_agents:
            recommendations.append(
                f"Restart {len(crashed_agents)} crashed agent(s): " + ", ".join(a["agent"] for a in crashed_agents)
            )
        if stuck_agents:
            recommendations.append(f"Interrupt and reassign tasks from {len(stuck_agents)} stuck agent session(s)")
        if health_score < 70:
            recommendations.append("Schedule team sync to align on priorities")

        return Artifact(
            artifact_type=ArtifactType.PROGRESS_REPORT,
            content={
                "report_type": "team_health",
                "health_score": health_score,
                "health_status": health_status,
                "agent_statuses": agent_statuses,
                "blocked_tasks": blocked_tasks,
                "overdue_tasks": overdue_tasks,
                "artifact_counts": artifact_counts,
                "risk_factors": risk_factors,
                "recommendations": recommendations,
                # HA fields
                "crashed_agents": crashed_agents,
                "stuck_agents": stuck_agents,
                "recovery_actions": recovery_actions,
                "project_name": context.project_name,
            },
            producer="project_manager",
            metadata={
                "type": "team_health",
                "project_name": context.project_name,
            },
        )
