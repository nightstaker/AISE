"""Tests for the Product Manager agent and skills."""

from aise.agents.product_manager import ProductManagerAgent
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus


class TestProductManagerAgent:
    def _make_agent(self):
        bus = MessageBus()
        store = ArtifactStore()
        return ProductManagerAgent(bus, store), store

    def test_has_all_skills(self):
        agent, _ = self._make_agent()
        expected = {
            "requirement_analysis",
            "user_story_writing",
            "product_design",
            "product_review",
            "system_feature_analysis",
            "system_requirement_analysis",
            "document_generation",
            "pr_review",
            "pr_merge",
        }
        assert set(agent.skill_names) == expected

    def test_requirement_analysis(self):
        agent, store = self._make_agent()
        artifact = agent.execute_skill(
            "requirement_analysis",
            {
                "raw_requirements": "User login\nUser registration\nPerformance must be under 200ms",
            },
        )
        content = artifact.content
        assert len(content["functional_requirements"]) == 2
        assert len(content["non_functional_requirements"]) == 1

    def test_user_story_writing(self):
        agent, store = self._make_agent()
        # First create requirements
        agent.execute_skill(
            "requirement_analysis",
            {
                "raw_requirements": "User login\nUser registration",
            },
        )
        artifact = agent.execute_skill("user_story_writing", {})
        stories = artifact.content["user_stories"]
        assert len(stories) == 2
        assert all("acceptance_criteria" in s for s in stories)

    def test_product_design(self):
        agent, store = self._make_agent()
        agent.execute_skill("requirement_analysis", {"raw_requirements": "Feature A\nFeature B"})
        agent.execute_skill("user_story_writing", {})
        artifact = agent.execute_skill("product_design", {})
        assert "features" in artifact.content
        assert "user_flows" in artifact.content

    def test_product_review(self):
        agent, store = self._make_agent()
        agent.execute_skill("requirement_analysis", {"raw_requirements": "Feature A"})
        agent.execute_skill("user_story_writing", {})
        agent.execute_skill("product_design", {})
        artifact = agent.execute_skill("product_review", {})
        assert "approved" in artifact.content
        assert "coverage_percentage" in artifact.content

    def test_system_feature_analysis(self):
        agent, store = self._make_agent()
        artifact = agent.execute_skill(
            "system_feature_analysis",
            {
                "raw_requirements": "User login\nUser registration\nPerformance must be under 200ms\nSystem must be secure",
            },
        )
        content = artifact.content
        assert "external_features" in content
        assert "internal_dfx_features" in content
        assert "all_features" in content

        # Check that features have SF IDs
        all_features = content["all_features"]
        assert len(all_features) > 0
        for feature in all_features:
            assert "id" in feature
            assert feature["id"].startswith("SF-")
            assert "description" in feature
            assert "type" in feature
            assert feature["type"] in ["external", "internal_dfx"]

    def test_system_requirement_analysis(self):
        agent, store = self._make_agent()
        # First create system features
        agent.execute_skill(
            "system_feature_analysis",
            {
                "raw_requirements": "User login\nUser registration\nPerformance must be under 200ms",
            },
        )
        # Then generate system requirements
        artifact = agent.execute_skill("system_requirement_analysis", {})
        content = artifact.content

        assert "requirements" in content
        assert "coverage_summary" in content
        assert "traceability_matrix" in content

        # Check that requirements have SR IDs
        requirements = content["requirements"]
        assert len(requirements) > 0
        for req in requirements:
            assert "id" in req
            assert req["id"].startswith("SR-")
            assert "description" in req
            assert "source_sfs" in req
            assert len(req["source_sfs"]) > 0

        # Check coverage
        coverage = content["coverage_summary"]
        assert coverage["coverage_percentage"] > 0

    def test_document_generation(self):
        import tempfile
        from pathlib import Path

        agent, store = self._make_agent()

        # First create system features and requirements
        agent.execute_skill(
            "system_feature_analysis",
            {
                "raw_requirements": "User login\nPerformance must be under 200ms",
            },
        )
        agent.execute_skill("system_requirement_analysis", {})

        # Generate documents
        with tempfile.TemporaryDirectory() as tmpdir:
            artifact = agent.execute_skill("document_generation", {"output_dir": tmpdir})

            assert "generated_files" in artifact.content
            generated_files = artifact.content["generated_files"]

            # Check that both documents were generated
            assert len(generated_files) == 2

            # Check that files exist
            design_doc = Path(tmpdir) / "system-design.md"
            req_doc = Path(tmpdir) / "system-requirements.md"

            assert design_doc.exists()
            assert req_doc.exists()

            # Check basic content
            design_content = design_doc.read_text()
            assert "System Design Document" in design_content
            assert "SF-" in design_content

            req_content = req_doc.read_text()
            assert "System Requirements Document" in req_content
            assert "SR-" in req_content
