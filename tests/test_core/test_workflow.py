"""Tests for the workflow engine."""

from aise.core.workflow import Phase, Task, Workflow, WorkflowEngine


class TestPhase:
    def test_add_task(self):
        phase = Phase(name="test")
        task = phase.add_task("agent_a", "skill_x", {"key": "val"})
        assert task.agent == "agent_a"
        assert task.skill == "skill_x"
        assert len(phase.tasks) == 1

    def test_task_key(self):
        task = Task(agent="dev", skill="code_gen")
        assert task.key == "dev.code_gen"


class TestWorkflow:
    def test_add_phase_and_navigate(self):
        wf = Workflow(name="test")
        wf.add_phase(Phase(name="p1"))
        wf.add_phase(Phase(name="p2"))

        assert wf.current_phase is not None
        assert wf.current_phase.name == "p1"
        assert not wf.is_complete

        wf.advance()
        assert wf.current_phase.name == "p2"

        wf.advance()
        assert wf.is_complete

    def test_empty_workflow_is_complete(self):
        wf = Workflow(name="empty")
        assert wf.is_complete


class TestWorkflowEngine:
    def test_execute_phase_success(self):
        engine = WorkflowEngine()
        wf = Workflow(name="test")
        p = Phase(name="p1")
        p.add_task("a", "s1")
        wf.add_phase(p)

        def executor(agent, skill, data):
            return "artifact-123"

        result = engine.execute_phase(wf, executor)
        assert result["status"] == "completed"
        assert result["tasks"]["a.s1"]["status"] == "success"

    def test_execute_phase_failure(self):
        engine = WorkflowEngine()
        wf = Workflow(name="test")
        p = Phase(name="p1")
        p.add_task("a", "s1")
        wf.add_phase(p)

        def executor(agent, skill, data):
            raise RuntimeError("boom")

        result = engine.execute_phase(wf, executor)
        assert result["status"] == "failed"

    def test_execute_complete_workflow(self):
        engine = WorkflowEngine()
        wf = Workflow(name="test")
        p = Phase(name="p1")
        p.add_task("a", "s1")
        wf.add_phase(p)

        result = engine.execute_phase(wf, lambda a, s, d: "id")
        assert result["status"] == "completed"

    def test_run_review_no_gate(self):
        engine = WorkflowEngine()
        wf = Workflow(name="test")
        wf.add_phase(Phase(name="p1"))

        result = engine.run_review(wf, lambda a, s, d: "id")
        assert result["approved"] is True

    def test_create_default_workflow(self):
        wf = WorkflowEngine.create_default_workflow()
        assert wf.name == "default_sdlc"
        assert len(wf.phases) == 4
        phase_names = [p.name for p in wf.phases]
        assert phase_names == ["requirements", "design", "implementation", "testing"]
