"""Agent capability learning module.

This module provides functionality for learning agent capabilities from
historical execution records.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from aise.core.task_allocation import AgentCapability


@dataclass
class TaskExecutionRecord:
    """Record of a single task execution."""

    task_id: str
    agent_name: str
    skill_name: str
    start_time: datetime
    end_time: datetime
    success: bool
    duration_seconds: float
    quality_score: float  # 0-100
    error_message: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "task_id": self.task_id,
            "agent_name": self.agent_name,
            "skill_name": self.skill_name,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "success": self.success,
            "duration_seconds": self.duration_seconds,
            "quality_score": self.quality_score,
            "error_message": self.error_message,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskExecutionRecord":
        """Create from dictionary."""
        return cls(
            task_id=data["task_id"],
            agent_name=data["agent_name"],
            skill_name=data["skill_name"],
            start_time=datetime.fromisoformat(data["start_time"]),
            end_time=datetime.fromisoformat(data["end_time"]),
            success=data["success"],
            duration_seconds=data["duration_seconds"],
            quality_score=data["quality_score"],
            error_message=data.get("error_message", ""),
        )


class AgentCapabilityLearner:
    """Learns agent capabilities from historical execution records.

    This class records task executions and calculates capability ratings
    based on historical performance data.
    """

    def __init__(self, history_file: Path | None = None):
        """Initialize the capability learner.

        Args:
            history_file: Path to the history file. Defaults to data/execution_history.json
        """
        self.history_file = history_file or Path("data/execution_history.json")
        self.records: list[TaskExecutionRecord] = []
        self._decay_factor = 0.95  # Exponential decay for older records

    def record_execution(self, record: TaskExecutionRecord) -> None:
        """Record a task execution.

        Args:
            record: The execution record to add.
        """
        self.records.append(record)

    def get_capability_rating(self, agent: str, skill: str, min_history: int = 1) -> float:
        """Calculate capability rating based on historical records.

        Uses exponential decay to weight recent executions more heavily.
        Rating is on a 0-5 scale.

        Args:
            agent: Agent name.
            skill: Skill name.
            min_history: Minimum history records required. Default 1.

        Returns:
            Capability rating on 0-5 scale. Returns 2.5 (default) if insufficient history.
        """
        # Filter records for this agent-skill pair
        agent_skill_records = [r for r in self.records if r.agent_name == agent and r.skill_name == skill]

        if len(agent_skill_records) < min_history:
            return 2.5  # Default rating

        now = datetime.now()
        total_weighted_score = 0.0
        total_weight = 0.0

        for record in agent_skill_records:
            # Calculate time weight (exponential decay)
            hours_ago = (now - record.end_time).total_seconds() / 3600
            time_weight = self._decay_factor**hours_ago

            # Calculate execution score
            execution_score = record.quality_score / 100.0 * 5.0 if record.success else 0.0

            total_weighted_score += execution_score * time_weight
            total_weight += time_weight

        if total_weight == 0:
            return 2.5

        # Calculate weighted average, clamped to 0-5
        rating = total_weighted_score / total_weight
        return max(0.0, min(5.0, rating))

    def export_learned_capabilities(self) -> list[AgentCapability]:
        """Export all learned capabilities.

        Returns:
            List of AgentCapability objects for all agent-skill pairs with history.
        """
        capabilities = []
        seen_pairs = set()

        for record in self.records:
            pair = (record.agent_name, record.skill_name)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)

            rating = self.get_capability_rating(record.agent_name, record.skill_name)
            capabilities.append(AgentCapability(record.agent_name, record.skill_name, rating))

        return capabilities

    def load_history(self) -> None:
        """Load execution history from file."""
        if not self.history_file.exists():
            self.records = []
            return

        try:
            content = self.history_file.read_text()
            if not content.strip():
                self.records = []
                return

            data = json.loads(content)
            self.records = [TaskExecutionRecord.from_dict(r) for r in data]
        except (json.JSONDecodeError, KeyError):
            self.records = []

    def save_history(self) -> None:
        """Save execution history to file."""
        # Ensure parent directory exists
        self.history_file.parent.mkdir(parents=True, exist_ok=True)

        data = [r.to_dict() for r in self.records]
        self.history_file.write_text(json.dumps(data, indent=2))
