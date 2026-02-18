"""Tests for the workflow engine."""

from aise.core.workflow import Phase, ReviewGate, Task, Workflow, WorkflowEngine


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
        requirement_skills = [task.skill for task in wf.phases[0].tasks]
        assert "system_requirement_analysis" in requirement_skills
        assert "document_generation" in requirement_skills

    def test_create_default_workflow_design_min_review_rounds(self):
        wf = WorkflowEngine.create_default_workflow()
        design_phase = wf.phases[1]
        assert design_phase.name == "design"
        assert design_phase.review_gate is not None
        assert design_phase.review_gate.min_review_rounds == 3

    def test_create_default_workflow_implementation_min_review_rounds(self):
        wf = WorkflowEngine.create_default_workflow()
        impl_phase = wf.phases[2]
        assert impl_phase.name == "implementation"
        assert impl_phase.review_gate is not None
        assert impl_phase.review_gate.min_review_rounds == 3

    def test_create_default_workflow_implementation_requires_tests(self):
        wf = WorkflowEngine.create_default_workflow()
        impl_phase = wf.phases[2]
        assert impl_phase.require_tests_pass is True

    def test_run_review_executes_min_rounds(self):
        engine = WorkflowEngine()
        wf = Workflow(name="test")
        p = Phase(name="p1")
        p.add_task("a", "s1")
        p.review_gate = ReviewGate(
            reviewer_agent="a",
            review_skill="review",
            target_artifact_type="code",
            min_review_rounds=3,
        )
        p.status = p.status  # keep PENDING for now
        wf.add_phase(p)

        call_count = 0

        def executor(agent, skill, data):
            nonlocal call_count
            call_count += 1
            return f"artifact-{call_count}"

        # First execute the phase so it enters IN_REVIEW
        engine.execute_phase(wf, executor)
        call_count = 0  # reset after phase execution

        result = engine.run_review(wf, executor)
        assert result["approved"] is True
        assert result["rounds_completed"] == 3
        assert len(result["rounds"]) == 3
        assert call_count == 3

    def test_run_review_stops_on_failure(self):
        engine = WorkflowEngine()
        wf = Workflow(name="test")
        p = Phase(name="p1")
        p.add_task("a", "s1")
        p.review_gate = ReviewGate(
            reviewer_agent="a",
            review_skill="review",
            target_artifact_type="code",
            min_review_rounds=3,
        )
        wf.add_phase(p)

        call_count = 0

        def executor(agent, skill, data):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise RuntimeError("review failed")
            return f"artifact-{call_count}"

        engine.execute_phase(wf, executor)
        call_count = 0

        result = engine.run_review(wf, executor)
        assert result["approved"] is False
        assert result["rounds_completed"] == 2
        assert result["rounds"][0]["status"] == "success"
        assert result["rounds"][1]["status"] == "failed"

    def test_run_review_single_round_default(self):
        engine = WorkflowEngine()
        wf = Workflow(name="test")
        p = Phase(name="p1")
        p.add_task("a", "s1")
        p.review_gate = ReviewGate(
            reviewer_agent="a",
            review_skill="review",
            target_artifact_type="code",
        )
        wf.add_phase(p)

        call_count = 0

        def executor(agent, skill, data):
            nonlocal call_count
            call_count += 1
            return f"artifact-{call_count}"

        engine.execute_phase(wf, executor)
        call_count = 0

        result = engine.run_review(wf, executor)
        assert result["approved"] is True
        assert result["rounds_completed"] == 1

    def test_verify_tests_pass_success(self):
        engine = WorkflowEngine()
        wf = Workflow(name="test")
        p = Phase(name="impl", require_tests_pass=True)
        p.add_task("developer", "code_generation")
        wf.add_phase(p)

        def executor(agent, skill, data):
            return "test-artifact-1"

        result = engine.verify_tests_pass(wf, executor)
        assert result["passed"] is True
        assert "artifact_id" in result

    def test_verify_tests_pass_failure(self):
        engine = WorkflowEngine()
        wf = Workflow(name="test")
        p = Phase(name="impl", require_tests_pass=True)
        p.add_task("developer", "code_generation")
        wf.add_phase(p)

        def executor(agent, skill, data):
            raise RuntimeError("tests failed")

        result = engine.verify_tests_pass(wf, executor)
        assert result["passed"] is False
        assert "error" in result

    def test_verify_tests_pass_skipped_when_not_required(self):
        engine = WorkflowEngine()
        wf = Workflow(name="test")
        p = Phase(name="design", require_tests_pass=False)
        p.add_task("architect", "system_design")
        wf.add_phase(p)

        result = engine.verify_tests_pass(wf, lambda a, s, d: "id")
        assert result["passed"] is True
