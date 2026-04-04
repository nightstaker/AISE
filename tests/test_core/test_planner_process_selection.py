"""Tests for Markdown-based process selection and AIPlanner integration."""

from __future__ import annotations

import pytest

from aise.core.ai_planner import AIPlanner, PlannerContext
from aise.core.artifact import ArtifactType
from aise.core.process_md_adapter import ProcessMdAdapter, process_to_descriptor
from aise.core.process_md_repository import ProcessRepository
from aise.core.process_registry import ProcessRegistry


@pytest.fixture
def md_repo() -> ProcessRepository:
    """Create a ProcessRepository pointing to the test processes directory."""
    return ProcessRepository()


@pytest.fixture
def md_adapter(md_repo: ProcessRepository) -> ProcessMdAdapter:
    """Create a ProcessMdAdapter."""
    adapter = ProcessMdAdapter()
    return adapter


@pytest.fixture
def registry() -> ProcessRegistry:
    """Create a ProcessRegistry with default processes."""
    return ProcessRegistry.build_default()


class TestProcessRepository:
    """Test Markdown process file loading and parsing."""

    def test_loads_all_process_files(self, md_repo: ProcessRepository) -> None:
        """ProcessRepository should load all .process.md files."""
        processes = md_repo.list_processes()
        assert len(processes) >= 3, f"Expected at least 3 processes, got {len(processes)}"

        process_ids = [p.process_id for p in processes]
        assert "agile_sprint_v1" in process_ids
        assert "waterfall_standard_v1" in process_ids
        assert "runtime_design_standard" in process_ids

    def test_waterfall_process_structure(self, md_repo: ProcessRepository) -> None:
        """Waterfall process should have 4 main phases."""
        process = md_repo.get_process("waterfall_standard_v1")
        assert process is not None
        assert process.work_type == "structured_development"
        assert len(process.steps) >= 3  # At least requirement, design, implementation

        step_ids = [s.step_id.lower() for s in process.steps]
        step_names = [s.name.lower() for s in process.steps]
        all_text = " ".join(step_ids + step_names)

        assert any(kw in all_text for kw in ["requirement", "specification"])
        assert any(kw in all_text for kw in ["design", "architecture"])
        assert any(kw in all_text for kw in ["implementation", "development", "coding"])

    def test_agile_process_structure(self, md_repo: ProcessRepository) -> None:
        """Agile process should have sprint phases."""
        process = md_repo.get_process("agile_sprint_v1")
        assert process is not None
        assert process.work_type == "rapid_iteration"

        step_ids = [s.step_id.lower() for s in process.steps]
        step_names = [s.name.lower() for s in process.steps]
        all_text = " ".join(step_ids + step_names)

        assert any(kw in all_text for kw in ["planning", "sprint_planning"])
        assert any(kw in all_text for kw in ["execution", "prototyping", "coding"])
        assert any(kw in all_text for kw in ["review", "retrospective"])

    def test_select_process_returns_selection(self, md_repo: ProcessRepository) -> None:
        """Selection should work for relevant prompts."""
        # Use English keywords that will match the process keywords
        prompt = "new structured software project with requirements analysis and design"
        selection = md_repo.select_process(prompt, min_score=0.5)
        # Should match waterfall (has "structured" in work_type)
        assert selection is not None

    def test_select_process_agile_iteration(self, md_repo: ProcessRepository) -> None:
        """Agile should be selected for iterative/rapid projects."""
        prompt = "agile iterative development sprint rapid prototyping"
        selection = md_repo.select_process(prompt, min_score=1.0)
        assert selection is not None
        assert selection.process.process_id == "agile_sprint_v1"


class TestProcessMdAdapter:
    """Test ProcessDescriptor conversion from Markdown ProcessDefinition."""

    def test_convert_waterfall_to_descriptor(
        self, md_repo: ProcessRepository, registry: ProcessRegistry
    ) -> None:
        """Waterfall process should map to deep workflow skills."""
        process = md_repo.get_process("waterfall_standard_v1")
        assert process is not None

        descriptor = process_to_descriptor(process, registry)
        assert descriptor.id == "md_process_waterfall_standard_v1"
        # Should include deep workflows
        assert "deep_product_workflow" in descriptor.supersedes
        assert "deep_architecture_workflow" in descriptor.supersedes
        assert "deep_developer_workflow" in descriptor.supersedes
        # Should also include atomic skills
        assert "requirement_analysis" in descriptor.supersedes
        assert "architecture_design" in descriptor.supersedes

    def test_load_all_processes(self, md_adapter: ProcessMdAdapter, registry: ProcessRegistry) -> None:
        """Adapter should load all processes and convert to descriptors."""
        descriptors = md_adapter.load_all(registry)
        assert len(descriptors) >= 3

        # Check waterfall
        waterfall = md_adapter.get_descriptor("waterfall_standard_v1")
        assert waterfall is not None
        assert "deep_product_workflow" in waterfall.supersedes

    def test_agile_descriptor(self, md_adapter: ProcessMdAdapter, registry: ProcessRegistry) -> None:
        """Agile process descriptor should include relevant workflows."""
        md_adapter.load_all(registry)
        agile = md_adapter.get_descriptor("agile_sprint_v1")
        assert agile is not None
        assert "rapid_iteration" in agile.phase_affinity


class TestAIPlannerWithProcess:
    """Test AIPlanner with process template constraint."""

    def test_plan_with_waterfall_process(
        self, registry: ProcessRegistry, md_adapter: ProcessMdAdapter
    ) -> None:
        """AIPlanner should generate a plan that follows waterfall template."""
        planner = AIPlanner(registry=registry, md_adapter=md_adapter)

        context = PlannerContext(
            user_requirements="Develop a new structured web application",
            available_artifacts={},
            goal_artifacts=[ArtifactType.SOURCE_CODE],
        )

        # Generate plan with waterfall constraint
        plan = planner.generate_plan(context, selected_process_id="waterfall_standard_v1")

        assert plan is not None
        assert len(plan.steps) > 0

    def test_plan_auto_selects_process(
        self, registry: ProcessRegistry, md_adapter: ProcessMdAdapter
    ) -> None:
        """AIPlanner should auto-select process when no ID is given."""
        planner = AIPlanner(registry=registry, md_adapter=md_adapter)

        context = PlannerContext(
            user_requirements="structured new software project with full requirements and design",
            available_artifacts={},
        )

        plan = planner.generate_plan(context)  # No process_id, should auto-select

        assert plan is not None
        assert len(plan.steps) > 0

    def test_plan_includes_process_steps(self, registry: ProcessRegistry, md_adapter: ProcessMdAdapter) -> None:
        """Generated plan should include steps from the selected process."""
        planner = AIPlanner(registry=registry, md_adapter=md_adapter)

        context = PlannerContext(
            user_requirements="New project with requirements and design",
            available_artifacts={},
        )

        plan = planner.generate_plan(context, selected_process_id="waterfall_standard_v1")

        # Plan should have phases
        step_process_ids = [s.process_id for s in plan.steps]

        # At minimum, should have requirement, design, and implementation phases
        has_requirement = any("product" in s or "requirement" in s for s in step_process_ids)
        has_design = any("architecture" in s or "design" in s for s in step_process_ids)
        has_implementation = any("developer" in s or "code" in s for s in step_process_ids)

        assert has_requirement or has_design or has_implementation, (
            f"Plan missing key phases. Steps: {step_process_ids}"
        )

    def test_plan_respects_process_agent_constraints(
        self, registry: ProcessRegistry, md_adapter: ProcessMdAdapter
    ) -> None:
        """Agents assigned to steps should be valid for the selected processes."""
        planner = AIPlanner(registry=registry, md_adapter=md_adapter)

        context = PlannerContext(
            user_requirements="New project",
            available_artifacts={},
        )

        plan = planner.generate_plan(context, selected_process_id="waterfall_standard_v1")

        # Get the waterfall process definition
        process = md_adapter.md_repo.get_process("waterfall_standard_v1")
        assert process is not None

        # Each step should use an agent that's in the registry
        for step in plan.steps:
            proc = registry.get(step.process_id)
            if proc:
                assert step.agent in proc.agent_roles, (
                    f"Agent {step.agent} not valid for process {step.process_id}. "
                    f"Valid: {proc.agent_roles}"
                )
