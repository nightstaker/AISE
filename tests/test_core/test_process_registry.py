"""Tests for the AI-First Process Registry.

The ProcessRegistry provides a structured, machine-readable catalog of all
available processes (skills) so that an AI planner can understand capabilities,
dependencies, and constraints — then dynamically compose workflows.
"""

from __future__ import annotations

import json

import pytest

from aise.core.artifact import ArtifactType
from aise.core.process_registry import (
    ProcessCapability,
    ProcessConstraint,
    ProcessDescriptor,
    ProcessRegistry,
)


class TestProcessDescriptor:
    """Test the ProcessDescriptor data class."""

    def test_basic_creation(self):
        desc = ProcessDescriptor(
            id="requirement_analysis",
            name="Requirement Analysis",
            description="Analyze raw requirements into structured format",
            agent_roles=["product_manager"],
            phase_affinity=["requirements"],
            input_keys=["raw_requirements"],
            output_artifact_types=[ArtifactType.REQUIREMENTS],
            capabilities=[ProcessCapability.ANALYSIS],
        )
        assert desc.id == "requirement_analysis"
        assert "product_manager" in desc.agent_roles
        assert ArtifactType.REQUIREMENTS in desc.output_artifact_types

    def test_descriptor_with_dependencies(self):
        desc = ProcessDescriptor(
            id="code_generation",
            name="Code Generation",
            description="Generate source code from design artifacts",
            agent_roles=["developer"],
            phase_affinity=["implementation"],
            input_keys=["requirements", "system_design", "api_contract"],
            output_artifact_types=[ArtifactType.SOURCE_CODE],
            capabilities=[ProcessCapability.GENERATION],
            depends_on_artifacts=[
                ArtifactType.ARCHITECTURE_DESIGN,
                ArtifactType.API_CONTRACT,
            ],
        )
        assert ArtifactType.ARCHITECTURE_DESIGN in desc.depends_on_artifacts
        assert len(desc.depends_on_artifacts) == 2

    def test_descriptor_to_dict_for_llm(self):
        """Descriptor must be serializable to a dict that an LLM can read."""
        desc = ProcessDescriptor(
            id="test_skill",
            name="Test Skill",
            description="A test skill for validation",
            agent_roles=["qa_engineer"],
            phase_affinity=["testing"],
            input_keys=["source_code"],
            output_artifact_types=[ArtifactType.TEST_PLAN],
            capabilities=[ProcessCapability.TESTING],
            constraints=[ProcessConstraint.REQUIRES_SOURCE_CODE],
        )
        d = desc.to_llm_dict()
        assert isinstance(d, dict)
        assert d["id"] == "test_skill"
        assert "testing" in d["capabilities"]
        assert "requires_source_code" in d["constraints"]
        # Must be JSON-serializable
        json.dumps(d)

    def test_descriptor_can_satisfy(self):
        """Check if a process can produce a needed artifact type."""
        desc = ProcessDescriptor(
            id="system_design",
            name="System Design",
            description="Create system architecture",
            agent_roles=["architect"],
            phase_affinity=["design"],
            input_keys=["requirements"],
            output_artifact_types=[ArtifactType.ARCHITECTURE_DESIGN],
            capabilities=[ProcessCapability.DESIGN],
        )
        assert desc.can_produce(ArtifactType.ARCHITECTURE_DESIGN)
        assert not desc.can_produce(ArtifactType.SOURCE_CODE)


class TestProcessRegistry:
    """Test the ProcessRegistry that holds all available processes."""

    @pytest.fixture
    def registry(self):
        return ProcessRegistry()

    def test_register_and_retrieve(self, registry):
        desc = ProcessDescriptor(
            id="my_skill",
            name="My Skill",
            description="Does something",
            agent_roles=["developer"],
            phase_affinity=["implementation"],
            input_keys=[],
            output_artifact_types=[ArtifactType.SOURCE_CODE],
            capabilities=[ProcessCapability.GENERATION],
        )
        registry.register(desc)
        assert registry.get("my_skill") == desc

    def test_register_duplicate_raises(self, registry):
        desc = ProcessDescriptor(
            id="dup",
            name="Dup",
            description="",
            agent_roles=[],
            phase_affinity=[],
            input_keys=[],
            output_artifact_types=[],
            capabilities=[],
        )
        registry.register(desc)
        with pytest.raises(ValueError, match="already registered"):
            registry.register(desc)

    def test_get_nonexistent_returns_none(self, registry):
        assert registry.get("nonexistent") is None

    def test_find_by_capability(self, registry):
        registry.register(
            ProcessDescriptor(
                id="s1",
                name="S1",
                description="",
                agent_roles=["dev"],
                phase_affinity=[],
                input_keys=[],
                output_artifact_types=[],
                capabilities=[ProcessCapability.GENERATION],
            )
        )
        registry.register(
            ProcessDescriptor(
                id="s2",
                name="S2",
                description="",
                agent_roles=["qa"],
                phase_affinity=[],
                input_keys=[],
                output_artifact_types=[],
                capabilities=[ProcessCapability.TESTING],
            )
        )
        gen_procs = registry.find_by_capability(ProcessCapability.GENERATION)
        assert len(gen_procs) == 1
        assert gen_procs[0].id == "s1"

    def test_find_by_output_artifact(self, registry):
        registry.register(
            ProcessDescriptor(
                id="s1",
                name="S1",
                description="",
                agent_roles=[],
                phase_affinity=[],
                input_keys=[],
                output_artifact_types=[ArtifactType.SOURCE_CODE],
                capabilities=[],
            )
        )
        registry.register(
            ProcessDescriptor(
                id="s2",
                name="S2",
                description="",
                agent_roles=[],
                phase_affinity=[],
                input_keys=[],
                output_artifact_types=[ArtifactType.TEST_PLAN],
                capabilities=[],
            )
        )
        results = registry.find_producers(ArtifactType.SOURCE_CODE)
        assert len(results) == 1
        assert results[0].id == "s1"

    def test_find_by_agent_role(self, registry):
        registry.register(
            ProcessDescriptor(
                id="s1",
                name="S1",
                description="",
                agent_roles=["developer"],
                phase_affinity=[],
                input_keys=[],
                output_artifact_types=[],
                capabilities=[],
            )
        )
        registry.register(
            ProcessDescriptor(
                id="s2",
                name="S2",
                description="",
                agent_roles=["architect"],
                phase_affinity=[],
                input_keys=[],
                output_artifact_types=[],
                capabilities=[],
            )
        )
        results = registry.find_by_agent("developer")
        assert len(results) == 1
        assert results[0].id == "s1"

    def test_to_llm_catalog(self, registry):
        """The full catalog must be exportable as a list of dicts for LLM context."""
        registry.register(
            ProcessDescriptor(
                id="s1",
                name="S1",
                description="Skill 1",
                agent_roles=["dev"],
                phase_affinity=["impl"],
                input_keys=["a"],
                output_artifact_types=[ArtifactType.SOURCE_CODE],
                capabilities=[ProcessCapability.GENERATION],
            )
        )
        catalog = registry.to_llm_catalog()
        assert isinstance(catalog, list)
        assert len(catalog) == 1
        assert catalog[0]["id"] == "s1"
        # Must be JSON-serializable
        json.dumps(catalog)

    def test_resolve_dependency_chain(self, registry):
        """Registry can compute which processes are needed to satisfy a goal artifact."""
        # Register a chain: req_analysis → system_design → code_gen
        registry.register(
            ProcessDescriptor(
                id="req_analysis",
                name="Req Analysis",
                description="",
                agent_roles=["pm"],
                phase_affinity=["requirements"],
                input_keys=["raw_requirements"],
                output_artifact_types=[ArtifactType.REQUIREMENTS],
                capabilities=[ProcessCapability.ANALYSIS],
                depends_on_artifacts=[],
            )
        )
        registry.register(
            ProcessDescriptor(
                id="system_design",
                name="System Design",
                description="",
                agent_roles=["architect"],
                phase_affinity=["design"],
                input_keys=["requirements"],
                output_artifact_types=[ArtifactType.ARCHITECTURE_DESIGN],
                capabilities=[ProcessCapability.DESIGN],
                depends_on_artifacts=[ArtifactType.REQUIREMENTS],
            )
        )
        registry.register(
            ProcessDescriptor(
                id="code_gen",
                name="Code Gen",
                description="",
                agent_roles=["dev"],
                phase_affinity=["implementation"],
                input_keys=["system_design"],
                output_artifact_types=[ArtifactType.SOURCE_CODE],
                capabilities=[ProcessCapability.GENERATION],
                depends_on_artifacts=[ArtifactType.ARCHITECTURE_DESIGN],
            )
        )

        chain = registry.resolve_dependency_chain(ArtifactType.SOURCE_CODE)
        ids = [p.id for p in chain]
        assert "req_analysis" in ids
        assert "system_design" in ids
        assert "code_gen" in ids
        # Order matters: dependencies must come before dependents
        assert ids.index("req_analysis") < ids.index("system_design")
        assert ids.index("system_design") < ids.index("code_gen")

    def test_build_from_skills_spec(self):
        """Registry can be built from the SKILLS_SPEC.md data."""
        registry = ProcessRegistry.build_default()
        # Should have at least the core skills
        assert registry.get("requirement_analysis") is not None
        assert registry.get("deep_product_workflow") is not None
        assert registry.get("deep_architecture_workflow") is not None
        assert registry.get("deep_developer_workflow") is not None
        assert registry.get("code_generation") is not None
        assert len(registry.all()) >= 30  # We have 36 skills
