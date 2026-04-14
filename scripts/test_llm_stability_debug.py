"""Debug version: captures full message trace when fix_bug fails under PolicyBackend.

Runs ONLY the fix_bug test case with PolicyBackend, captures every message
in the agent loop, and dumps a detailed trace when the test fails.

Usage:
    python scripts/test_llm_stability_debug.py --rounds 10
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

LOCAL_BASE_URL = os.environ.get("AISE_LOCAL_BASE_URL", "http://127.0.0.1:8088/v1")
LOCAL_MODEL = os.environ.get("AISE_LOCAL_MODEL", "qwen3.5")
LOCAL_API_KEY = os.environ.get("AISE_LOCAL_API_KEY", "local-no-key-required")


def build_policy_agent(root_dir: str, system_prompt: str):
    from deepagents import create_deep_agent
    from langchain_openai import ChatOpenAI

    from aise.runtime.models import OutputLayout
    from aise.runtime.policy_backend import make_policy_backend

    llm = ChatOpenAI(
        model=LOCAL_MODEL, api_key=LOCAL_API_KEY,
        base_url=LOCAL_BASE_URL, temperature=0.2, max_tokens=4096,
    )
    layout = OutputLayout(paths={"source": "src/", "tests": "tests/"})
    backend = make_policy_backend(root_dir, layout=layout, agent_name="dev")
    return create_deep_agent(model=llm, system_prompt=system_prompt, backend=backend, name="policy")


def build_raw_agent(root_dir: str, system_prompt: str):
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=LOCAL_MODEL, api_key=LOCAL_API_KEY,
        base_url=LOCAL_BASE_URL, temperature=0.2, max_tokens=4096,
    )
    backend = FilesystemBackend(root_dir=root_dir, virtual_mode=True)
    return create_deep_agent(model=llm, system_prompt=system_prompt, backend=backend, name="raw")


def run_fix_bug(build_fn, tmp: Path) -> tuple[bool, str, list[dict]]:
    from langchain_core.messages import AIMessage, HumanMessage

    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "math_utils.py").write_text(
        "def factorial(n):\n"
        "    if n <= 0:\n"
        "        return 1\n"
        "    result = 1\n"
        "    for i in range(1, n):  # BUG\n"
        "        result *= i\n"
        "    return result\n"
    )

    agent = build_fn(
        str(tmp),
        "You fix bugs. Read the file, find the bug, fix with edit_file.",
    )
    result = agent.invoke({"messages": [HumanMessage(
        content=(
            "FAILED: factorial(5) returned 24, expected 120.\n"
            "Read `/src/math_utils.py`, find the off-by-one bug, fix it."
        )
    )]})

    messages = result.get("messages", [])
    trace = []
    for i, msg in enumerate(messages):
        entry = {"idx": i, "type": type(msg).__name__}
        content = getattr(msg, "content", "")
        if isinstance(content, str):
            entry["content"] = content
        elif isinstance(content, list):
            entry["content"] = str(content)[:500]
        tcs = getattr(msg, "tool_calls", None)
        if tcs:
            entry["tool_calls"] = []
            for tc in tcs:
                tc_entry = {"name": tc.get("name", ""), "args": {}}
                for k, v in tc.get("args", {}).items():
                    tc_entry["args"][k] = v if len(str(v)) < 300 else str(v)[:300] + "..."
                entry["tool_calls"].append(tc_entry)
        name = getattr(msg, "name", None)
        if name:
            entry["name"] = name
        trace.append(entry)

    content = (tmp / "src" / "math_utils.py").read_text()
    ok = "n+1" in content or "n + 1" in content
    return ok, content, trace


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=10)
    args = parser.parse_args()

    print(f"fix_bug stability debug — {args.rounds} rounds")
    print(f"Model: {LOCAL_MODEL} @ {LOCAL_BASE_URL}")

    for suite_name, build_fn in [("Raw", build_raw_agent), ("PolicyBackend", build_policy_agent)]:
        print(f"\n{'=' * 50}")
        print(f"Suite: {suite_name}")
        print(f"{'=' * 50}")

        pass_count = 0
        fail_count = 0

        for r in range(1, args.rounds + 1):
            tmp = Path(tempfile.mkdtemp(prefix=f"debug_{suite_name}_"))
            try:
                t0 = time.time()
                ok, final_content, trace = run_fix_bug(build_fn, tmp)
                dt = time.time() - t0

                if ok:
                    print(f"  Round {r}: ✓ ({dt:.1f}s, {len(trace)} msgs)")
                    pass_count += 1
                else:
                    fail_count += 1
                    print(f"  Round {r}: ✗ ({dt:.1f}s, {len(trace)} msgs)")
                    print(f"    Final file content:")
                    for line in final_content.strip().split("\n"):
                        print(f"      {line}")
                    print(f"    Message trace:")
                    for entry in trace:
                        idx = entry["idx"]
                        mtype = entry["type"]
                        tcs = entry.get("tool_calls", [])
                        name = entry.get("name", "")
                        content = entry.get("content", "")

                        if tcs:
                            for tc in tcs:
                                tc_name = tc["name"]
                                tc_args_keys = list(tc["args"].keys())
                                if tc_name == "write_file":
                                    fp = tc["args"].get("file_path", "?")
                                    cl = len(tc["args"].get("content", ""))
                                    print(f"      [{idx}] {mtype} → write_file({fp}) len={cl}")
                                elif tc_name == "edit_file":
                                    fp = tc["args"].get("file_path", "?")
                                    ol = len(tc["args"].get("old_string", ""))
                                    nl = len(tc["args"].get("new_string", ""))
                                    print(f"      [{idx}] {mtype} → edit_file({fp}) old={ol} new={nl}")
                                elif tc_name == "read_file":
                                    fp = tc["args"].get("file_path", "?")
                                    print(f"      [{idx}] {mtype} → read_file({fp})")
                                else:
                                    print(f"      [{idx}] {mtype} → {tc_name}({tc_args_keys})")
                        elif mtype == "ToolMessage":
                            preview = content[:120].replace("\n", "\\n")
                            err = "ERR" if "Error" in content or "Cannot" in content else "ok"
                            print(f"      [{idx}] Tool({name}) [{err}]: {preview}")
                        elif mtype == "HumanMessage":
                            print(f"      [{idx}] Human: {content[:80]}...")
                        elif content:
                            print(f"      [{idx}] {mtype}: {content[:80]}...")
                    print()
            except Exception as exc:
                fail_count += 1
                print(f"  Round {r}: ERROR — {exc}")
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

        total = pass_count + fail_count
        print(f"\n  {suite_name} result: {pass_count}/{total} ({pass_count/total*100:.0f}%)")


if __name__ == "__main__":
    main()
