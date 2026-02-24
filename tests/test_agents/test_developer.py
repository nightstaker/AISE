"""Tests for the Developer agent and skills."""

from pathlib import Path

from aise.agents.architect import ArchitectAgent
from aise.agents.developer import DeveloperAgent
from aise.agents.product_manager import ProductManagerAgent
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus


class TestDeveloperAgent:
    def _setup_with_design(self):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)
        dev = DeveloperAgent(bus, store)

        pm.execute_skill("requirement_analysis", {"raw_requirements": "User login\nDashboard"})
        pm.execute_skill("user_story_writing", {})
        pm.execute_skill("product_design", {})
        arch.execute_skill("system_design", {})
        arch.execute_skill("api_design", {})
        arch.execute_skill("tech_stack_selection", {})

        return dev, store

    def test_has_all_skills(self):
        bus = MessageBus()
        store = ArtifactStore()
        agent = DeveloperAgent(bus, store)
        expected = {
            "deep_developer_workflow",
            "code_generation",
            "unit_test_writing",
            "code_review",
            "bug_fix",
            "tdd_session",
            "pr_review",
        }
        assert set(agent.skill_names) == expected

    def test_code_generation(self):
        dev, store = self._setup_with_design()
        artifact = dev.execute_skill("code_generation", {})
        assert "modules" in artifact.content
        assert artifact.content["total_files"] > 0

    def test_unit_test_writing(self):
        dev, store = self._setup_with_design()
        dev.execute_skill("code_generation", {})
        artifact = dev.execute_skill("unit_test_writing", {})
        assert "test_suites" in artifact.content
        assert artifact.content["total_test_cases"] > 0

    def test_code_review(self):
        dev, store = self._setup_with_design()
        dev.execute_skill("code_generation", {})
        dev.execute_skill("unit_test_writing", {})
        artifact = dev.execute_skill("code_review", {})
        assert "approved" in artifact.content
        assert "findings" in artifact.content

    def test_bug_fix(self):
        dev, store = self._setup_with_design()
        artifact = dev.execute_skill(
            "bug_fix",
            {
                "bug_reports": [{"id": "BUG-001", "description": "Login fails"}],
            },
        )
        assert artifact.content["total_bugs"] == 1

    def test_deep_developer_workflow_writes_source_tests_and_revision(self, tmp_path):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)
        dev = DeveloperAgent(bus, store)

        project_root = tmp_path / "project_0-dev"
        (project_root / "docs").mkdir(parents=True, exist_ok=True)
        pm.execute_skill(
            "deep_product_workflow",
            {
                "raw_requirements": "User login and chat",
                "output_dir": str(project_root / "docs"),
            },
            parameters={"project_root": str(project_root)},
        )
        arch.execute_skill(
            "deep_architecture_workflow",
            {"output_dir": "docs", "source_dir": "src"},
            parameters={"project_root": str(project_root)},
        )

        artifact = dev.execute_skill(
            "deep_developer_workflow",
            {"source_dir": "src", "tests_dir": "tests"},
            parameters={"project_root": str(project_root)},
        )

        assert artifact.content["workflow"] == "deep_developer_workflow"
        assert (Path(project_root) / "src").exists()
        assert not (Path(project_root) / "src" / "services").exists()
        assert (Path(project_root) / "tests" / "services").exists()
        assert (Path(project_root) / "tests" / "conftest.py").exists()

    def test_deep_developer_workflow_generates_generic_service_assets(self, tmp_path):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)
        dev = DeveloperAgent(bus, store)

        project_root = tmp_path / "project_0-snake"
        (project_root / "docs").mkdir(parents=True, exist_ok=True)
        pm.execute_skill(
            "deep_product_workflow",
            {
                "raw_requirements": "开发一个命令行贪吃蛇游戏，支持暂停、重开和pytest测试",
                "output_dir": str(project_root / "docs"),
            },
            parameters={"project_root": str(project_root)},
        )
        arch.execute_skill(
            "deep_architecture_workflow",
            {"output_dir": "docs", "source_dir": "src"},
            parameters={"project_root": str(project_root)},
        )

        dev.execute_skill(
            "deep_developer_workflow",
            {
                "source_dir": "src",
                "tests_dir": "tests",
                "raw_requirements": "开发一个命令行贪吃蛇游戏，支持暂停、重开和pytest测试",
            },
            parameters={"project_root": str(project_root)},
        )

        service_files = list((project_root / "src").glob("*/*.py"))
        test_files = list((project_root / "tests" / "services").glob("*/*.py"))
        assert service_files
        assert test_files
        assert not (project_root / "src" / "services").exists()
        assert (project_root / "tests" / "conftest.py").exists()

    def test_deep_developer_workflow_uses_generic_subsystem_pipeline_for_cpp_requirement(self, tmp_path):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)
        dev = DeveloperAgent(bus, store)

        project_root = tmp_path / "project_2-snake-cpp"
        (project_root / "docs").mkdir(parents=True, exist_ok=True)
        raw = "开发一个C++版本的贪吃蛇项目，要求可以编译和运行"
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
            {"output_dir": "docs", "source_dir": "src", "raw_requirements": raw},
            parameters={"project_root": str(project_root)},
        )

        dev.execute_skill(
            "deep_developer_workflow",
            {
                "source_dir": "src",
                "tests_dir": "tests",
                "raw_requirements": raw,
            },
            parameters={"project_root": str(project_root)},
        )

        assert (project_root / "src").exists()
        assert not (project_root / "src" / "services").exists()
        assert (project_root / "tests" / "services").exists()
        assert not (project_root / "CMakeLists.txt").exists()
