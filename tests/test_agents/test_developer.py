"""Tests for the Developer agent and skills."""

from pathlib import Path

from aise.agents.architect import ArchitectAgent
from aise.agents.developer import DeveloperAgent
from aise.agents.product_manager import ProductManagerAgent
from aise.core.artifact import ArtifactStore
from aise.core.message import MessageBus
from aise.core.skill import SkillContext


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

    def test_deep_developer_workflow_writes_source_tests_and_revision(self, tmp_path, monkeypatch):
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

        skill = dev.get_skill("deep_developer_workflow")
        assert skill is not None
        monkeypatch.setattr(
            skill,
            "_generate_python_sr_group_tests_with_llm",
            lambda **kwargs: {
                str(plan.get("fn_id", "")): {
                    "module_name": str(plan.get("module_name", "")),
                    "test_content": (
                        f"from src.{str(kwargs.get('subsystem_slug', 'subsystem'))}."
                        f"{str(plan.get('module_name', 'module'))} import "
                        f"implement_{str(plan.get('module_name', 'module'))}\n\n"
                        f"def test_{str(plan.get('module_name', 'module'))}_ok():\n"
                        f"    assert implement_{str(plan.get('module_name', 'module'))}({{}})['status'] == 'ok'\n\n"
                        f"def test_{str(plan.get('module_name', 'module'))}_meta():\n"
                        "    assert isinstance("
                        f"implement_{str(plan.get('module_name', 'module'))}({{}})['meta'], dict)\n"
                    ),
                }
                for plan in kwargs.get("plans", [])
            },
        )
        monkeypatch.setattr(
            skill,
            "_generate_python_sr_group_code_with_llm",
            lambda **kwargs: {
                str(plan.get("fn_id", "")): {
                    "module_name": str(plan.get("module_name", "")),
                    "code_content": (
                        f"def implement_{str(plan.get('module_name', 'module'))}(input_data: dict | None = None):\n"
                        "    return {'status': 'ok', 'data': {}, 'errors': [], 'meta': {}}\n"
                    ),
                }
                for plan in kwargs.get("plans", [])
            },
        )

        artifact = dev.execute_skill(
            "deep_developer_workflow",
            {"source_dir": "src", "tests_dir": "tests"},
            parameters={"project_root": str(project_root)},
        )

        assert artifact.content["workflow"] == "deep_developer_workflow"
        assert (Path(project_root) / "src").exists()
        assert not (Path(project_root) / "src" / "services").exists()
        assert (Path(project_root) / "tests").exists()
        assert not (Path(project_root) / "tests" / "services").exists()
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
        test_files = list((project_root / "tests").glob("*/*.py"))
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
        assert (project_root / "tests").exists()
        assert not (project_root / "CMakeLists.txt").exists()

    def test_deep_developer_workflow_writes_step1_subsystem_summary_before_step2_runs(self, tmp_path, monkeypatch):
        class _Recorder:
            def __init__(self):
                self.attempts = {}
                self.outputs = {}

            def record_task_attempt_start(self, **kwargs):
                task_key = str(kwargs.get("task_key", ""))
                attempt_no = int(self.attempts.get(task_key, 0)) + 1
                self.attempts[task_key] = attempt_no
                return {"attempt": {"attempt_no": attempt_no}}

            def record_task_attempt_output(self, **kwargs):
                task_key = str(kwargs.get("task_key", ""))
                out = kwargs.get("outputs", {})
                current = self.outputs.get(task_key, {})
                if isinstance(current, dict) and isinstance(out, dict):
                    self.outputs[task_key] = {**current, **out}

            def record_task_attempt_end(self, **kwargs):
                return {"ok": True}

        bus = MessageBus()
        store = ArtifactStore()
        dev = DeveloperAgent(bus, store)
        recorder = _Recorder()
        project_root = tmp_path / "project_0-dev-step1-summary"

        skill = dev.get_skill("deep_developer_workflow")
        assert skill is not None
        original = skill._process_single_subsystem_batch_rounds
        checked = {"ok": False}

        def _spy_process_single_subsystem_batch_rounds(*args, **kwargs):
            step1 = recorder.outputs.get("developer.deep_developer_workflow.step1", {})
            summary = step1.get("workflow_summary", {}) if isinstance(step1, dict) else {}
            subsystems = summary.get("subsystems", []) if isinstance(summary, dict) else []
            assert isinstance(subsystems, list)
            assert len(subsystems) > 0
            first_sub = subsystems[0] if isinstance(subsystems[0], dict) else {}
            srs = first_sub.get("srs", []) if isinstance(first_sub, dict) else []
            assert isinstance(srs, list)
            assert len(srs) > 0
            assert "sr_id" in (srs[0] if isinstance(srs[0], dict) else {})
            checked["ok"] = True
            return original(*args, **kwargs)

        monkeypatch.setattr(skill, "_process_single_subsystem_batch_rounds", _spy_process_single_subsystem_batch_rounds)
        monkeypatch.setattr(
            skill,
            "_generate_python_sr_group_tests_with_llm",
            lambda **kwargs: {
                str(plan.get("fn_id", "")): {
                    "module_name": str(plan.get("module_name", "")),
                    "test_content": (
                        f"from src.subsystem.{str(plan.get('module_name', 'module'))} import "
                        f"implement_{str(plan.get('module_name', 'module'))}\n\n"
                        f"def test_{str(plan.get('module_name', 'module'))}_ok():\n"
                        f"    assert implement_{str(plan.get('module_name', 'module'))}({{}})['status'] == 'ok'\n\n"
                        f"def test_{str(plan.get('module_name', 'module'))}_meta():\n"
                        "    assert isinstance("
                        f"implement_{str(plan.get('module_name', 'module'))}({{}})['meta'], dict)\n"
                    ),
                }
                for plan in kwargs.get("plans", [])
            },
        )
        monkeypatch.setattr(
            skill,
            "_generate_python_sr_group_code_with_llm",
            lambda **kwargs: {
                str(plan.get("fn_id", "")): {
                    "module_name": str(plan.get("module_name", "")),
                    "code_content": (
                        f"def implement_{str(plan.get('module_name', 'module'))}(input_data: dict | None = None):\n"
                        "    return {'status': 'ok', 'data': {}, 'errors': [], 'meta': {}}\n"
                    ),
                }
                for plan in kwargs.get("plans", [])
            },
        )

        artifact = dev.execute_skill(
            "deep_developer_workflow",
            {"source_dir": "src", "tests_dir": "tests"},
            parameters={
                "project_root": str(project_root),
                "task_memory_recorder": recorder,
                "phase_key": "implementation",
            },
        )

        assert artifact.content["workflow"] == "deep_developer_workflow"
        assert checked["ok"] is True

    def test_deep_developer_workflow_retries_only_current_sr_group_once(self, monkeypatch):
        bus = MessageBus()
        store = ArtifactStore()
        dev = DeveloperAgent(bus, store)
        skill = dev.get_skill("deep_developer_workflow")
        assert skill is not None

        calls = []

        def _fake_group_round(**kwargs):
            calls.append((kwargs["sr_key"], kwargs["round_index"]))
            if len(calls) == 1:
                raise RuntimeError("first attempt failed")
            return {"sr_group": kwargs["sr_key"], "fn_count": 1, "results": []}

        monkeypatch.setattr(skill, "_develop_single_sr_group_round", _fake_group_round)
        ctx = SkillContext(artifact_store=store)

        result = skill._develop_single_sr_group_round_with_retry(
            context=ctx,
            subsystem_slug="user_service",
            sr_key="SR-001",
            plans=[{"fn_id": "FN-SR-001-01"}],
            round_index=1,
            max_attempts=2,
        )

        assert result["sr_group"] == "SR-001"
        assert calls == [("SR-001", 1), ("SR-001", 1)]

    def test_deep_developer_workflow_develops_sr_group_tests_first_with_subsystem_context(self, tmp_path, monkeypatch):
        bus = MessageBus()
        store = ArtifactStore()
        dev = DeveloperAgent(bus, store)
        skill = dev.get_skill("deep_developer_workflow")
        assert skill is not None

        code_a = tmp_path / "a.py"
        code_b = tmp_path / "b.py"
        test_a = tmp_path / "test_a.py"
        test_b = tmp_path / "test_b.py"
        for p in (code_a, code_b, test_a, test_b):
            p.write_text("# placeholder\n", encoding="utf-8")

        calls = []
        prompt_snapshots = []
        project_root = tmp_path / "project_ctx"
        (project_root / "docs").mkdir(parents=True, exist_ok=True)
        (project_root / "docs" / "subsystem-order_service-design.md").write_text(
            "# subsystem-order_service-design.md\n\n## Module Class Designs\n\n```mermaid\nclassDiagram\n```\n",
            encoding="utf-8",
        )
        src_dir = project_root / "src" / "order_service"
        tests_dir = project_root / "tests" / "order_service"
        src_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)

        def _fake_run_llm_json_segment(**kwargs):
            calls.append(str(kwargs.get("purpose", "")))
            prompt_snapshots.append(str(kwargs.get("user_prompt", "")))
            purpose = str(kwargs.get("purpose", ""))
            if "sr_group_test_generation" in purpose:
                return {
                    "items": [
                        {
                            "fn_id": "FN-SR-001-01",
                            "module_name": "order_create",
                            "test_content": (
                                "from src.order_service.order_create import implement_order_create\n\n"
                                "def test_order_create_ok():\n"
                                "    assert implement_order_create({})['status'] == 'ok'\n\n"
                                "def test_order_create_meta():\n"
                                "    assert isinstance(implement_order_create({})['meta'], dict)\n"
                            ),
                        },
                        {
                            "fn_id": "FN-SR-001-02",
                            "module_name": "order_query",
                            "test_content": (
                                "from src.order_service.order_query import implement_order_query\n\n"
                                "def test_order_query_ok():\n"
                                "    assert implement_order_query({})['status'] == 'ok'\n\n"
                                "def test_order_query_meta():\n"
                                "    assert isinstance(implement_order_query({})['meta'], dict)\n"
                            ),
                        },
                    ]
                }
            return {
                "items": [
                    {
                        "fn_id": "FN-SR-001-01",
                        "module_name": "order_create",
                        "code_content": (
                            "def implement_order_create(input_data: dict | None = None):\n"
                            "    return {'status': 'ok', 'data': {}, 'errors': [], 'meta': {}}\n"
                        ),
                    },
                    {
                        "fn_id": "FN-SR-001-02",
                        "module_name": "order_query",
                        "code_content": (
                            "def implement_order_query(input_data: dict | None = None):\n"
                            "    return {'status': 'ok', 'data': {}, 'errors': [], 'meta': {}}\n"
                        ),
                    },
                ]
            }

        monkeypatch.setattr(skill, "_run_llm_json_segment", _fake_run_llm_json_segment)
        ctx = SkillContext(
            artifact_store=store,
            llm_client=object(),
            parameters={"project_root": str(project_root)},
        )

        plans = [
            {
                "fn_id": "FN-SR-001-01",
                "fn_description": "create order",
                "fn_spec": "create",
                "module_name": "order_create",
                "code_path": src_dir / "order_create.py",
                "test_path": tests_dir / "test_order_service_order_create.py",
                "comments": [],
            },
            {
                "fn_id": "FN-SR-001-02",
                "fn_description": "query order",
                "fn_spec": "query",
                "module_name": "order_query",
                "code_path": src_dir / "order_query.py",
                "test_path": tests_dir / "test_order_service_order_query.py",
                "comments": [],
            },
        ]

        result = skill._develop_single_sr_group_round(
            context=ctx,
            subsystem_slug="order_service",
            sr_key="SR-001",
            plans=plans,
            round_index=1,
        )

        assert result["sr_group"] == "SR-001"
        assert len(calls) == 2
        assert "sr_group_test_generation" in calls[0]
        assert "sr_group_code_generation" in calls[1]
        assert "fn_code_generation" not in calls[0]
        assert any("subsystem_architecture_design_doc" in prompt for prompt in prompt_snapshots)
        assert any("existing_source_code" in prompt for prompt in prompt_snapshots)
        assert any("existing_test_code" in prompt for prompt in prompt_snapshots)
        assert "generated_tests_for_current_sr" in prompt_snapshots[1]
        assert "implement_order_create" in (src_dir / "order_create.py").read_text(encoding="utf-8")
        assert "implement_order_query" in (src_dir / "order_query.py").read_text(encoding="utf-8")

    def test_deep_developer_workflow_preserves_class_based_module_contract(self, tmp_path, monkeypatch):
        bus = MessageBus()
        store = ArtifactStore()
        dev = DeveloperAgent(bus, store)
        skill = dev.get_skill("deep_developer_workflow")
        assert skill is not None

        project_root = tmp_path / "project_class_contract"
        (project_root / "docs").mkdir(parents=True, exist_ok=True)
        (project_root / "docs" / "subsystem-syncbridge-design.md").write_text(
            "# subsystem-syncbridge-design.md\n", encoding="utf-8"
        )
        src_dir = project_root / "src" / "syncbridge"
        tests_dir = project_root / "tests" / "syncbridge"
        src_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)
        (src_dir / "__init__.py").write_text("", encoding="utf-8")
        (src_dir / "syncorchestrator.py").write_text(
            (
                "class SyncOrchestrator:\n"
                "    def run(self, payload: dict | None = None) -> dict:\n"
                "        raise NotImplementedError\n"
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(
            skill,
            "_generate_python_sr_group_tests_with_llm",
            lambda **kwargs: {
                "FN-SR-003-01": {
                    "module_name": "syncorchestrator",
                    "test_content": (
                        "from src.syncbridge.syncorchestrator import SyncOrchestrator\n\n"
                        "def test_sync_orchestrator_returns_dict():\n"
                        "    result = SyncOrchestrator().run({})\n"
                        "    assert isinstance(result, dict)\n\n"
                        "def test_sync_orchestrator_has_status():\n"
                        "    result = SyncOrchestrator().run({})\n"
                        "    assert result['status'] == 'ok'\n"
                    ),
                }
            },
        )
        monkeypatch.setattr(
            skill,
            "_generate_python_sr_group_code_with_llm",
            lambda **kwargs: {
                "FN-SR-003-01": {
                    "module_name": "syncorchestrator",
                    "code_content": (
                        "class SyncOrchestrator:\n"
                        "    def run(self, payload: dict | None = None) -> dict:\n"
                        "        data = payload or {}\n"
                        "        return {\n"
                        "            'status': 'ok',\n"
                        "            'data': data,\n"
                        "            'errors': [],\n"
                        "            'meta': {'module': 'syncorchestrator'},\n"
                        "        }\n"
                    ),
                }
            },
        )

        ctx = SkillContext(artifact_store=store, llm_client=object(), parameters={"project_root": str(project_root)})
        plans = [
            {
                "fn_id": "FN-SR-003-01",
                "fn_description": "coordinate sync flow",
                "fn_spec": "orchestrate sync",
                "module_name": "syncorchestrator",
                "code_path": src_dir / "syncorchestrator.py",
                "test_path": tests_dir / "test_syncbridge_syncorchestrator.py",
                "comments": [],
            }
        ]

        result = skill._develop_single_sr_group_round(
            context=ctx,
            subsystem_slug="syncbridge",
            sr_key="SR-003",
            plans=plans,
            round_index=1,
        )

        assert result["sr_group"] == "SR-003"
        code_text = (src_dir / "syncorchestrator.py").read_text(encoding="utf-8")
        test_text = (tests_dir / "test_syncbridge_syncorchestrator.py").read_text(encoding="utf-8")
        assert "class SyncOrchestrator" in code_text
        assert "def implement_syncorchestrator" not in code_text
        assert "from src.syncbridge.syncorchestrator import SyncOrchestrator" in test_text

    def test_deep_developer_workflow_sr_group_retry_failure_continues_with_warning(self, monkeypatch):
        """SR group failure should warn and continue, not raise."""
        bus = MessageBus()
        store = ArtifactStore()
        dev = DeveloperAgent(bus, store)
        skill = dev.get_skill("deep_developer_workflow")
        assert skill is not None

        calls = []

        def _always_fail(**kwargs):
            calls.append((kwargs["sr_key"], kwargs["round_index"]))
            raise RuntimeError("still failing")

        monkeypatch.setattr(skill, "_develop_single_sr_group_round", _always_fail)
        ctx = SkillContext(artifact_store=store)

        # Should NOT raise — logs warning and continues
        skill._develop_single_sr_group_round_with_retry(
            context=ctx,
            subsystem_slug="user_service",
            sr_key="SR-002",
            plans=[{"fn_id": "FN-SR-002-01"}],
            round_index=2,
            max_attempts=2,
        )
        assert calls == [("SR-002", 2), ("SR-002", 2)]

    def test_deep_developer_workflow_uses_configured_sr_group_retry_attempts(self, tmp_path, monkeypatch):
        bus = MessageBus()
        store = ArtifactStore()
        pm = ProductManagerAgent(bus, store)
        arch = ArchitectAgent(bus, store)
        dev = DeveloperAgent(bus, store)
        skill = dev.get_skill("deep_developer_workflow")
        assert skill is not None

        project_root = tmp_path / "project_0-retry-config"
        (project_root / "docs").mkdir(parents=True, exist_ok=True)
        pm.execute_skill(
            "deep_product_workflow",
            {
                "raw_requirements": "User login and chat",
                "output_dir": str(project_root / "docs"),
                "review_rounds": 1,
            },
            parameters={"project_root": str(project_root)},
        )
        arch.execute_skill(
            "deep_architecture_workflow",
            {
                "output_dir": str(project_root / "docs"),
                "review_rounds": 1,
            },
            parameters={"project_root": str(project_root)},
        )

        original = skill._process_single_subsystem_batch_rounds
        seen_retry_attempts: list[int] = []

        def _spy_process_single_subsystem_batch_rounds(*args, **kwargs):
            seen_retry_attempts.append(int(kwargs.get("sr_group_retry_attempts", 0) or 0))
            return original(*args, **kwargs)

        monkeypatch.setattr(skill, "_process_single_subsystem_batch_rounds", _spy_process_single_subsystem_batch_rounds)

        artifact = dev.execute_skill(
            "deep_developer_workflow",
            {
                "source_dir": "src",
                "tests_dir": "tests",
                "_developer_sr_task_retry_attempts": 1,
                "subsystem_review_rounds": 1,
            },
            parameters={"project_root": str(project_root)},
        )

        assert artifact.content["workflow"] == "deep_developer_workflow"
        assert seen_retry_attempts
        assert set(seen_retry_attempts) == {1}

    def test_run_llm_json_segment_logs_warning_per_invalid_attempt(self, monkeypatch, caplog):
        bus = MessageBus()
        store = ArtifactStore()
        dev = DeveloperAgent(bus, store)
        skill = dev.get_skill("deep_developer_workflow")
        assert skill is not None

        calls = {"count": 0}

        def _fake_run_llm_json(**kwargs):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("not json")
            return {"code_content": "def bad("}

        monkeypatch.setattr(skill, "_run_llm_json", _fake_run_llm_json)
        ctx = SkillContext(artifact_store=store, llm_client=object())

        with caplog.at_level("WARNING"):
            try:
                skill._run_llm_json_segment(
                    context=ctx,
                    purpose="subagent:programmer step:test_segment",
                    system_prompt="Return JSON",
                    user_prompt="payload",
                    required_keys=["code_content"],
                    module_name="demo_mod",
                    subsystem_slug="demo_subsystem",
                    max_attempts=2,
                )
                assert False, "expected RuntimeError"
            except RuntimeError:
                pass

        warning_messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert len(warning_messages) >= 2
        assert any("Developer LLM segment attempt failed" in msg for msg in warning_messages)
        assert any("Developer LLM segment invalid payload" in msg for msg in warning_messages)

    def test_develop_single_sr_group_round_logs_warning_on_invalid_pytest_content(self, tmp_path, monkeypatch, caplog):
        bus = MessageBus()
        store = ArtifactStore()
        dev = DeveloperAgent(bus, store)
        skill = dev.get_skill("deep_developer_workflow")
        assert skill is not None

        project_root = tmp_path / "project_invalid_pytest"
        docs_dir = project_root / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        (docs_dir / "subsystem-syncbridge-design.md").write_text("# subsystem-syncbridge-design.md\n", encoding="utf-8")
        src_dir = project_root / "src" / "syncbridge"
        tests_dir = project_root / "tests" / "syncbridge"
        src_dir.mkdir(parents=True, exist_ok=True)
        tests_dir.mkdir(parents=True, exist_ok=True)

        monkeypatch.setattr(
            skill,
            "_generate_python_sr_group_tests_with_llm",
            lambda **kwargs: {
                "FN-SR-003-01": {
                    "module_name": "syncorchestrator",
                    "test_content": "def test_only_one():\n    assert True\n",
                }
            },
        )
        monkeypatch.setattr(
            skill,
            "_generate_python_sr_group_code_with_llm",
            lambda **kwargs: {},
        )

        ctx = SkillContext(artifact_store=store, llm_client=object(), parameters={"project_root": str(project_root)})
        plans = [
            {
                "fn_id": "FN-SR-003-01",
                "fn_description": "sync orchestrator flow",
                "fn_spec": "sync flow",
                "module_name": "syncorchestrator",
                "code_path": src_dir / "syncorchestrator.py",
                "test_path": tests_dir / "test_syncbridge_syncorchestrator.py",
                "comments": [],
            }
        ]

        with caplog.at_level("WARNING"):
            try:
                skill._develop_single_sr_group_round(
                    context=ctx,
                    subsystem_slug="syncbridge",
                    sr_key="SR-003",
                    plans=plans,
                    round_index=1,
                )
                assert False, "expected RuntimeError"
            except RuntimeError as exc:
                assert "Invalid LLM-generated pytest content" in str(exc)

        warning_messages = [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]
        assert any("Developer SR generation invalid content: kind=pytest" in msg for msg in warning_messages)
        assert any("subsystem=syncbridge" in msg for msg in warning_messages)
        assert any("sr_group=SR-003" in msg for msg in warning_messages)
        assert any("fn_id=FN-SR-003-01" in msg for msg in warning_messages)
