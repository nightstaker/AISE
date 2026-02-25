from __future__ import annotations

import pytest

from aise.runtime.exceptions import AuthorizationError, PlanningError
from aise.runtime.models import LLMTrace, Principal
from aise.runtime.runtime import AgentRuntime, SubmitTaskRequest


def _admin(user_id: str = "u1", tenant_id: str = "t1") -> Principal:
    return Principal(user_id=user_id, tenant_id=tenant_id, roles=["Admin"])


def _viewer(user_id: str = "u2", tenant_id: str = "t1") -> Principal:
    return Principal(user_id=user_id, tenant_id=tenant_id, roles=["Viewer"])


def test_submit_task_request_dataclass() -> None:
    req = SubmitTaskRequest(prompt="p", principal=_admin(), run_sync=False)
    assert req.prompt == "p"
    assert req.run_sync is False


def test_agent_runtime_auth_context_submit_and_manual_run(runtime_factory) -> None:
    rt = runtime_factory()
    task_id = rt.submit_task(
        prompt="设计一个 runtime",
        auth_context={"user_id": "u1", "tenant_id": "t1", "roles": ["Admin"]},
        run_sync=False,
    )
    status_before = rt.get_task_status(task_id, principal=_admin())
    assert status_before["status"] in {"created", "planning", "running", "completed"}
    rt.run_task(task_id, principal=_admin())
    status_after = rt.get_task_status(task_id, principal=_admin())
    assert status_after["status"] == "completed"


def test_agent_runtime_requires_llm_when_no_explicit_plan() -> None:
    rt = AgentRuntime()
    with pytest.raises(PlanningError):
        rt.submit_task(
            prompt="设计一个runtime",
            principal=_admin(),
            run_sync=True,
        )


def test_agent_runtime_llm_trace_redaction_and_sensitive_access_control(runtime_factory) -> None:
    rt = runtime_factory()
    p = _admin()
    task_id = rt.submit_task(prompt="x", principal=p, run_sync=False)
    rt.observability.record_llm_trace(
        task_id, LLMTrace(trace_id="lt1", prompt="secret prompt", response="secret response")
    )
    redacted = rt.get_task_llm_traces(task_id, principal=p, include_sensitive=False)
    assert redacted[0]["prompt"].startswith("<redacted len=")
    sensitive = rt.get_task_llm_traces(task_id, principal=p, include_sensitive=True)
    assert sensitive[0]["prompt"] == "secret prompt"

    with pytest.raises(AuthorizationError):
        rt.get_task_llm_traces(task_id, principal=_viewer(user_id="u1"), include_sensitive=True)


def test_agent_runtime_read_permission_and_retry_node(runtime_factory) -> None:
    rt = runtime_factory()
    owner = _admin("owner", "tenant-x")
    other_viewer = _viewer("other", "tenant-x")
    task_id = rt.submit_task(prompt="设计 runtime", principal=owner, run_sync=True)

    with pytest.raises(AuthorizationError):
        rt.get_task(task_id, principal=other_viewer)

    task_payload = rt.get_task(task_id, principal=owner)
    first_node_id = task_payload["plan"]["tasks"][0]["id"]
    retry_resp = rt.retry_node(task_id, first_node_id, principal=owner)
    assert retry_resp["node_id"] == first_node_id
    assert retry_resp["status"] in {"success", "failed", "partial_success"}

    with pytest.raises(ValueError):
        rt.retry_node(task_id, "missing", principal=owner)


def test_agent_runtime_plan_contains_process_context_and_step_requirements(runtime_factory) -> None:
    rt = runtime_factory()
    owner = _admin("owner2", "tenant-y")
    task_id = rt.submit_task(prompt="请设计一个agent runtime架构", principal=owner, run_sync=True)
    task_payload = rt.get_task(task_id, principal=owner)
    plan = task_payload["plan"]
    assert plan["metadata"]["planning_inference"]["mode"] == "single_inference"
    assert plan["metadata"].get("process_context") is not None
    assert plan["metadata"].get("selected_process") is not None
    first_node_meta = plan["tasks"][0].get("metadata", {})
    assert "effective_agent_requirements" in first_node_meta
