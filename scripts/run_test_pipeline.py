"""Deterministic end-to-end pipeline test for the refactored runtime.

Skips the orchestrator LLM (too slow on local hardware for a smoke test)
and instead directly invokes the primitive tools in the order a smart
orchestrator would call them. This proves the full integration works:

  1. RuntimeManager loads agents, parses output_layout / role / forbidden_outputs
  2. ProjectSession scaffolds the project root from agent layouts
  3. The discovery primitives (list_processes/get_process/list_agents) work
  4. The PolicyBackend rejects bad paths and accepts good ones
  5. dispatch_task routes to a project-scoped runtime with the correct backend
  6. mark_complete sets the workflow state and the session loop honors it

Worker agents are mocked so we don't need a real LLM. Run with::

    python scripts/run_test_pipeline.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aise.config import ModelConfig, ProjectConfig  # noqa: E402
from aise.runtime.policy_backend import make_policy_backend  # noqa: E402
from aise.runtime.runtime_config import RuntimeConfig, SafetyLimits  # noqa: E402

PROJECT_ROOT = Path("/tmp/aise_test_pipeline")


def main() -> int:
    if PROJECT_ROOT.exists():
        shutil.rmtree(PROJECT_ROOT)
    PROJECT_ROOT.mkdir(parents=True)
    print(f"=== Pipeline test against {PROJECT_ROOT} ===\n")

    issues: list[str] = []

    # Patch the LLM factory and deepagents so the manager can start
    # without needing a real LLM.
    from langchain_core.messages import AIMessage

    fake_llm = MagicMock()
    fake_agent = MagicMock()
    fake_agent.invoke.return_value = {"messages": [AIMessage(content="(fake worker output)")]}

    with (
        patch("aise.runtime.agent_runtime.create_deep_agent", return_value=fake_agent),
        patch("aise.runtime.manager._build_llm", return_value=fake_llm),
    ):
        from aise.runtime.manager import RuntimeManager
        from aise.runtime.project_session import ProjectSession

        cfg = ProjectConfig(project_name="pipeline_smoke", development_mode="local")
        cfg.default_model = ModelConfig(provider="local", model="fake", api_key="x")
        manager = RuntimeManager(config=cfg)
        manager.start()

        print(f"[1] Loaded {len(manager.runtimes)} agents:")
        for name, rt in sorted(manager.runtimes.items()):
            d = rt.definition
            print(
                f"    - {name}: role={d.role!r} layout={d.output_layout.paths} "
                f"forbidden={len(d.output_layout.forbidden)} tools={d.allowed_tools}"
            )

        # Verify the new fields landed on every agent
        for name in ("developer", "qa_engineer", "architect", "product_manager", "project_manager"):
            rt = manager.get_runtime(name)
            if rt is None or not rt.definition.role:
                issues.append(f"agent {name}: missing role field")
            if name == "project_manager" and rt and rt.definition.role != "orchestrator":
                issues.append(f"agent {name}: role should be 'orchestrator', got {rt.definition.role!r}")
            if name == "developer" and rt and not rt.definition.output_layout.forbidden:
                issues.append(f"agent {name}: forbidden_outputs should not be empty")

        rt_config = RuntimeConfig(safety_limits=SafetyLimits(max_dispatches=5, max_continuations=3))

        events: list[dict] = []
        session = ProjectSession(
            manager=manager,
            project_root=PROJECT_ROOT,
            on_event=events.append,
            runtime_config=rt_config,
        )

        # Verify orchestrator selection
        print(f"\n[2] Selected orchestrator: {session.orchestrator_name!r}")
        if session.orchestrator_name != "project_manager":
            issues.append(f"orchestrator should be project_manager, got {session.orchestrator_name!r}")

        # Verify project scaffold (driven by union of agent output_layouts)
        scaffold = sorted(p.relative_to(PROJECT_ROOT) for p in PROJECT_ROOT.iterdir() if p.is_dir())
        print(f"\n[3] Scaffolded directories: {scaffold}")
        # Every layout dir from agents must exist
        for name, rt in manager.runtimes.items():
            for sub in rt.definition.output_layout.paths.values():
                target = PROJECT_ROOT / sub
                if not target.exists():
                    issues.append(f"missing scaffolded dir for {name}: {sub}")
        if not (PROJECT_ROOT / "runs/trace").exists():
            issues.append("missing runs/trace scaffolding")

        # Drive the primitive tools directly (this is what an orchestrator does)
        tools = session._make_tools()
        tool_map = {t.name: t for t in tools}
        print(f"\n[4] Primitive tools available: {sorted(tool_map.keys())}")
        expected = {
            "list_processes",
            "get_process",
            "list_agents",
            "dispatch_task",
            "dispatch_tasks_parallel",
            "execute_shell",
            "mark_complete",
        }
        missing_tools = expected - set(tool_map)
        if missing_tools:
            issues.append(f"missing tools: {missing_tools}")

        # 4a. list_processes
        proc_result = json.loads(tool_map["list_processes"].invoke({}))
        proc_ids = [p["process_id"] for p in proc_result["processes"]]
        print(f"\n[5] list_processes → {proc_ids}")
        if "waterfall_standard_v1" not in proc_ids:
            issues.append("waterfall_standard_v1 missing from list_processes")

        # 4b. get_process
        wf_md = tool_map["get_process"].invoke({"process_file": "waterfall.process.md"})
        if "phase_3_implementation" not in wf_md:
            issues.append("waterfall.process.md content unexpected")

        # 4c. list_agents (must exclude project_manager)
        ag_result = json.loads(tool_map["list_agents"].invoke({}))
        ag_names = sorted(a["name"] for a in ag_result["agents"])
        print(f"\n[6] list_agents → {ag_names}")
        if "project_manager" in ag_names:
            issues.append("list_agents should exclude project_manager (orchestrator)")
        if "developer" not in ag_names:
            issues.append("list_agents missing developer")

        # 4d. dispatch_task to developer (worker is mocked, returns "(fake worker output)")
        dt_result = json.loads(
            tool_map["dispatch_task"].invoke(
                {
                    "agent_name": "developer",
                    "task_description": "Implement calculator",
                    "step_id": "step_implement_with_tdd",
                    "phase": "phase_3_implementation",
                }
            )
        )
        print(f"\n[7] dispatch_task(developer) → status={dt_result['status']}")
        if dt_result["status"] != "completed":
            issues.append(f"dispatch_task failed: {dt_result}")

        # 4e. dispatch to nonexistent agent must fail cleanly
        ghost = json.loads(tool_map["dispatch_task"].invoke({"agent_name": "ghost", "task_description": "x"}))
        if ghost["status"] != "failed" or "not found" not in ghost["error"]:
            issues.append(f"ghost dispatch should fail with 'not found': {ghost}")

        # 4f. execute_shell with allowed command
        sh_result = json.loads(tool_map["execute_shell"].invoke({"command": "python --version"}))
        print(f"\n[8] execute_shell(python --version) → exit={sh_result.get('exit_code')}")
        if sh_result["status"] != "completed" or sh_result["exit_code"] != 0:
            issues.append(f"execute_shell python failed: {sh_result}")

        # 4g. execute_shell with denied command
        sh_deny = json.loads(tool_map["execute_shell"].invoke({"command": "rm -rf /"}))
        if sh_deny["status"] != "refused":
            issues.append(f"execute_shell should refuse rm: {sh_deny}")

        # 4h. PolicyBackend integration: build a backend for developer and try writes
        dev_rt = manager.get_runtime("developer")
        dev_backend = make_policy_backend(
            PROJECT_ROOT,
            layout=dev_rt.definition.output_layout,
            agent_name="developer",
        )
        ok_write = dev_backend.write("src/main.py", "print('hi')")
        bad_write = dev_backend.write("docs/random.py", "junk")
        forbidden_write = dev_backend.write("src/run_pytest.py", "junk")
        absolute_write = dev_backend.write("/etc/passwd", "x")
        print("\n[9] PolicyBackend writes:")
        print(f"    src/main.py        → error={ok_write.error}")
        print(f"    docs/random.py     → error={bad_write.error}")
        print(f"    src/run_pytest.py  → error={forbidden_write.error}")
        print(f"    /etc/passwd        → error={absolute_write.error}")
        if ok_write.error is not None:
            issues.append(f"valid write rejected: {ok_write.error}")
        if bad_write.error is None:
            issues.append("docs/random.py should be rejected for developer")
        if forbidden_write.error is None or "forbidden pattern" not in forbidden_write.error:
            issues.append("forbidden filename should be rejected")
        if absolute_write.error is None:
            issues.append("/etc/passwd should be rejected (stripped to etc/passwd, outside layout)")

        # 4i. mark_complete sets state
        report = "Calculator delivered. All tests pass."
        tool_map["mark_complete"].invoke({"report": report})
        print(f"\n[10] mark_complete: is_complete={session.workflow_state.is_complete}")
        if not session.workflow_state.is_complete:
            issues.append("mark_complete did not set workflow_state.is_complete")
        if session.workflow_state.final_report != report:
            issues.append("final_report not stored correctly")

        # 4j. session.run should now exit immediately because mark_complete was called.
        # Set up the orchestrator runtime to return any value.
        session._pm_runtime.handle_message = MagicMock(return_value="ack")
        run_result = session.run("Build a calculator")
        print(f"\n[11] session.run → returned final report ({len(run_result)} chars)")
        if report not in run_result:
            issues.append("session.run did not return the final_report from workflow_state")

        # 4k. Event log accounting
        types = sorted({e.get("type") for e in events})
        print(f"\n[12] Event types collected: {types}")
        for required in ("tool_call", "task_request", "task_response", "workflow_complete"):
            if required not in types:
                issues.append(f"event log missing type {required!r}")

        manager.stop()

    print("\n=== Files in project root ===")
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if path.is_file():
            rel = path.relative_to(PROJECT_ROOT)
            print(f"  {rel} ({path.stat().st_size} bytes)")

    print("\n=== Result ===")
    if issues:
        print(f"FAILED ({len(issues)} issue(s)):")
        for i in issues:
            print(f"  - {i}")
        return 1
    print("OK — all pipeline checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
