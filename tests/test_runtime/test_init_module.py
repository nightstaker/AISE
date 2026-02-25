from __future__ import annotations

import aise.runtime as runtime_pkg


def test_runtime_init_exports_all_declared_symbols() -> None:
    assert isinstance(runtime_pkg.__all__, list)
    for name in runtime_pkg.__all__:
        assert hasattr(runtime_pkg, name), f"Missing export: {name}"


def test_runtime_init_exposes_core_types() -> None:
    assert runtime_pkg.AgentRuntime is not None
    assert runtime_pkg.TaskPlan is not None
    assert runtime_pkg.WorkerAgent is not None
    assert callable(runtime_pkg.validate_task_plan_payload)
