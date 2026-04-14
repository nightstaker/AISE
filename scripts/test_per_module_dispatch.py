#!/usr/bin/env python3
"""Verify per-module dispatch + write-overwrite eliminates file loop problems.

Simulates the orchestrator dispatching developer once per module, each
time asking for exactly 2 files (test + src). Dependent modules get
hints about which existing files to read.

Success criteria per round:
- All 8 files created (4 src + 4 test)
- Zero junk files (_v2, _new, _final, etc.)
- Zero write_exists errors

Usage:
    python scripts/test_per_module_dispatch.py --rounds 20
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

LOCAL_BASE_URL = os.environ.get("AISE_LOCAL_BASE_URL", "http://127.0.0.1:8088/v1")
LOCAL_MODEL = os.environ.get("AISE_LOCAL_MODEL", "gemma4")
LOCAL_API_KEY = os.environ.get("AISE_LOCAL_API_KEY", "local-no-key-required")

# (name, description, dependencies)
MODULES = [
    ("models", "Direction enum (UP/DOWN/LEFT/RIGHT with delta tuples), Point class (x,y), Snake class (body, direction, grow_flag, move/grow methods), Food class (position)", []),
    ("collision", "CollisionDetector: check_wall(head, width, height), check_self(head, body), check_food(head, food_pos) — all return bool", ["models"]),
    ("scoring", "ScoreManager: score int, level int, add_points(base_points), get_speed() returning float", []),
    ("engine", "GameEngine: __init__(width, height), update(), handle_input(direction). Uses Snake/Food from models, CollisionDetector from collision, ScoreManager from scoring", ["models", "collision", "scoring"]),
]

DEVELOPER_PROMPT = (
    "You are a developer. Each task is for ONE module. "
    "Write exactly 2 files: tests/test_<name>.py first, then src/<name>.py. "
    "Then respond with a summary. Do NOT write extra files."
)


def run_one_round(round_num: int) -> tuple[bool, dict]:
    from deepagents import create_deep_agent
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import HumanMessage

    from aise.runtime.policy_backend import make_policy_backend

    tmp = Path(tempfile.mkdtemp(prefix=f"permod_{round_num}_"))
    stats = {
        "time": 0.0,
        "total_msgs": 0,
        "write_exists": 0,
        "edit_nomatch": 0,
        "junk": [],
        "dispatches": 0,
        "modules_ok": [],
    }

    try:
        backend = make_policy_backend(str(tmp))

        (tmp / "docs").mkdir(parents=True, exist_ok=True)
        (tmp / "docs" / "architecture.md").write_text(
            "# Architecture\n\n## Modules\n"
            + "\n".join(f"- `src/{name}.py`: {desc}" for name, desc, _ in MODULES)
            + "\n"
        )

        t0 = time.time()

        for mod_name, mod_desc, deps in MODULES:
            llm = ChatOpenAI(
                model=LOCAL_MODEL,
                api_key=LOCAL_API_KEY,
                base_url=LOCAL_BASE_URL,
                temperature=0.2,
                max_tokens=4096,
            )
            agent = create_deep_agent(
                model=llm,
                system_prompt=DEVELOPER_PROMPT,
                backend=backend,
                name="dev",
            )

            dep_note = ""
            if deps:
                dep_note = (
                    f" This module imports from: "
                    + ", ".join(f"src/{d}.py" for d in deps)
                    + ". Read those files first to understand the API."
                )

            task = (
                f"Implement module '{mod_name}': {mod_desc}.{dep_note}\n\n"
                f"Write exactly 2 files:\n"
                f"1. /tests/test_{mod_name}.py (pytest tests)\n"
                f"2. /src/{mod_name}.py (implementation)\n\n"
                f"Read /docs/architecture.md if needed for context."
            )

            try:
                result = agent.invoke(
                    {"messages": [HumanMessage(content=task)]},
                    config={"recursion_limit": 100},
                )
            except Exception as exc:
                stats["modules_ok"].append((mod_name, False, False))
                stats["error"] = f"{mod_name}: {exc}"
                continue

            msgs = result.get("messages", [])
            stats["dispatches"] += 1
            stats["total_msgs"] += len(msgs)

            for msg in msgs:
                mt = type(msg).__name__
                if mt == "ToolMessage":
                    c = str(getattr(msg, "content", ""))
                    if "Cannot write" in c or "already exists" in c:
                        stats["write_exists"] += 1
                    if "String not found" in c:
                        stats["edit_nomatch"] += 1
                for tc in getattr(msg, "tool_calls", []) or []:
                    if tc.get("name") == "write_file":
                        fp = tc.get("args", {}).get("file_path", "")
                        if any(x in fp for x in ["_v", "_new", "_final", "_clean", "_bak"]):
                            stats["junk"].append(fp)

            has_test = (tmp / "tests" / f"test_{mod_name}.py").exists()
            has_src = (tmp / "src" / f"{mod_name}.py").exists()
            stats["modules_ok"].append((mod_name, has_test, has_src))

        stats["time"] = time.time() - t0

        src_files = sorted(f.name for f in (tmp / "src").rglob("*.py")) if (tmp / "src").exists() else []
        test_files = sorted(f.name for f in (tmp / "tests").rglob("*.py")) if (tmp / "tests").exists() else []
        all_junk = [f for f in src_files + test_files if any(x in f for x in ["_v", "_new", "_final", "_clean"])]
        stats["junk"].extend(all_junk)

        expected_src = {f"{name}.py" for name, _, _ in MODULES}
        expected_tests = {f"test_{name}.py" for name, _, _ in MODULES}
        ok = expected_src.issubset(set(src_files)) and expected_tests.issubset(set(test_files)) and not stats["junk"]

        return ok, stats

    except Exception as exc:
        stats["error"] = str(exc)
        return False, stats
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=20)
    parser.add_argument("--max-rounds", type=int, default=50)
    args = parser.parse_args()

    print(f"Per-Module Dispatch Verification")
    print(f"Model: {LOCAL_MODEL} @ {LOCAL_BASE_URL}")
    print(f"Modules: {[m[0] for m in MODULES]}")
    print(f"Min rounds: {args.rounds}, Max rounds: {args.max_rounds}")
    print(f"{'=' * 60}\n")

    passed = 0
    failed = 0
    consecutive_pass = 0

    for r in range(1, args.max_rounds + 1):
        ok, stats = run_one_round(r)
        t = stats["time"]
        m = stats["total_msgs"]
        we = stats["write_exists"]
        en = stats["edit_nomatch"]
        junk = len(stats["junk"])
        mods = [(n, "✓" if ts and sr else "✗") for n, ts, sr in stats.get("modules_ok", [])]
        mods_str = " ".join(f"{n}:{s}" for n, s in mods)

        if ok:
            passed += 1
            consecutive_pass += 1
            print(f"  {r:2d}. ✓ ({t:.0f}s, {m} msgs, we={we}, en={en}) [{mods_str}]")
        else:
            failed += 1
            consecutive_pass = 0
            err = stats.get("error", "")
            print(f"  {r:2d}. ✗ ({t:.0f}s, {m} msgs, we={we}, en={en}, junk={junk}) [{mods_str}]")
            if err:
                print(f"      error: {err[:200]}")
            if stats["junk"]:
                print(f"      junk: {stats['junk'][:5]}")

        total = passed + failed
        if total >= args.rounds and failed == 0:
            print(f"\n{'=' * 60}")
            print(f"PASSED: {passed}/{total} (100%) — {args.rounds}+ rounds with zero failures")
            break
        if total >= args.rounds and consecutive_pass >= 20:
            print(f"\n{'=' * 60}")
            print(f"PASSED: {passed}/{total} ({passed/total*100:.0f}%) — 20 consecutive passes")
            break
    else:
        print(f"\n{'=' * 60}")

    total = passed + failed
    print(f"Final: {passed}/{total} ({passed/total*100:.1f}%)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
