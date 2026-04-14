"""Data models for the agent runtime.

Includes both agent definitions (parsed from agent.md) and process
definitions (parsed from process.md). All workflow behavior comes from
these data files — the runtime code itself stays role/process-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentState(Enum):
    """Lifecycle states of an agent runtime."""

    CREATED = "created"
    ACTIVE = "active"
    WORKING = "working"
    STOPPED = "stopped"


@dataclass
class SkillInfo:
    """Metadata describing a single agent skill."""

    id: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


@dataclass
class ProviderInfo:
    """Organization that provides the agent."""

    organization: str = ""
    url: str = ""


@dataclass
class OutputLayout:
    """Declarative output-path policy for an agent.

    Each entry maps a logical output kind (e.g. "source", "tests",
    "design") to a relative directory inside the project root. The
    runtime's policy backend uses this to validate writes — paths
    that fall outside any declared directory are rejected (no silent
    rerouting).

    The ``forbidden`` field is a list of glob patterns matched against
    the filename only; matching files are always rejected even if the
    target directory is allowed.
    """

    paths: dict[str, str] = field(default_factory=dict)
    forbidden: list[str] = field(default_factory=list)

    def allowed_directories(self) -> list[str]:
        """Return the list of allowed relative directories (with trailing slash)."""
        return [p.rstrip("/") + "/" for p in self.paths.values() if p]

    def is_empty(self) -> bool:
        """True when no paths are declared (legacy agent.md without layout)."""
        return not self.paths


@dataclass
class AgentDefinition:
    """Parsed agent definition from an agent.md file.

    The ``role`` field categorizes the agent for the orchestrator:
    ``"orchestrator"`` agents are excluded from ``list_agents`` and
    are eligible to drive a ProjectSession; everything else defaults
    to ``"worker"``.

    The ``output_layout`` and ``allowed_tools`` fields are used by the
    runtime's policy backend and tool factory to enforce what an agent
    may do — none of these are interpreted by code as workflow logic.
    """

    name: str
    description: str
    version: str = "1.0.0"
    system_prompt: str = ""
    skills: list[SkillInfo] = field(default_factory=list)
    capabilities: dict[str, bool] = field(default_factory=dict)
    provider: ProviderInfo = field(default_factory=ProviderInfo)
    role: str = "worker"
    output_layout: OutputLayout = field(default_factory=OutputLayout)
    allowed_tools: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


# -- Process definitions ----------------------------------------------------


@dataclass
class ProcessCaps:
    """Safety caps that override RuntimeConfig defaults for a process."""

    max_dispatches: int | None = None
    max_continuations: int | None = None
    per_phase_timeout_seconds: int | None = None


@dataclass
class ProcessStep:
    """A single step within a process phase.

    ``agents`` lists role names declared by the process (these are
    matched against AgentDefinition.role / name during team assembly,
    not hardcoded anywhere). ``deliverables`` lists the relative
    directories or files this step is expected to produce.
    """

    id: str
    title: str = ""
    description: str = ""
    agents: list[str] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    on_failure: str = ""
    max_retries: int = 0
    verification_command: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ProcessPhase:
    """A logical phase grouping one or more steps."""

    id: str
    title: str = ""
    description: str = ""
    steps: list[ProcessStep] = field(default_factory=list)


@dataclass
class ProcessDefinition:
    """Parsed process.md definition.

    Carries metadata, phases/steps, optional caps, and an optional
    ``terminal_step`` id. Code never inspects step ids or phase ids
    by name — it only walks the structure declared here.
    """

    process_id: str
    name: str = ""
    work_type: str = ""
    keywords: str = ""
    summary: str = ""
    caps: ProcessCaps = field(default_factory=ProcessCaps)
    terminal_step: str = ""
    required_phases: list[str] = field(default_factory=list)
    phases: list[ProcessPhase] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def header_dict(self) -> dict[str, str]:
        """Return process metadata as a flat dict (for list_processes tool)."""
        return {
            "process_id": self.process_id,
            "name": self.name,
            "work_type": self.work_type,
            "keywords": self.keywords,
            "summary": self.summary,
        }

    def all_step_ids(self) -> list[str]:
        """Return every step id in declaration order."""
        return [s.id for ph in self.phases for s in ph.steps]


@dataclass
class AgentCard:
    """A2A protocol-compliant agent card.

    Follows the Google Agent-to-Agent (A2A) protocol specification
    for agent discovery and capability advertisement.
    """

    name: str
    description: str
    url: str = ""
    version: str = "1.0.0"
    provider: ProviderInfo = field(default_factory=ProviderInfo)
    capabilities: dict[str, bool] = field(
        default_factory=lambda: {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": False,
        }
    )
    skills: list[SkillInfo] = field(default_factory=list)
    default_input_modes: list[str] = field(default_factory=lambda: ["text"])
    default_output_modes: list[str] = field(default_factory=lambda: ["text"])

    def to_dict(self) -> dict[str, Any]:
        """Serialize to A2A-compliant JSON-compatible dict."""
        return {
            "name": self.name,
            "description": self.description,
            "url": self.url,
            "version": self.version,
            "provider": {
                "organization": self.provider.organization,
                "url": self.provider.url,
            },
            "capabilities": dict(self.capabilities),
            "skills": [
                {
                    "id": s.id,
                    "name": s.name,
                    "description": s.description,
                    "tags": s.tags,
                    "examples": s.examples,
                }
                for s in self.skills
            ],
            "defaultInputModes": self.default_input_modes,
            "defaultOutputModes": self.default_output_modes,
        }
