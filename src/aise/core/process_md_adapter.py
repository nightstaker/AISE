"""Adapter to convert Markdown-based ProcessDefinition to ProcessRegistry ProcessDescriptor."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .process_md_repository import ProcessDefinition, ProcessRepository

if TYPE_CHECKING:
    from .process_registry import ProcessDescriptor, ProcessRegistry


def process_to_descriptor(process: ProcessDefinition, registry: "ProcessRegistry") -> "ProcessDescriptor":
    """Convert a Markdown ProcessDefinition to a ProcessDescriptor compatible with ProcessRegistry.

    This adapter maps the Markdown-defined process steps to existing skills in the registry.
    The mapping is based on step names and participating agents.
    """
    from .process_registry import ProcessCapability, ProcessDescriptor

    # Map process work_type to capability
    capability_map = {
        "rapid_iteration": ProcessCapability.MANAGEMENT,
        "structured_development": ProcessCapability.DESIGN,
        "runtime_design": ProcessCapability.DESIGN,
    }
    capability = capability_map.get(process.work_type, ProcessCapability.MANAGEMENT)

    # Build a list of skills that should be included when this process is selected
    # This is a heuristic: we look for deep workflow skills that match the process steps
    included_process_ids: list[str] = []

    for step in process.steps:
        step_name_lower = step.name.lower()
        step_id_lower = step.step_id.lower()

        # Map step names to deep workflow skills
        kw_list = ["requirement", "sprint_planning", "req_analysis"]
        if any(kw in step_name_lower or kw in step_id_lower for kw in kw_list):
            included_process_ids.append("deep_product_workflow")
        elif any(kw in step_name_lower or kw in step_id_lower for kw in ["design", "architecture", "subsystem"]):
            included_process_ids.append("deep_architecture_workflow")
        elif any(kw in step_name_lower or kw in step_id_lower for kw in ["implementation", "coding", "execution"]):
            included_process_ids.append("deep_developer_workflow")
        elif any(kw in step_name_lower or kw in step_id_lower for kw in ["test", "verification", "review"]):
            included_process_ids.append("deep_testing_workflow")

    # Remove duplicates while preserving order
    seen: set[str] = set()
    unique_included: list[str] = []
    for pid in included_process_ids:
        if pid not in seen:
            seen.add(pid)
            unique_included.append(pid)

    # Build description from process summary and steps
    step_descriptions = []
    for step in process.steps:
        agents_str = ", ".join(step.participating_agents) if step.participating_agents else "unspecified"
        step_descriptions.append(f"- {step.name}: {step.description} (agents: {agents_str})")

    full_description = (
        f"{process.summary}\n\n"
        f"Work Type: {process.work_type}\n\n"
        f"Steps:\n" + "\n".join(step_descriptions)
    )

    # Determine which atomic skills this process supersedes
    supersedes: list[str] = []
    # Add the deep workflows that this process maps to
    supersedes.extend(unique_included)  # Include the deep workflows directly
    # Also include atomic skills that are superseded by these deep workflows
    if "deep_product_workflow" in unique_included:
        supersedes.extend(["requirement_analysis", "system_requirement_design", "system_requirement_review"])
    if "deep_architecture_workflow" in unique_included:
        supersedes.extend([
            "architecture_design", "architecture_review",
            "subsystem_architecture_design", "subsystem_architecture_review"
        ])
    if "deep_developer_workflow" in unique_included:
        supersedes.extend([
            "code_generation", "code_review", "tdd_session", "test_case_design"
        ])

    descriptor = ProcessDescriptor(
        id=f"md_process_{process.process_id}",
        name=process.name,
        description=full_description,
        agent_roles=list({agent for step in process.steps for agent in step.participating_agents if agent}),
        phase_affinity=process.work_type,
        input_keys=["raw_requirements"],
        output_artifact_types=[],  # Will be inferred from included skills
        capabilities=[capability],
        depends_on_artifacts=set(),
        constraints=set(),
        is_deep_workflow=False,  # This is a process template, not a deep workflow skill
        supersedes=supersedes,
    )

    return descriptor


class ProcessMdAdapter:
    """Adapter that loads Markdown process definitions and converts them to ProcessDescriptors."""

    def __init__(self, process_dir: str | None = None):
        self.md_repo = ProcessRepository(process_dir=process_dir)
        self._descriptors: dict[str, "ProcessDescriptor"] = {}

    def load_all(self, registry: "ProcessRegistry") -> dict[str, "ProcessDescriptor"]:
        """Load all Markdown process definitions and convert to ProcessDescriptors.

        Returns a dict mapping process_id to ProcessDescriptor.
        """
        self._descriptors = {}
        for process in self.md_repo.list_processes():
            descriptor = process_to_descriptor(process, registry)
            self._descriptors[process.process_id] = descriptor
        return self._descriptors

    def get_descriptor(self, process_id: str) -> "ProcessDescriptor | None":
        return self._descriptors.get(process_id)

    def list_processes(self) -> list["ProcessDescriptor"]:
        return list(self._descriptors.values())

    def select_process(self, prompt: str, *, min_score: float = 1.2):
        """Select the best matching process based on the prompt."""
        return self.md_repo.select_process(prompt, min_score=min_score)
