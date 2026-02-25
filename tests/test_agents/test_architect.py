"""Tests for the Architect agent and skills."""

from pathlib import Path

from aise.agents.architect import ArchitectAgent
from aise.agents.product_manager import ProductManagerAgent
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus


class TestArchitectAgent:
    def _setup_with_requirements(self):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)

        pm.execute_skill("requirement_analysis", {"raw_requirements": "User auth\nData export"})
        pm.execute_skill("user_story_writing", {})
        pm.execute_skill("product_design", {})

        return arch, store

    def test_has_all_skills(self):
        bus = MessageBus()
        store = ArtifactStore()
        agent = ArchitectAgent(bus, store)
        expected = {
            "deep_architecture_workflow",
            "system_design",
            "api_design",
            "architecture_review",
            "tech_stack_selection",
            "architecture_requirement_analysis",
            "functional_design",
            "status_tracking",
            "architecture_document_generation",
            "pr_review",
        }
        print(agent.skill_names)
        assert set(agent.skill_names) == expected

    def test_system_design(self):
        arch, store = self._setup_with_requirements()
        artifact = arch.execute_skill("system_design", {})
        assert "components" in artifact.content
        assert "data_flows" in artifact.content

    def test_api_design(self):
        arch, store = self._setup_with_requirements()
        arch.execute_skill("system_design", {})
        artifact = arch.execute_skill("api_design", {})
        assert "endpoints" in artifact.content
        assert "schemas" in artifact.content

    def test_tech_stack_selection(self):
        arch, store = self._setup_with_requirements()
        arch.execute_skill("system_design", {})
        artifact = arch.execute_skill("tech_stack_selection", {})
        assert "backend" in artifact.content
        assert "database" in artifact.content

    def test_architecture_review(self):
        arch, store = self._setup_with_requirements()
        arch.execute_skill("system_design", {})
        arch.execute_skill("api_design", {})
        artifact = arch.execute_skill("architecture_review", {})
        assert "approved" in artifact.content
        assert "checks" in artifact.content

    def test_run_full_architecture_workflow_generates_system_architecture_doc(self, tmp_path):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)

        raw = "User auth\nData export\nLatency under 200ms"
        pm.execute_skill("requirement_analysis", {"raw_requirements": raw})
        pm.execute_skill("system_feature_analysis", {"raw_requirements": raw})
        pm.execute_skill("system_requirement_analysis", {})
        pm.execute_skill("user_story_writing", {})
        pm.execute_skill("product_design", {})

        project_root = tmp_path / "project_0-demo"
        docs_dir = project_root / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)

        outputs = arch.run_full_architecture_workflow(
            project_name="Demo",
            parameters={"project_root": str(project_root)},
        )

        assert "deep_architecture_workflow" in outputs
        assert (Path(project_root) / "docs" / "system-architecture.md").exists()

    def test_deep_architecture_workflow_writes_docs_and_source_scaffold(self, tmp_path):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)

        raw = "User auth\nData export\nLatency under 200ms"
        pm.execute_skill(
            "deep_product_workflow",
            {
                "raw_requirements": raw,
                "output_dir": str(tmp_path / "project_0-demo" / "docs"),
            },
            parameters={"project_root": str(tmp_path / "project_0-demo")},
        )

        artifact = arch.execute_skill(
            "deep_architecture_workflow",
            {"output_dir": "docs", "source_dir": "src"},
            parameters={"project_root": str(tmp_path / "project_0-demo")},
        )

        assert artifact.content["workflow"] == "deep_architecture_workflow"
        assert (tmp_path / "project_0-demo" / "docs" / "system-architecture.md").exists()
        assert (tmp_path / "project_0-demo" / "src" / "main.py").exists()
        subsystem_design_docs = sorted((tmp_path / "project_0-demo" / "docs").glob("subsystem-*-design.md"))
        assert subsystem_design_docs
        assert not list((tmp_path / "project_0-demo" / "docs").glob("*-detail-design.md"))
        detail_doc_text = subsystem_design_docs[0].read_text(encoding="utf-8")
        assert "## Logical Architecture Views" in detail_doc_text
        assert "## Module Class Designs" in detail_doc_text
        assert "```mermaid" in detail_doc_text
        assert "classDiagram" in detail_doc_text
        subsystem_root = tmp_path / "project_0-demo" / "src"
        module_files = [p for p in subsystem_root.glob("*/*.py") if p.name != "__init__.py"]
        assert module_files
        assert all(p.name.isascii() for p in subsystem_root.glob("*/*.py"))
        sample_module = module_files[0].read_text(encoding="utf-8")
        assert "class " in sample_module
        assert "import" in sample_module
        assert list(subsystem_root.glob("*/__init__.py"))
        assert not list(subsystem_root.glob("*/schemas.py"))
        assert not list(subsystem_root.glob("*/service.py"))
        assert not list(subsystem_root.glob("*/api.py"))

    def test_deep_architecture_workflow_generates_generic_subsystem_names(self, tmp_path):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)

        raw = "开发命令行贪吃蛇，支持开始暂停结束、碰撞判定、加分、速度提升与结算重开"
        project_root = tmp_path / "project_0-snake"
        pm.execute_skill(
            "deep_product_workflow",
            {
                "raw_requirements": raw,
                "output_dir": str(project_root / "docs"),
            },
            parameters={"project_root": str(project_root)},
        )

        arch.execute_skill(
            "deep_architecture_workflow",
            {"output_dir": "docs", "source_dir": "src"},
            parameters={"project_root": str(project_root)},
        )

        architecture_doc = (project_root / "docs" / "system-architecture.md").read_text(encoding="utf-8")
        assert "core_domain" not in architecture_doc
        assert "integration_service" not in architecture_doc
