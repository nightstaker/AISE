"""End-to-end CLI test of waterfall_v2 (driven by ProjectSession).

Bypasses the web UI / scaffold entirely. Sets up a minimal project
root with a hand-written project_config.json (process_type=waterfall_v2)
and runs through ProjectSession.run() — the same code path the web UI
hits for waterfall_v2 projects.

Goal: prove the v2 pipeline reaches `delivery` end-to-end against the
local qwen3.6-35b LLM, with a SMALL requirement so the LLM doesn't
enter an output storm.

Usage:
    .venv/bin/python scripts/test_waterfall_v2_e2e.py
"""

from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path("/tmp/aise_v2_test/v2demo")
REQUIREMENT = "Build a Python CLI tool that prints 'hello, world' when run."

# Tiny project_config — process_type=waterfall_v2 is the key bit.
PROJECT_CONFIG = {
    "project_name": "v2demo",
    "development_mode": "local",
    "process_type": "waterfall_v2",
    "ui_language": "en",
    "default_model": {
        "provider": "Local",
        "model": "qwen3.6-35b",
        "api_key": "",
        "base_url": "http://127.0.0.1:8088/v1",
        "temperature": 0.7,
        "max_tokens": 4096,
    },
    "model_providers": [
        {
            "provider": "Local",
            "api_key": "",
            "base_url": "http://127.0.0.1:8088/v1",
            "enabled": True,
        }
    ],
    "agents": {
        "product_manager": {"name": "product_manager", "enabled": True},
        "architect": {"name": "architect", "enabled": True},
        "developer": {"name": "developer", "enabled": True},
        "qa_engineer": {"name": "qa_engineer", "enabled": True},
        "project_manager": {"name": "project_manager", "enabled": True},
        "rd_director": {"name": "rd_director", "enabled": True},
    },
    "agent_model_selection": {},
    "workflow": {
        "max_review_iterations": 3,
        "fail_on_review_rejection": False,
    },
    "session": {
        "max_concurrent_sessions": 5,
    },
    "workspace": {
        "projects_root": "projects",
        "artifacts_root": "artifacts",
        "auto_create_dirs": True,
    },
    "logging": {
        "level": "INFO",
        "log_dir": "logs",
        "json_format": False,
        "rotate_daily": True,
    },
    "github": {"token": "", "repo_owner": "", "repo_name": ""},
}


def main() -> int:
    # Reset project root
    if PROJECT_ROOT.exists():
        shutil.rmtree(PROJECT_ROOT)
    PROJECT_ROOT.mkdir(parents=True)
    (PROJECT_ROOT / "project_config.json").write_text(
        json.dumps(PROJECT_CONFIG, indent=2), encoding="utf-8"
    )
    # Pre-init git so PR contracts that expect a repo root work
    import subprocess

    subprocess.run(["git", "init", "-q"], cwd=PROJECT_ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "test@aise.local"], cwd=PROJECT_ROOT, check=True)
    subprocess.run(["git", "config", "user.name", "AISE Test"], cwd=PROJECT_ROOT, check=True)
    (PROJECT_ROOT / ".gitignore").write_text("__pycache__/\n*.pyc\n", encoding="utf-8")
    for sub in ("docs", "src", "tests", "scripts", "config", "artifacts", "trace", "runs"):
        (PROJECT_ROOT / sub).mkdir(exist_ok=True)
    subprocess.run(["git", "add", "-A"], cwd=PROJECT_ROOT, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "scaffold"], cwd=PROJECT_ROOT, check=True)

    # Configure logging via the AISE config
    from aise.config import ProjectConfig
    from aise.utils.logging import configure_logging

    cfg = ProjectConfig.from_dict(PROJECT_CONFIG)
    configure_logging(cfg.logging, force=True)

    print(f"\n=== STARTING waterfall_v2 e2e ===")
    print(f"project_root: {PROJECT_ROOT}")
    print(f"process_type: {cfg.process_type}")  # MUST print 'waterfall_v2'
    print(f"requirement: {REQUIREMENT!r}\n")

    if cfg.process_type != "waterfall_v2":
        print("FATAL: process_type was downgraded; check whitelists")
        return 1

    # Build runtime
    from aise.runtime import ProjectSession, RuntimeManager

    manager = RuntimeManager(config=cfg)
    manager.start()
    print(f"agents loaded: {sorted(manager.runtimes.keys())}")

    # Track event timing for diagnostics
    events_log: list[tuple[float, dict]] = []
    start_time = time.monotonic()

    def on_event(event: dict) -> None:
        events_log.append((time.monotonic() - start_time, event))
        et = event.get("type", "?")
        # Print phase events + halts to stdout for live tracking
        if et in ("phase_plan", "phase_start", "phase_complete"):
            print(
                f"[{time.monotonic() - start_time:7.1f}s] {et}: "
                f"phase={event.get('phase_name', '?')} "
                f"idx={event.get('phase_idx', '?')}"
            )

    session = ProjectSession(
        manager,
        project_root=str(PROJECT_ROOT),
        on_event=on_event,
        mode="initial",
        process_type="waterfall_v2",
    )

    # Run!
    print(f"\n--- ProjectSession.run() starting ---\n")
    t0 = time.monotonic()
    try:
        result = session.run(REQUIREMENT)
    except Exception as exc:
        elapsed = time.monotonic() - t0
        print(f"\n[{elapsed:.1f}s] ❌ EXCEPTION: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
        return 2
    elapsed = time.monotonic() - t0

    print(f"\n--- run completed in {elapsed:.1f}s ---")
    print(f"\nresult:\n{result}\n")

    # Verify artifacts on disk
    print("--- artifact check ---")
    expected = [
        "docs/requirement.md",
        "docs/requirement_contract.json",
        "docs/architecture.md",
        "docs/stack_contract.json",
        "docs/behavioral_contract.json",
        "docs/delivery_report.md",
    ]
    halt_file = PROJECT_ROOT / "runs" / "HALTED.json"
    halted = halt_file.is_file()
    for path in expected:
        p = PROJECT_ROOT / path
        if p.is_file():
            print(f"  ✅ {path:45s} ({p.stat().st_size} B)")
        else:
            print(f"  ❌ {path:45s} MISSING")
    if halted:
        print(f"  ⚠️ runs/HALTED.json present:")
        print(f"     {halt_file.read_text(encoding='utf-8')[:600]}")

    return 0 if not halted and not any("HALTED" in str(e[1]) for e in events_log) else 3


if __name__ == "__main__":
    sys.exit(main())
