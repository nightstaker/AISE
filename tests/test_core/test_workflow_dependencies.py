"""Tests for task dependency verification in WorkflowEngine.

Tests for the feature that ensures tasks execute in correct order
based on their declared dependencies.
"""

import pytest

from aise.core.workflow import Phase, Task, Workflow, WorkflowEngine


class TestTaskDependencyVerification:
    """Test task dependency enforcement."""

    def test_task_with_no_dependencies_executes_immediately(self) -> None:
        """A task without dependencies should execute without waiting."""
        phase = Phase(name="test_phase")
        task = Task(agent="developer", skill="write_code")
        phase.add_task("developer", "write_code")

        assert len(task.depends_on) == 0
        assert task.key == "developer.write_code"

    def test_task_can_declare_dependency_on_another_task(self) -> None:
        """A task can declare dependency on another task by key."""
        phase = Phase(name="test_phase")
        task1 = phase.add_task("architect", "design")
        task2 = phase.add_task("developer", "implement")

        # Manually set dependency (feature not yet implemented)
        task2.depends_on = [task1.key]

        assert task1.key == "architect.design"
        assert task2.key == "developer.implement"
        assert task2.depends_on == ["architect.design"]

    def test_execute_phase_respects_dependencies(self) -> None:
        """Tasks should execute in dependency order."""
        workflow = Workflow(name="test_workflow")
        phase = Phase(name="test_phase")
        phase.add_task("architect", "design")
        phase.add_task("developer", "implement")
        phase.add_task("qa_engineer", "test")
        workflow.add_phase(phase)

        # Set up dependencies: implement depends on design, test depends on implement
        tasks = phase.tasks
        tasks[1].depends_on = [tasks[0].key]  # implement depends on design
        tasks[2].depends_on = [tasks[1].key]  # test depends on implement

        execution_order = []

        def mock_executor(agent: str, skill: str, input_data: dict) -> str:
            task_key = f"{agent}.{skill}"
            execution_order.append(task_key)
            return f"artifact_{task_key}"

        engine = WorkflowEngine()
        result = engine.execute_phase(workflow, mock_executor)

        # Verify execution respected dependencies
        assert result["phase"] == "test_phase"
        assert execution_order == ["architect.design", "developer.implement", "qa_engineer.test"]

    def test_execute_phase_detects_circular_dependency(self) -> None:
        """Circular dependencies should be detected and reported."""
        workflow = Workflow(name="test_workflow")
        phase = Phase(name="test_phase")
        task1 = phase.add_task("agent1", "skill1")
        task2 = phase.add_task("agent2", "skill2")
        task3 = phase.add_task("agent3", "skill3")
        workflow.add_phase(phase)

        # Create circular dependency: task1 -> task2 -> task3 -> task1
        task1.depends_on = [task3.key]
        task2.depends_on = [task1.key]
        task3.depends_on = [task2.key]

        engine = WorkflowEngine()

        with pytest.raises(ValueError) as exc_info:
            engine.execute_phase(workflow, lambda a, s, i: "artifact")
        assert "circular" in str(exc_info.value).lower() or "dependency" in str(exc_info.value).lower()

    def test_execute_phase_handles_missing_dependency(self) -> None:
        """Missing dependency target should be reported."""
        workflow = Workflow(name="test_workflow")
        phase = Phase(name="test_phase")
        task = phase.add_task("developer", "implement")
        task.depends_on = ["nonexistent.task"]
        workflow.add_phase(phase)

        engine = WorkflowEngine()

        with pytest.raises(ValueError) as exc_info:
            engine.execute_phase(workflow, lambda a, s, i: "artifact")
        error_msg = str(exc_info.value).lower()
        assert "missing" in error_msg or "dependency" in error_msg or "not found" in error_msg

    def test_execute_phase_executes_independent_tasks_in_parallel_order(self) -> None:
        """Independent tasks can be executed in any order (topologically sorted)."""
        workflow = Workflow(name="test_workflow")
        phase = Phase(name="test_phase")
        phase.add_task("agent1", "skill1")
        phase.add_task("agent2", "skill2")
        phase.add_task("agent3", "skill3")
        workflow.add_phase(phase)
        # No dependencies - all independent

        execution_order = []

        def mock_executor(agent: str, skill: str, input_data: dict) -> str:
            task_key = f"{agent}.{skill}"
            execution_order.append(task_key)
            return f"artifact_{task_key}"

        engine = WorkflowEngine()
        _ = engine.execute_phase(workflow, mock_executor)

        # All tasks should execute, order may vary but should be deterministic
        assert set(execution_order) == {"agent1.skill1", "agent2.skill2", "agent3.skill3"}
        assert len(execution_order) == 3

    def test_execute_phase_complex_dependency_graph(self) -> None:
        """Complex dependency graph should be resolved correctly."""
        workflow = Workflow(name="test_workflow")
        phase = Phase(name="test_phase")

        # Create a diamond dependency graph:
        #     A
        #    / \
        #   B   C
        #    \\/
        #     D

        task_a = phase.add_task("agent", "a")
        task_b = phase.add_task("agent", "b")
        task_c = phase.add_task("agent", "c")
        task_d = phase.add_task("agent", "d")
        workflow.add_phase(phase)

        task_b.depends_on = [task_a.key]
        task_c.depends_on = [task_a.key]
        task_d.depends_on = [task_b.key, task_c.key]

        execution_order = []

        def mock_executor(agent: str, skill: str, input_data: dict) -> str:
            task_key = f"{agent}.{skill}"
            execution_order.append(task_key)
            return f"artifact_{task_key}"

        engine = WorkflowEngine()
        _ = engine.execute_phase(workflow, mock_executor)

        # A must come first, D must come last
        assert execution_order[0] == "agent.a"
        assert execution_order[-1] == "agent.d"

        # B and C must come after A and before D
        a_idx = execution_order.index("agent.a")
        b_idx = execution_order.index("agent.b")
        c_idx = execution_order.index("agent.c")
        d_idx = execution_order.index("agent.d")

        assert a_idx < b_idx < d_idx
        assert a_idx < c_idx < d_idx

    def test_workflow_with_multiple_phases_and_dependencies(self) -> None:
        """Dependencies are checked within each phase independently."""
        workflow = Workflow(name="multi_phase")

        phase1 = Phase(name="phase1")
        phase1.add_task("agent", "task1")
        phase1.add_task("agent", "task2")
        phase1.tasks[1].depends_on = [phase1.tasks[0].key]
        workflow.add_phase(phase1)

        phase2 = Phase(name="phase2")
        phase2.add_task("agent", "task3")
        phase2.add_task("agent", "task4")
        phase2.tasks[1].depends_on = [phase2.tasks[0].key]
        workflow.add_phase(phase2)

        execution_order = []

        def mock_executor(agent: str, skill: str, input_data: dict) -> str:
            task_key = f"{agent}.{skill}"
            execution_order.append(task_key)
            return f"artifact_{task_key}"

        engine = WorkflowEngine()

        # Execute phase 1
        engine.execute_phase(workflow, mock_executor)
        phase1_order = execution_order.copy()
        execution_order.clear()

        # Execute phase 2
        workflow.advance()
        engine.execute_phase(workflow, mock_executor)
        phase2_order = execution_order

        # Each phase respects its own dependencies
        assert phase1_order == ["agent.task1", "agent.task2"]
        assert phase2_order == ["agent.task3", "agent.task4"]
