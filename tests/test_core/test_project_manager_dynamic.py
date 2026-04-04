"""Tests for AI-First dynamic workflow integration in ProjectManager."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aise.core.project_manager import ProjectManager


class TestRunProjectWorkflowDynamic:
    """Test that run_project_workflow prefers dynamic workflow."""

    def _make_pm(self) -> ProjectManager:
        with patch.object(ProjectManager, "_load_global_config", return_value=MagicMock()):
            pm = ProjectManager.__new__(ProjectManager)
            pm._projects = {}
            pm._project_counter = 0
            pm._projects_root = MagicMock()
            pm._global_config_path = MagicMock()
            pm._global_config = MagicMock()
        return pm

    def _make_project(self, *, has_dynamic: bool = True, dynamic_result: dict | None = None) -> MagicMock:
        project = MagicMock()
        project.project_name = "test_project"

        base_orchestrator = MagicMock()
        if has_dynamic:
            base_orchestrator.run_dynamic_workflow.return_value = dynamic_result or {
                "status": "completed",
                "step_results": [
                    {
                        "process": "deep_product_workflow",
                        "agent": "product_manager",
                        "status": "completed",
                        "artifact_id": "art_001",
                        "error": None,
                        "duration": 10.0,
                    },
                    {
                        "process": "deep_architecture_workflow",
                        "agent": "architect",
                        "status": "completed",
                        "artifact_id": "art_002",
                        "error": None,
                        "duration": 20.0,
                    },
                ],
                "artifact_ids": ["art_001", "art_002"],
                "plan": {
                    "goal": "Build a snake game",
                    "reasoning": "Selected product and architecture workflows",
                    "steps": [
                        {"process_id": "deep_product_workflow", "agent": "product_manager", "phase": "requirements"},
                        {"process_id": "deep_architecture_workflow", "agent": "architect", "phase": "design"},
                    ],
                },
                "replans": 0,
                "total_duration": 30.0,
            }

            # Mock agent with llm_client
            mock_agent = MagicMock()
            mock_agent.llm_client = MagicMock()
            base_orchestrator._agents = {"product_manager": mock_agent}
        else:
            del base_orchestrator.run_dynamic_workflow
            base_orchestrator._agents = {}

        # DeepOrchestrator wraps base orchestrator
        project.orchestrator = MagicMock()
        project.orchestrator.orchestrator = base_orchestrator

        return project

    def test_prefers_dynamic_workflow(self):
        pm = self._make_pm()
        project = self._make_project(has_dynamic=True)
        pm._projects["p1"] = project

        result = pm.run_project_workflow("p1", {"raw_requirements": "Build a snake game"})

        # Should have called run_dynamic_workflow
        base = project.orchestrator.orchestrator
        base.run_dynamic_workflow.assert_called_once()

        # Should return normalized results
        assert len(result) == 2
        assert result[0]["phase"] == "requirements"
        assert result[1]["phase"] == "design"

    def test_dynamic_stores_plan_on_project(self):
        pm = self._make_pm()
        project = self._make_project(has_dynamic=True)
        pm._projects["p1"] = project

        pm.run_project_workflow("p1", {"raw_requirements": "test"})

        assert hasattr(project, "_dynamic_plan")
        assert project._dynamic_plan["reasoning"] == "Selected product and architecture workflows"

    def test_fallback_on_dynamic_failure(self):
        pm = self._make_pm()
        project = self._make_project(has_dynamic=True)
        pm._projects["p1"] = project

        base = project.orchestrator.orchestrator
        base.run_dynamic_workflow.side_effect = RuntimeError("LLM planning failed")

        # Should fall back to run_workflow (DeepOrchestrator)
        project.orchestrator.run_workflow.return_value = {
            "messages": [],
            "phase_results": {"requirements_product_manager": {"status": "completed"}},
        }

        pm.run_project_workflow("p1", {"raw_requirements": "test"})
        project.orchestrator.run_workflow.assert_called_once()

    def test_fallback_on_empty_dynamic_result(self):
        pm = self._make_pm()
        project = self._make_project(
            has_dynamic=True,
            dynamic_result={"status": "completed", "step_results": [], "plan": {}, "artifact_ids": []},
        )
        pm._projects["p1"] = project

        project.orchestrator.run_workflow.return_value = {
            "messages": [],
            "phase_results": {"requirements_product_manager": {"status": "completed"}},
        }

        pm.run_project_workflow("p1", {"raw_requirements": "test"})
        # Dynamic returned empty → should try run_workflow fallback
        project.orchestrator.run_workflow.assert_called_once()

    def test_no_dynamic_uses_deep_orchestrator(self):
        pm = self._make_pm()
        project = self._make_project(has_dynamic=False)
        pm._projects["p1"] = project

        project.orchestrator.run_workflow.return_value = {
            "messages": [],
            "phase_results": {"requirements_product_manager": {"status": "completed"}},
        }

        pm.run_project_workflow("p1", {"raw_requirements": "test"})
        project.orchestrator.run_workflow.assert_called_once()

    def test_project_not_found_raises(self):
        pm = self._make_pm()
        with pytest.raises(ValueError, match="not found"):
            pm.run_project_workflow("nonexistent", {})


class TestNormalizeDynamicResult:
    """Test _normalize_dynamic_workflow_result."""

    def _make_pm(self) -> ProjectManager:
        with patch.object(ProjectManager, "_load_global_config", return_value=MagicMock()):
            pm = ProjectManager.__new__(ProjectManager)
        return pm

    def test_groups_by_phase(self):
        pm = self._make_pm()
        result = pm._normalize_dynamic_workflow_result(
            {
                "step_results": [
                    {"process": "requirement_analysis", "agent": "product_manager", "status": "completed"},
                    {"process": "deep_architecture_workflow", "agent": "architect", "status": "completed"},
                ],
                "plan": {
                    "steps": [
                        {"process_id": "requirement_analysis", "phase": "requirements"},
                        {"process_id": "deep_architecture_workflow", "phase": "design"},
                    ]
                },
            }
        )
        assert len(result) == 2
        assert result[0]["phase"] == "requirements"
        assert result[1]["phase"] == "design"

    def test_infers_phase_from_name(self):
        pm = self._make_pm()
        result = pm._normalize_dynamic_workflow_result(
            {
                "step_results": [
                    {"process": "deep_developer_workflow", "agent": "developer", "status": "completed"},
                ],
                "plan": {"steps": []},  # No plan steps to match
            }
        )
        # Without plan steps, process_id is used directly as phase name
        assert result[0]["phase"] == "deep_developer_workflow"

    def test_handles_failed_steps(self):
        pm = self._make_pm()
        result = pm._normalize_dynamic_workflow_result(
            {
                "step_results": [
                    {"process": "test_automation", "agent": "qa_engineer", "status": "failed", "error": "timeout"},
                ],
                "plan": {"steps": [{"process_id": "test_automation", "phase": "testing"}]},
            }
        )
        assert result[0]["status"] == "failed"

    def test_empty_result(self):
        pm = self._make_pm()
        assert pm._normalize_dynamic_workflow_result({}) == []
        assert pm._normalize_dynamic_workflow_result({"step_results": [], "plan": {}}) == []

    def test_non_dict_returns_empty(self):
        pm = self._make_pm()
        assert pm._normalize_dynamic_workflow_result("not a dict") == []


class TestGetPlannerLlmClient:
    """Test _get_planner_llm_client."""

    def test_extracts_from_agents(self):
        orchestrator = MagicMock()
        agent = MagicMock()
        agent.llm_client = MagicMock()
        orchestrator._agents = {"pm": agent}

        client = ProjectManager._get_planner_llm_client(orchestrator)
        assert client is agent.llm_client

    def test_returns_none_when_no_agents(self):
        orchestrator = MagicMock()
        orchestrator._agents = {}
        assert ProjectManager._get_planner_llm_client(orchestrator) is None

    def test_returns_none_when_no_llm_client(self):
        orchestrator = MagicMock()
        agent = MagicMock(spec=[])  # No llm_client attribute
        orchestrator._agents = {"pm": agent}
        assert ProjectManager._get_planner_llm_client(orchestrator) is None


class TestInferPhaseFromProcess:
    """Test _infer_phase_from_process."""

    @pytest.mark.parametrize(
        "process_id,expected",
        [
            # Without plan steps, process_id is returned directly
            ("requirement_analysis", "requirement_analysis"),
            ("deep_product_workflow", "deep_product_workflow"),
            ("deep_architecture_workflow", "deep_architecture_workflow"),
            ("api_design", "api_design"),
            ("deep_developer_workflow", "deep_developer_workflow"),
            ("code_generation", "code_generation"),
            ("tdd_development", "tdd_development"),
            ("test_automation", "test_automation"),
            ("qa_review", "qa_review"),
            ("unknown_process", "unknown_process"),
        ],
    )
    def test_infer(self, process_id: str, expected: str):
        plan: dict[str, Any] = {"steps": []}
        assert ProjectManager._infer_phase_from_process(process_id, plan) == expected

    def test_prefers_plan_step_phase(self):
        plan = {"steps": [{"process_id": "custom_process", "phase": "custom_phase"}]}
        assert ProjectManager._infer_phase_from_process("custom_process", plan) == "custom_phase"
