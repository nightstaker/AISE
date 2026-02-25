from __future__ import annotations

import json

import pytest

from aise.runtime.agents import MasterAgent
from aise.runtime.memory import InMemoryMemoryManager
from aise.runtime.registry import WorkerRegistry
from aise.runtime.runtime import AgentRuntime


class FakePlanningLLM:
    """Test-only planner LLM that returns structured planning JSON."""

    model = "fake-planning-llm"

    def complete(self, prompt: str, **kwargs) -> str:
        text = str(prompt).lower()
        runtime_like = any(k in text for k in ["runtime", "架构", "设计"])
        if runtime_like:
            return json.dumps(
                {
                    "selected_process_id": "runtime_design_standard",
                    "process_match_score": 0.99,
                    "task_plan": {
                        "task_name": "planned-by-fake-llm",
                        "tasks": [
                            {
                                "id": "req_analysis",
                                "name": "Requirement Analysis",
                                "assigned_agent_type": "generic_worker",
                                "capability_hints": ["analyze", "requirement"],
                                "input_data": {"prompt": "x"},
                            },
                            {
                                "id": "architecture_design",
                                "name": "Architecture Design",
                                "assigned_agent_type": "generic_worker",
                                "dependencies": ["req_analysis"],
                                "capability_hints": ["design", "architecture", "document"],
                                "input_data": {"prompt": "x"},
                            },
                            {
                                "id": "document_finalize",
                                "name": "Finalize Doc",
                                "assigned_agent_type": "generic_worker",
                                "dependencies": ["architecture_design"],
                                "capability_hints": ["summarize", "report"],
                                "input_data": {"prompt": "x"},
                            },
                        ],
                    },
                },
                ensure_ascii=False,
            )
        return json.dumps(
            {
                "selected_process_id": None,
                "task_plan": {
                    "task_name": "generic-plan",
                    "tasks": [
                        {
                            "id": "t1",
                            "name": "Task 1",
                            "assigned_agent_type": "generic_worker",
                            "capability_hints": ["analyze"],
                            "input_data": {"prompt": "x"},
                        },
                        {
                            "id": "t2",
                            "name": "Task 2",
                            "assigned_agent_type": "generic_worker",
                            "dependencies": ["t1"],
                            "capability_hints": ["summarize"],
                            "input_data": {"prompt": "x"},
                        },
                    ],
                },
            }
        )


@pytest.fixture
def fake_planning_llm() -> FakePlanningLLM:
    return FakePlanningLLM()


@pytest.fixture
def runtime_factory(fake_planning_llm):
    def _factory(**kwargs):
        return AgentRuntime(llm_client=kwargs.pop("llm_client", fake_planning_llm), **kwargs)

    return _factory


@pytest.fixture
def master_factory(fake_planning_llm):
    def _factory(worker_registry: WorkerRegistry, memory_manager: InMemoryMemoryManager):
        return MasterAgent(worker_registry=worker_registry, memory_manager=memory_manager, llm_client=fake_planning_llm)

    return _factory
