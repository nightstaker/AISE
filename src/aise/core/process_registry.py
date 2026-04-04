"""AI-First Process Registry — structured catalog of all available processes.

The ProcessRegistry provides a machine-readable, LLM-consumable description
of every skill/process in the AISE system. Instead of hardcoded phase-agent
mappings, the AI planner reads the registry to understand:

- What each process does (capabilities, description)
- What it needs (input keys, artifact dependencies)
- What it produces (output artifact types)
- Who can run it (agent roles)
- When it's typically used (phase affinity — advisory, not mandatory)

This enables dynamic workflow generation: the AI selects and orders
processes based on the actual requirements, not a fixed pipeline.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from ..utils.logging import get_logger
from .artifact import ArtifactType

logger = get_logger(__name__)


class ProcessCapability(Enum):
    """What kind of work a process does."""

    ANALYSIS = "analysis"
    DESIGN = "design"
    GENERATION = "generation"
    TESTING = "testing"
    REVIEW = "review"
    MANAGEMENT = "management"
    DOCUMENTATION = "documentation"
    DEEP_WORKFLOW = "deep_workflow"
    INTEGRATION = "integration"


class ProcessConstraint(Enum):
    """Constraints that limit when a process can run."""

    REQUIRES_SOURCE_CODE = "requires_source_code"
    REQUIRES_ARCHITECTURE = "requires_architecture"
    REQUIRES_REQUIREMENTS = "requires_requirements"
    REQUIRES_TESTS = "requires_tests"
    REQUIRES_GITHUB = "requires_github"
    ON_DEMAND_ONLY = "on_demand_only"


@dataclass
class ProcessDescriptor:
    """A structured description of a single process (skill).

    This is the unit of knowledge that the AI planner uses to understand
    what the system can do. It replaces hardcoded PHASE_SKILL_PLAYBOOK
    and PHASE_AGENT_MAP with a data-driven approach.
    """

    id: str
    name: str
    description: str
    agent_roles: list[str]
    phase_affinity: list[str]  # Advisory: typical phase, not mandatory
    input_keys: list[str]
    output_artifact_types: list[ArtifactType]
    capabilities: list[ProcessCapability]
    depends_on_artifacts: list[ArtifactType] = field(default_factory=list)
    constraints: list[ProcessConstraint] = field(default_factory=list)
    is_deep_workflow: bool = False
    supersedes: list[str] = field(default_factory=list)
    estimated_complexity: str = "medium"  # low, medium, high

    def can_produce(self, artifact_type: ArtifactType) -> bool:
        """Check if this process can produce the given artifact type."""
        return artifact_type in self.output_artifact_types

    def to_llm_dict(self) -> dict[str, Any]:
        """Serialize to a dict optimized for LLM consumption.

        Strips internal details, keeps only what the AI planner needs
        to make decisions.
        """
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "agent_roles": self.agent_roles,
            "phase_affinity": self.phase_affinity,
            "input_keys": self.input_keys,
            "output_artifacts": [a.value for a in self.output_artifact_types],
            "capabilities": [c.value for c in self.capabilities],
            "depends_on": [a.value for a in self.depends_on_artifacts],
            "constraints": [c.value for c in self.constraints],
            "is_deep_workflow": self.is_deep_workflow,
            "supersedes": self.supersedes,
            "complexity": self.estimated_complexity,
        }


class ProcessRegistry:
    """Central registry of all available processes.

    The registry is the single source of truth for what the AISE system
    can do. The AI planner consults it to:
    1. Understand available capabilities
    2. Resolve artifact dependencies
    3. Select appropriate processes for a given goal
    4. Generate valid execution plans
    """

    def __init__(self) -> None:
        self._processes: dict[str, ProcessDescriptor] = {}
        self._by_capability: dict[ProcessCapability, list[str]] = defaultdict(list)
        self._by_output: dict[ArtifactType, list[str]] = defaultdict(list)
        self._by_agent: dict[str, list[str]] = defaultdict(list)

    def register(self, descriptor: ProcessDescriptor) -> None:
        """Register a process descriptor."""
        if descriptor.id in self._processes:
            raise ValueError(f"Process '{descriptor.id}' is already registered")
        self._processes[descriptor.id] = descriptor
        for cap in descriptor.capabilities:
            self._by_capability[cap].append(descriptor.id)
        for art in descriptor.output_artifact_types:
            self._by_output[art].append(descriptor.id)
        for role in descriptor.agent_roles:
            self._by_agent[role].append(descriptor.id)
        logger.debug(
            "Process registered: id=%s capabilities=%s", descriptor.id, [c.value for c in descriptor.capabilities]
        )

    def register_or_update(self, descriptor: ProcessDescriptor) -> bool:
        """Register a process or update it if it already exists.

        Returns True if a new process was registered, False if updated.
        """
        if descriptor.id in self._processes:
            # Remove old index entries
            old = self._processes[descriptor.id]
            for cap in old.capabilities:
                ids = self._by_capability.get(cap, [])
                if old.id in ids:
                    ids.remove(old.id)
            for art in old.output_artifact_types:
                ids = self._by_output.get(art, [])
                if old.id in ids:
                    ids.remove(old.id)
            for role in old.agent_roles:
                ids = self._by_agent.get(role, [])
                if old.id in ids:
                    ids.remove(old.id)
            del self._processes[descriptor.id]

        self._processes[descriptor.id] = descriptor
        for cap in descriptor.capabilities:
            self._by_capability[cap].append(descriptor.id)
        for art in descriptor.output_artifact_types:
            self._by_output[art].append(descriptor.id)
        for role in descriptor.agent_roles:
            self._by_agent[role].append(descriptor.id)
        return True

    def get(self, process_id: str) -> ProcessDescriptor | None:
        """Get a process by ID."""
        return self._processes.get(process_id)

    def all(self) -> list[ProcessDescriptor]:
        """Return all registered processes."""
        return list(self._processes.values())

    def find_by_capability(self, capability: ProcessCapability) -> list[ProcessDescriptor]:
        """Find all processes with a given capability."""
        ids = self._by_capability.get(capability, [])
        return [self._processes[pid] for pid in ids]

    def find_producers(self, artifact_type: ArtifactType) -> list[ProcessDescriptor]:
        """Find all processes that can produce a given artifact type."""
        ids = self._by_output.get(artifact_type, [])
        return [self._processes[pid] for pid in ids]

    def find_by_agent(self, agent_role: str) -> list[ProcessDescriptor]:
        """Find all processes assignable to a given agent role."""
        ids = self._by_agent.get(agent_role, [])
        return [self._processes[pid] for pid in ids]

    def to_llm_catalog(self) -> list[dict[str, Any]]:
        """Export the catalog as LLM-readable dicts, excluding superseded processes.

        When a deep workflow supersedes atomic steps (e.g., deep_product_workflow
        supersedes requirement_analysis + user_story_writing), only the deep
        workflow is included so the LLM cannot pick the wrong granularity.
        """
        superseded: set[str] = set()
        for p in self._processes.values():
            if p.supersedes:
                superseded.update(p.supersedes)
        return [
            p.to_llm_dict()
            for p in self._processes.values()
            if p.id not in superseded
        ]

    def resolve_dependency_chain(
        self,
        goal_artifact: ArtifactType,
        available: set[ArtifactType] | None = None,
    ) -> list[ProcessDescriptor]:
        """Compute a dependency-ordered list of processes needed to produce goal_artifact.

        Uses BFS on artifact dependencies to find the minimal chain.
        Skips processes whose output artifacts are already available.
        """
        available = available or set()
        if goal_artifact in available:
            return []

        # Find a process that produces the goal
        producers = self.find_producers(goal_artifact)
        if not producers:
            return []

        # Pick the first (or best) producer
        producer = producers[0]

        # Recursively resolve dependencies
        chain: list[ProcessDescriptor] = []
        for dep_artifact in producer.depends_on_artifacts:
            if dep_artifact not in available:
                sub_chain = self.resolve_dependency_chain(dep_artifact, available)
                for p in sub_chain:
                    if p.id not in [c.id for c in chain]:
                        chain.append(p)
                # Mark as now available after resolution
                available.add(dep_artifact)

        # Add the producer itself
        if producer.id not in [c.id for c in chain]:
            chain.append(producer)

        return chain

    @classmethod
    def build_default(cls) -> "ProcessRegistry":
        """Build the default registry with all 36 AISE skills."""
        registry = cls()
        for desc in _default_process_descriptors():
            registry.register(desc)
        logger.info("Default process registry built: %d processes", len(registry.all()))
        return registry

    def auto_discover_from_agents(self, agents: dict[str, Any]) -> int:
        """Auto-discover and register skills from live Agent instances.

        Scans registered agents' skills and creates ProcessDescriptors
        for any skill not already in the registry. This ensures newly
        added skills are automatically available to the AI planner.

        Args:
            agents: Dict of agent_name -> Agent instances.

        Returns:
            Number of newly discovered processes.
        """
        discovered = 0
        for agent_name, agent in agents.items():
            role = getattr(agent, "role", None)
            role_value = role.value if role else agent_name
            skills = getattr(agent, "_skills", {}) or getattr(agent, "skills", {})

            for skill_name, skill in skills.items():
                if skill_name in self._processes:
                    continue  # Already registered

                # Infer descriptor from skill metadata
                desc = self._descriptor_from_skill(skill, skill_name, role_value)
                self.register_or_update(desc)
                discovered += 1
                logger.info(
                    "Auto-discovered process: id=%s agent=%s",
                    skill_name,
                    agent_name,
                )

        if discovered:
            logger.info(
                "Auto-discovery complete: %d new processes (total: %d)",
                discovered,
                len(self._processes),
            )
        return discovered

    @staticmethod
    def _descriptor_from_skill(
        skill: Any,
        skill_name: str,
        agent_role: str,
    ) -> ProcessDescriptor:
        """Create a ProcessDescriptor from a Skill instance."""
        description = getattr(skill, "description", "") or f"Skill: {skill_name}"

        # Infer phase affinity from skill name patterns
        phase = _infer_phase(skill_name)
        capability = _infer_capability(skill_name)

        return ProcessDescriptor(
            id=skill_name,
            name=skill_name.replace("_", " ").title(),
            description=str(description),
            agent_roles=[agent_role],
            phase_affinity=[phase] if phase else [],
            input_keys=[],  # Cannot infer reliably
            output_artifact_types=[],  # Cannot infer reliably
            capabilities=[capability],
            is_deep_workflow="deep" in skill_name.lower(),
        )


def _infer_phase(skill_name: str) -> str:
    """Infer phase affinity from skill name."""
    name = skill_name.lower()
    if any(k in name for k in ("requirement", "product", "story", "feature")):
        return "requirements"
    if any(k in name for k in ("design", "architect", "api")):
        return "design"
    if any(k in name for k in ("code", "develop", "implement", "bug", "refactor")):
        return "implementation"
    if any(k in name for k in ("test", "qa", "review")):
        return "testing"
    return ""


def _infer_capability(skill_name: str) -> ProcessCapability:
    """Infer capability from skill name."""
    name = skill_name.lower()
    if any(k in name for k in ("analysis", "requirement", "parse")):
        return ProcessCapability.ANALYSIS
    if any(k in name for k in ("design", "architect")):
        return ProcessCapability.DESIGN
    if any(k in name for k in ("code", "generate", "implement", "develop")):
        return ProcessCapability.GENERATION
    if any(k in name for k in ("test", "qa")):
        return ProcessCapability.TESTING
    if any(k in name for k in ("review",)):
        return ProcessCapability.REVIEW
    if "deep" in name:
        return ProcessCapability.DEEP_WORKFLOW
    return ProcessCapability.MANAGEMENT


def _default_process_descriptors() -> list[ProcessDescriptor]:
    """Define all AISE processes as structured descriptors.

    This replaces the scattered PHASE_SKILL_PLAYBOOK, PHASE_AGENT_MAP,
    and SKILL_INPUT_HINTS with a single, unified, AI-readable catalog.
    """
    return [
        # === Requirements Phase ===
        ProcessDescriptor(
            id="requirement_analysis",
            name="Requirement Analysis",
            description="Parse raw requirements text into structured functional and non-functional requirements",
            agent_roles=["product_manager"],
            phase_affinity=["requirements"],
            input_keys=["raw_requirements"],
            output_artifact_types=[ArtifactType.REQUIREMENTS],
            capabilities=[ProcessCapability.ANALYSIS],
        ),
        ProcessDescriptor(
            id="user_story_writing",
            name="User Story Writing",
            description="Generate user stories from analyzed requirements",
            agent_roles=["product_manager"],
            phase_affinity=["requirements"],
            input_keys=["requirements"],
            output_artifact_types=[ArtifactType.USER_STORIES],
            capabilities=[ProcessCapability.GENERATION, ProcessCapability.DOCUMENTATION],
            depends_on_artifacts=[ArtifactType.REQUIREMENTS],
        ),
        ProcessDescriptor(
            id="product_design",
            name="Product Design",
            description="Create product requirement document (PRD) from requirements and user stories",
            agent_roles=["product_manager"],
            phase_affinity=["requirements"],
            input_keys=["requirements", "user_stories", "review_feedback"],
            output_artifact_types=[ArtifactType.PRD],
            capabilities=[ProcessCapability.DESIGN],
            depends_on_artifacts=[ArtifactType.REQUIREMENTS, ArtifactType.USER_STORIES],
        ),
        ProcessDescriptor(
            id="product_review",
            name="Product Review",
            description="Review product requirements and PRD for completeness and consistency",
            agent_roles=["product_manager"],
            phase_affinity=["requirements"],
            input_keys=["requirements", "prd"],
            output_artifact_types=[ArtifactType.REVIEW_FEEDBACK],
            capabilities=[ProcessCapability.REVIEW],
            depends_on_artifacts=[ArtifactType.REQUIREMENTS, ArtifactType.PRD],
        ),
        ProcessDescriptor(
            id="system_feature_analysis",
            name="System Feature Analysis",
            description="Analyze system features (SF) from raw requirements",
            agent_roles=["product_manager"],
            phase_affinity=["requirements"],
            input_keys=["raw_requirements", "requirements"],
            output_artifact_types=[ArtifactType.SYSTEM_DESIGN],
            capabilities=[ProcessCapability.ANALYSIS],
        ),
        ProcessDescriptor(
            id="system_requirement_analysis",
            name="System Requirement Analysis",
            description="Derive system requirements (SR) from system design",
            agent_roles=["product_manager"],
            phase_affinity=["requirements"],
            input_keys=["system_design"],
            output_artifact_types=[ArtifactType.SYSTEM_REQUIREMENTS],
            capabilities=[ProcessCapability.ANALYSIS],
            depends_on_artifacts=[ArtifactType.SYSTEM_DESIGN],
        ),
        ProcessDescriptor(
            id="document_generation",
            name="Document Generation",
            description="Generate requirement documentation (System-Requirements.md)",
            agent_roles=["product_manager"],
            phase_affinity=["requirements"],
            input_keys=["system_design", "system_requirements", "output_dir"],
            output_artifact_types=[ArtifactType.PROGRESS_REPORT],
            capabilities=[ProcessCapability.DOCUMENTATION],
            depends_on_artifacts=[ArtifactType.SYSTEM_DESIGN, ArtifactType.SYSTEM_REQUIREMENTS],
        ),
        ProcessDescriptor(
            id="deep_product_workflow",
            name="Deep Product Workflow",
            description="End-to-end deep paired workflow: expand requirements, produce system-design.md with SF list, "
            "produce system-requirements.md with SR list, with multi-round review cycles",
            agent_roles=["product_manager"],
            phase_affinity=["requirements"],
            input_keys=["raw_requirements", "user_memory", "output_dir"],
            output_artifact_types=[
                ArtifactType.REQUIREMENTS,
                ArtifactType.SYSTEM_DESIGN,
                ArtifactType.SYSTEM_REQUIREMENTS,
            ],
            capabilities=[ProcessCapability.DEEP_WORKFLOW, ProcessCapability.ANALYSIS],
            is_deep_workflow=True,
            supersedes=[
                "requirement_analysis",
                "user_story_writing",
                "product_design",
                "product_review",
                "system_feature_analysis",
                "system_requirement_analysis",
                "document_generation",
            ],
            estimated_complexity="high",
        ),
        # === Design Phase ===
        ProcessDescriptor(
            id="system_design",
            name="System Design",
            description="Create system architecture from requirements",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=["requirements"],
            output_artifact_types=[ArtifactType.ARCHITECTURE_DESIGN],
            capabilities=[ProcessCapability.DESIGN],
            depends_on_artifacts=[ArtifactType.REQUIREMENTS],
        ),
        ProcessDescriptor(
            id="api_design",
            name="API Design",
            description="Design API contracts from architecture",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=["requirements"],
            output_artifact_types=[ArtifactType.API_CONTRACT],
            capabilities=[ProcessCapability.DESIGN],
            depends_on_artifacts=[ArtifactType.ARCHITECTURE_DESIGN],
        ),
        ProcessDescriptor(
            id="tech_stack_selection",
            name="Tech Stack Selection",
            description="Select technology stack based on requirements and architecture",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=["requirements"],
            output_artifact_types=[ArtifactType.TECH_STACK],
            capabilities=[ProcessCapability.ANALYSIS, ProcessCapability.DESIGN],
            depends_on_artifacts=[ArtifactType.REQUIREMENTS, ArtifactType.ARCHITECTURE_DESIGN],
        ),
        ProcessDescriptor(
            id="architecture_review",
            name="Architecture Review",
            description="Review architecture design for quality and completeness",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=["requirements"],
            output_artifact_types=[ArtifactType.REVIEW_FEEDBACK],
            capabilities=[ProcessCapability.REVIEW],
            depends_on_artifacts=[ArtifactType.ARCHITECTURE_DESIGN, ArtifactType.API_CONTRACT, ArtifactType.TECH_STACK],
        ),
        ProcessDescriptor(
            id="architecture_requirement_analysis",
            name="Architecture Requirement Analysis",
            description="Analyze architecture requirements from system requirements",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=["requirements"],
            output_artifact_types=[ArtifactType.ARCHITECTURE_DESIGN],
            capabilities=[ProcessCapability.ANALYSIS],
            depends_on_artifacts=[ArtifactType.REQUIREMENTS],
        ),
        ProcessDescriptor(
            id="functional_design",
            name="Functional Design",
            description="Create functional design (FN decomposition) from architecture",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=["requirements"],
            output_artifact_types=[ArtifactType.FUNCTIONAL_DESIGN],
            capabilities=[ProcessCapability.DESIGN],
            depends_on_artifacts=[ArtifactType.REQUIREMENTS],
        ),
        ProcessDescriptor(
            id="status_tracking",
            name="Status Tracking",
            description="Track development status across all phases",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=["requirements"],
            output_artifact_types=[ArtifactType.STATUS_TRACKING],
            capabilities=[ProcessCapability.MANAGEMENT],
        ),
        ProcessDescriptor(
            id="architecture_document_generation",
            name="Architecture Document Generation",
            description="Generate architecture documentation",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=["output_dir"],
            output_artifact_types=[ArtifactType.PROGRESS_REPORT],
            capabilities=[ProcessCapability.DOCUMENTATION],
            depends_on_artifacts=[ArtifactType.ARCHITECTURE_DESIGN],
        ),
        ProcessDescriptor(
            id="deep_architecture_workflow",
            name="Deep Architecture Workflow",
            description="End-to-end deep architecture workflow: architecture foundation, structure design, "
            "subsystem detail design, code skeleton generation, with multi-round review cycles",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=["output_dir", "source_dir", "requirements"],
            output_artifact_types=[
                ArtifactType.ARCHITECTURE_DESIGN,
                ArtifactType.API_CONTRACT,
                ArtifactType.FUNCTIONAL_DESIGN,
            ],
            capabilities=[ProcessCapability.DEEP_WORKFLOW, ProcessCapability.DESIGN],
            depends_on_artifacts=[ArtifactType.REQUIREMENTS, ArtifactType.SYSTEM_REQUIREMENTS],
            is_deep_workflow=True,
            supersedes=[
                "system_design",
                "api_design",
                "tech_stack_selection",
                "architecture_review",
                "architecture_requirement_analysis",
                "functional_design",
                "architecture_document_generation",
            ],
            estimated_complexity="high",
        ),
        # === Implementation Phase ===
        ProcessDescriptor(
            id="code_generation",
            name="Code Generation",
            description="Generate source code from design artifacts",
            agent_roles=["developer"],
            phase_affinity=["implementation"],
            input_keys=["requirements", "system_design", "api_contract", "functional_design"],
            output_artifact_types=[ArtifactType.SOURCE_CODE],
            capabilities=[ProcessCapability.GENERATION],
            depends_on_artifacts=[ArtifactType.ARCHITECTURE_DESIGN, ArtifactType.API_CONTRACT, ArtifactType.TECH_STACK],
            constraints=[ProcessConstraint.REQUIRES_ARCHITECTURE],
        ),
        ProcessDescriptor(
            id="unit_test_writing",
            name="Unit Test Writing",
            description="Write unit tests for generated source code",
            agent_roles=["developer"],
            phase_affinity=["implementation"],
            input_keys=["source_code", "requirements"],
            output_artifact_types=[ArtifactType.UNIT_TESTS],
            capabilities=[ProcessCapability.TESTING],
            depends_on_artifacts=[ArtifactType.SOURCE_CODE],
            constraints=[ProcessConstraint.REQUIRES_SOURCE_CODE],
        ),
        ProcessDescriptor(
            id="code_review",
            name="Code Review",
            description="Review source code quality and correctness",
            agent_roles=["developer", "reviewer"],
            phase_affinity=["implementation"],
            input_keys=["source_code", "requirements"],
            output_artifact_types=[ArtifactType.REVIEW_FEEDBACK],
            capabilities=[ProcessCapability.REVIEW],
            depends_on_artifacts=[ArtifactType.SOURCE_CODE, ArtifactType.UNIT_TESTS],
            constraints=[ProcessConstraint.REQUIRES_SOURCE_CODE],
        ),
        ProcessDescriptor(
            id="bug_fix",
            name="Bug Fix",
            description="Fix reported bugs in source code",
            agent_roles=["developer"],
            phase_affinity=["implementation"],
            input_keys=["source_code", "test_report", "bug_report"],
            output_artifact_types=[ArtifactType.BUG_REPORT],
            capabilities=[ProcessCapability.GENERATION],
            depends_on_artifacts=[ArtifactType.SOURCE_CODE],
            constraints=[ProcessConstraint.REQUIRES_SOURCE_CODE, ProcessConstraint.ON_DEMAND_ONLY],
        ),
        ProcessDescriptor(
            id="tdd_session",
            name="TDD Session",
            description="Interactive test-driven development session",
            agent_roles=["developer"],
            phase_affinity=["implementation"],
            input_keys=["requirements", "source_code"],
            output_artifact_types=[ArtifactType.SOURCE_CODE, ArtifactType.UNIT_TESTS],
            capabilities=[ProcessCapability.GENERATION, ProcessCapability.TESTING],
            constraints=[ProcessConstraint.ON_DEMAND_ONLY],
        ),
        ProcessDescriptor(
            id="deep_developer_workflow",
            name="Deep Developer Workflow",
            description="End-to-end deep implementation workflow: split by subsystem, test-first iterations, "
            "code review rounds, static checks and unit tests for each SR group",
            agent_roles=["developer"],
            phase_affinity=["implementation"],
            input_keys=["source_dir", "tests_dir"],
            output_artifact_types=[ArtifactType.SOURCE_CODE, ArtifactType.UNIT_TESTS],
            capabilities=[ProcessCapability.DEEP_WORKFLOW, ProcessCapability.GENERATION, ProcessCapability.TESTING],
            depends_on_artifacts=[ArtifactType.ARCHITECTURE_DESIGN, ArtifactType.FUNCTIONAL_DESIGN],
            is_deep_workflow=True,
            supersedes=["code_generation", "unit_test_writing", "code_review"],
            estimated_complexity="high",
        ),
        # === Testing Phase ===
        ProcessDescriptor(
            id="test_plan_design",
            name="Test Plan Design",
            description="Design comprehensive test plan covering all system features",
            agent_roles=["qa_engineer"],
            phase_affinity=["testing"],
            input_keys=["requirements", "system_design"],
            output_artifact_types=[ArtifactType.TEST_PLAN],
            capabilities=[ProcessCapability.TESTING, ProcessCapability.DESIGN],
            depends_on_artifacts=[ArtifactType.ARCHITECTURE_DESIGN, ArtifactType.API_CONTRACT],
        ),
        ProcessDescriptor(
            id="test_case_design",
            name="Test Case Design",
            description="Create detailed executable test cases from test plan",
            agent_roles=["qa_engineer"],
            phase_affinity=["testing"],
            input_keys=["test_plan", "requirements"],
            output_artifact_types=[ArtifactType.TEST_CASES],
            capabilities=[ProcessCapability.TESTING, ProcessCapability.DESIGN],
            depends_on_artifacts=[ArtifactType.TEST_PLAN],
        ),
        ProcessDescriptor(
            id="test_automation",
            name="Test Automation",
            description="Implement automated test scripts from test cases",
            agent_roles=["qa_engineer"],
            phase_affinity=["testing"],
            input_keys=["test_cases", "source_code"],
            output_artifact_types=[ArtifactType.AUTOMATED_TESTS],
            capabilities=[ProcessCapability.TESTING, ProcessCapability.GENERATION],
            depends_on_artifacts=[ArtifactType.TEST_CASES, ArtifactType.TECH_STACK],
        ),
        ProcessDescriptor(
            id="test_review",
            name="Test Review",
            description="Review test coverage and quality",
            agent_roles=["qa_engineer"],
            phase_affinity=["testing"],
            input_keys=["test_plan", "test_cases", "automated_tests"],
            output_artifact_types=[ArtifactType.REVIEW_FEEDBACK],
            capabilities=[ProcessCapability.REVIEW],
            depends_on_artifacts=[ArtifactType.TEST_PLAN, ArtifactType.TEST_CASES, ArtifactType.AUTOMATED_TESTS],
        ),
        ProcessDescriptor(
            id="deep_testing_workflow",
            name="Deep Testing Workflow",
            description="End-to-end deep testing workflow with automated test generation and quality checks",
            agent_roles=["qa_engineer"],
            phase_affinity=["testing"],
            input_keys=["source_code", "requirements"],
            output_artifact_types=[ArtifactType.TEST_PLAN, ArtifactType.TEST_CASES, ArtifactType.AUTOMATED_TESTS],
            capabilities=[ProcessCapability.DEEP_WORKFLOW, ProcessCapability.TESTING],
            depends_on_artifacts=[ArtifactType.SOURCE_CODE],
            is_deep_workflow=True,
            supersedes=["test_plan_design", "test_case_design", "test_automation", "test_review"],
            estimated_complexity="high",
        ),
        # === Cross-cutting / Management ===
        ProcessDescriptor(
            id="progress_tracking",
            name="Progress Tracking",
            description="Track and report project progress across all phases",
            agent_roles=["project_manager"],
            phase_affinity=["requirements", "design", "implementation", "testing"],
            input_keys=["phase_results", "artifact_ids"],
            output_artifact_types=[ArtifactType.PROGRESS_REPORT],
            capabilities=[ProcessCapability.MANAGEMENT],
            constraints=[ProcessConstraint.ON_DEMAND_ONLY],
        ),
        ProcessDescriptor(
            id="team_health",
            name="Team Health",
            description="Monitor and report on team health and workload",
            agent_roles=["project_manager"],
            phase_affinity=["requirements", "design", "implementation", "testing"],
            input_keys=["agent_registry", "message_history", "task_statuses"],
            output_artifact_types=[ArtifactType.PROGRESS_REPORT],
            capabilities=[ProcessCapability.MANAGEMENT],
            constraints=[ProcessConstraint.ON_DEMAND_ONLY],
        ),
        ProcessDescriptor(
            id="conflict_resolution",
            name="Conflict Resolution",
            description="Resolve conflicts between team members or requirements",
            agent_roles=["project_manager"],
            phase_affinity=["requirements", "design", "implementation", "testing"],
            input_keys=["topic", "options", "constraints"],
            output_artifact_types=[ArtifactType.REVIEW_FEEDBACK],
            capabilities=[ProcessCapability.MANAGEMENT],
            constraints=[ProcessConstraint.ON_DEMAND_ONLY],
        ),
        ProcessDescriptor(
            id="version_release",
            name="Version Release",
            description="Prepare and manage version releases",
            agent_roles=["project_manager"],
            phase_affinity=["testing"],
            input_keys=["release_notes", "version"],
            output_artifact_types=[ArtifactType.PROGRESS_REPORT],
            capabilities=[ProcessCapability.MANAGEMENT],
            constraints=[ProcessConstraint.ON_DEMAND_ONLY],
        ),
        ProcessDescriptor(
            id="team_formation",
            name="Team Formation",
            description="Form development team and assign roles",
            agent_roles=["rd_director"],
            phase_affinity=["requirements"],
            input_keys=["roles", "development_mode"],
            output_artifact_types=[ArtifactType.PROGRESS_REPORT],
            capabilities=[ProcessCapability.MANAGEMENT],
            constraints=[ProcessConstraint.ON_DEMAND_ONLY],
        ),
        ProcessDescriptor(
            id="requirement_distribution",
            name="Requirement Distribution",
            description="Distribute requirements to team members",
            agent_roles=["rd_director"],
            phase_affinity=["requirements"],
            input_keys=["product_requirements", "architecture_requirements"],
            output_artifact_types=[ArtifactType.PROGRESS_REPORT],
            capabilities=[ProcessCapability.MANAGEMENT],
            constraints=[ProcessConstraint.ON_DEMAND_ONLY],
        ),
        # === GitHub Integration ===
        ProcessDescriptor(
            id="pr_submission",
            name="PR Submission",
            description="Submit pull request to GitHub",
            agent_roles=["product_manager"],
            phase_affinity=["implementation"],
            input_keys=["source_code", "branch_name"],
            output_artifact_types=[ArtifactType.PROGRESS_REPORT],
            capabilities=[ProcessCapability.INTEGRATION],
            constraints=[ProcessConstraint.REQUIRES_GITHUB, ProcessConstraint.ON_DEMAND_ONLY],
        ),
        ProcessDescriptor(
            id="pr_review",
            name="PR Review",
            description="Review pull request on GitHub",
            agent_roles=["architect", "developer", "product_manager", "project_manager", "qa_engineer", "reviewer"],
            phase_affinity=["implementation"],
            input_keys=["pr_number", "feedback", "event"],
            output_artifact_types=[ArtifactType.REVIEW_FEEDBACK],
            capabilities=[ProcessCapability.REVIEW, ProcessCapability.INTEGRATION],
            constraints=[ProcessConstraint.REQUIRES_GITHUB, ProcessConstraint.ON_DEMAND_ONLY],
        ),
        ProcessDescriptor(
            id="pr_merge",
            name="PR Merge",
            description="Merge approved pull request",
            agent_roles=["product_manager", "project_manager", "reviewer"],
            phase_affinity=["implementation"],
            input_keys=["pr_number", "merge_method", "commit_title"],
            output_artifact_types=[ArtifactType.PROGRESS_REPORT],
            capabilities=[ProcessCapability.INTEGRATION],
            constraints=[ProcessConstraint.REQUIRES_GITHUB, ProcessConstraint.ON_DEMAND_ONLY],
        ),
    ]
