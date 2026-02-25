from __future__ import annotations

from dataclasses import dataclass

from aise.runtime.agents import WorkerAgent, build_default_worker
from aise.runtime.memory import InMemoryMemoryManager
from aise.runtime.models import ExecutionStatus, Principal, RuntimeTask, TaskNode, TaskPlan
from aise.runtime.registry import WorkerRegistry


@dataclass
class DummyLLM:
    model: str = "dummy-model"

    def complete(self, prompt: str, **kwargs) -> str:
        return f"LLM:{len(prompt)}"


def test_worker_agent_register_discover_health_and_cancel() -> None:
    worker = WorkerAgent(adapter_id="w1", agent_type="generic_worker")
    worker.register_skill(
        capability_id="skill.a",
        name="analyze",
        description="x",
        func=lambda input_data, context: {"summary": "s1", "output": {"x": 1}},
        tags=["analyze"],
    )
    worker.register_tool(
        capability_id="tool.b",
        name="echo",
        description="x",
        func=lambda input_data, context: {"summary": "s2", "output": {"y": 2}},
        tags=["echo"],
    )
    caps = worker.discover_capabilities()
    assert len(caps) == 2
    assert worker.health_check()["capability_count"] == 2
    assert worker.cancel("t", "n") is False


def test_worker_agent_execute_task_success() -> None:
    worker = WorkerAgent(adapter_id="w1", agent_type="generic_worker")
    worker.register_skill(
        capability_id="skill.a",
        name="analyze",
        description="x",
        func=lambda input_data, context: {
            "summary": "ok",
            "output": {"k": "v"},
            "artifacts": [{"type": "text", "uri": "artifact://x"}],
            "llm_traces": [{"trace_id": "z1", "prompt": "p", "response": "r"}],
        },
        tags=["analyze"],
    )
    node = TaskNode(id="n1", name="node", capability_hints=["analyze"], input_data={"a": 1})
    result = worker.execute_task(node, {"memory_summary": ""})
    assert result.status == ExecutionStatus.SUCCESS
    assert result.artifacts and result.llm_traces


def test_worker_agent_execute_task_failure_without_capabilities() -> None:
    worker = WorkerAgent(adapter_id="w1", agent_type="generic_worker")
    result = worker.execute_task(TaskNode(id="n1", name="n1"), {})
    assert result.status == ExecutionStatus.FAILED
    assert result.errors


def test_master_agent_public_interfaces(master_factory) -> None:
    wr = WorkerRegistry()
    wr.register(build_default_worker())
    mm = InMemoryMemoryManager()
    master = master_factory(wr, mm)
    task = RuntimeTask(principal=Principal(user_id="u1", tenant_id="t1", roles=["Admin"]), prompt="设计 runtime")
    scan = master.scan_workers()
    assert scan
    process_summaries = master.scan_processes()
    assert process_summaries
    summaries, summary_text = master.retrieve_relevant_memory(task)
    assert isinstance(summaries, list)
    assert isinstance(summary_text, str)
    planning_prompt = master.build_planning_prompt(
        task=task,
        memory_summary_text=summary_text,
        process_summaries=master.scan_processes(),
    )
    assert "ONE inference" in planning_prompt
    plan = master.generate_plan(task)
    assert isinstance(plan, TaskPlan)
    assert plan.metadata.get("selected_process") is not None
    assert plan.metadata.get("planning_inference", {}).get("mode") == "single_inference"
    assert plan.metadata.get("process_context") is not None
    # Seed one failed result to test replan
    from aise.runtime.models import ExecutionResult

    res = ExecutionResult(node_id=plan.tasks[0].id, status=ExecutionStatus.FAILED, summary="failed")
    res.finish()
    task.node_results[plan.tasks[0].id] = res
    replanned = master.maybe_replan(task, plan)
    assert replanned is None
    final = master.finalize_task_output(task)
    assert final["failure_count"] >= 1


def test_build_default_worker_can_execute_default_skills() -> None:
    worker = build_default_worker()
    node = TaskNode(id="n1", name="analyze", capability_hints=["analyze"], input_data={"prompt": "x"})
    result = worker.execute_task(node, {})
    assert result.status == ExecutionStatus.SUCCESS
