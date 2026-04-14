"""End-to-end smoke test for the refactored ProjectSession.

Spins up a RuntimeManager against the local qwen3.5 endpoint, builds a
ProjectSession on a fresh /tmp project directory, and asks it to build
a tiny calculator. Prints a summary of:

  - the orchestrator that was selected
  - every event the orchestrator emitted
  - the final files that landed under the project root
  - whether mark_complete was actually called

Run with::

    python scripts/run_test_calculator.py

Expects a local OpenAI-compatible endpoint at the URL configured below.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sys
from pathlib import Path

# Make `aise` importable when running as a script.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from aise.config import ModelConfig, ModelDefinition, ModelProvider, ProjectConfig  # noqa: E402
from aise.runtime.manager import RuntimeManager  # noqa: E402
from aise.runtime.project_session import ProjectSession  # noqa: E402
from aise.runtime.runtime_config import RuntimeConfig, SafetyLimits  # noqa: E402

PROJECT_ROOT = Path("/tmp/aise_test_calc")
LOCAL_BASE_URL = os.environ.get("AISE_LOCAL_BASE_URL", "http://127.0.0.1:8088/v1")
LOCAL_MODEL = os.environ.get("AISE_LOCAL_MODEL", "qwen3.5")
REQUIREMENT = (
    "Build a tiny command-line calculator in Python. It should accept two numbers "
    "and an operator (+, -, *, /) as arguments, print the result, and handle "
    "division by zero with a clear error message. Include unit tests."
)


def build_project_config() -> ProjectConfig:
    """Pin everything to the local OpenAI-compatible endpoint."""
    cfg = ProjectConfig(project_name="test_calculator", development_mode="local")
    cfg.default_model = ModelConfig(
        provider="local",
        model=LOCAL_MODEL,
        api_key="local-no-key-required",
        base_url=LOCAL_BASE_URL,
        temperature=0.4,
        max_tokens=4096,
    )
    cfg.model_providers = [
        ModelProvider(
            provider="local",
            api_key="local-no-key-required",
            base_url=LOCAL_BASE_URL,
            enabled=True,
        )
    ]
    cfg.models = [
        ModelDefinition(
            id=LOCAL_MODEL,
            name=LOCAL_MODEL,
            api_model=LOCAL_MODEL,
            providers=["local"],
            default_provider="local",
            is_default=True,
            is_local=False,
        )
    ]
    cfg.ensure_model_catalog_defaults()
    return cfg


def main() -> int:
    logging.basicConfig(
        level=os.environ.get("AISE_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
    )

    if PROJECT_ROOT.exists():
        shutil.rmtree(PROJECT_ROOT)
    PROJECT_ROOT.mkdir(parents=True)
    print(f"Project root: {PROJECT_ROOT}")

    project_config = build_project_config()
    manager = RuntimeManager(config=project_config)
    manager.start()
    print(f"Loaded agents: {sorted(manager.runtimes.keys())}")
    for name, rt in sorted(manager.runtimes.items()):
        defn = rt.definition
        print(
            f"  - {name}: role={defn.role!r} layout={defn.output_layout.paths} "
            f"forbidden={defn.output_layout.forbidden} tools={defn.allowed_tools}"
        )

    # Slightly tighter caps so the smoke test is bounded.
    rt_config = RuntimeConfig(safety_limits=SafetyLimits(max_dispatches=10, max_continuations=4))

    events: list[dict] = []

    def on_event(ev: dict) -> None:
        events.append(ev)
        kind = ev.get("type", "?")
        if kind == "task_request":
            print(f"  [event] task_request → {ev.get('to')} step={ev['payload'].get('step')!r}")
        elif kind == "task_response":
            status = ev.get("status")
            length = ev.get("payload", {}).get("output_length")
            print(f"  [event] task_response ← {ev.get('from')} status={status} bytes={length}")
        elif kind == "stage_update":
            print(f"  [event] stage→ {ev.get('stage')}")
        elif kind == "tool_call":
            print(f"  [event] tool_call: {ev.get('tool')} :: {ev.get('summary', '')[:80]}")
        elif kind == "workflow_complete":
            print(f"  [event] workflow_complete (report={ev.get('report_length')} chars)")
        else:
            print(f"  [event] {kind}: {json.dumps(ev, default=str)[:200]}")

    session = ProjectSession(
        manager=manager,
        project_root=PROJECT_ROOT,
        on_event=on_event,
        runtime_config=rt_config,
    )
    print(f"Selected orchestrator: {session.orchestrator_name}")

    print("\n=== Running ProjectSession ===")
    try:
        result = session.run(REQUIREMENT)
    except Exception as exc:
        print(f"\nProjectSession.run raised: {exc}")
        return 2
    finally:
        manager.stop()

    print("\n=== Final response ===")
    print(result[:800])
    print("...(truncated)" if len(result) > 800 else "")

    print("\n=== Workflow state ===")
    print(f"  is_complete: {session.workflow_state.is_complete}")
    print(f"  final_report_len: {len(session.workflow_state.final_report)}")
    print(f"  total events: {len(events)}")
    by_type: dict[str, int] = {}
    for ev in events:
        by_type[ev.get("type", "?")] = by_type.get(ev.get("type", "?"), 0) + 1
    print(f"  events by type: {by_type}")

    print("\n=== Files written ===")
    for path in sorted(PROJECT_ROOT.rglob("*")):
        if path.is_file():
            rel = path.relative_to(PROJECT_ROOT)
            size = path.stat().st_size
            print(f"  {rel} ({size} bytes)")

    print("\n=== Verification ===")
    issues: list[str] = []
    if not session.workflow_state.is_complete:
        issues.append("mark_complete was NOT called")
    if not (PROJECT_ROOT / "src").iterdir():
        issues.append("src/ is empty")
    has_main = (PROJECT_ROOT / "src" / "main.py").is_file() or any((PROJECT_ROOT / "src").rglob("*.py"))
    if not has_main:
        issues.append("no .py files under src/")
    has_tests = any((PROJECT_ROOT / "tests").rglob("test_*.py"))
    if not has_tests:
        issues.append("no test_*.py files under tests/")

    if issues:
        print("ISSUES:")
        for issue in issues:
            print(f"  - {issue}")
        return 1
    print("OK — all expected outputs present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
