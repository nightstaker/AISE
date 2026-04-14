"""Stability test: run write/read/edit tests multiple rounds.

Runs both the raw FilesystemBackend and PolicyBackend test suites
N rounds each, collecting pass/fail statistics per test case.

Usage:
    python scripts/test_llm_stability.py              # 5 rounds (default)
    python scripts/test_llm_stability.py --rounds 10  # 10 rounds
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
LOCAL_MODEL = os.environ.get("AISE_LOCAL_MODEL", "qwen3.5")
LOCAL_API_KEY = os.environ.get("AISE_LOCAL_API_KEY", "local-no-key-required")


# ─── Helpers ─────────────────────────────────────────────────────────────


def _build_raw_agent(root_dir: str, system_prompt: str):
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=LOCAL_MODEL, api_key=LOCAL_API_KEY,
        base_url=LOCAL_BASE_URL, temperature=0.2, max_tokens=4096,
    )
    backend = FilesystemBackend(root_dir=root_dir, virtual_mode=True)
    return create_deep_agent(model=llm, system_prompt=system_prompt, backend=backend, name="raw")


def _build_policy_agent(root_dir: str, system_prompt: str):
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


def _invoke(agent, prompt: str) -> str:
    from langchain_core.messages import AIMessage, HumanMessage

    result = agent.invoke({"messages": [HumanMessage(content=prompt)]})
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage):
            text = msg.content if isinstance(msg.content, str) else ""
            if text.strip():
                return text
    return ""


# ─── Test cases ──────────────────────────────────────────────────────────


def _test_write(build_fn, tmp: Path) -> tuple[bool, str]:
    agent = build_fn(str(tmp), "You are a coding assistant.")
    _invoke(agent, 'Create `/src/hello.py` with: print("hello")')
    f = tmp / "src" / "hello.py"
    if f.exists() and "hello" in f.read_text():
        return True, "ok"
    return False, f"exists={f.exists()}"


def _test_read_edit(build_fn, tmp: Path) -> tuple[bool, str]:
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    agent = build_fn(
        str(tmp),
        "You modify files. First read_file, then edit_file with exact old_string.",
    )
    _invoke(agent, 'Read `/src/calc.py`, then edit_file to rename `add` to `sum_two`.')
    content = (tmp / "src" / "calc.py").read_text()
    if "sum_two" in content:
        return True, "ok"
    return False, f"content={content.strip()!r}"


def _test_write_blocked_edit(build_fn, tmp: Path) -> tuple[bool, str]:
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "app.py").write_text("VERSION = 1\n")
    agent = build_fn(
        str(tmp),
        "If write_file fails (file exists), use read_file then edit_file. "
        "Never create new filenames.",
    )
    _invoke(agent, 'Change VERSION to 2 in `/src/app.py`.')
    content = (tmp / "src" / "app.py").read_text()
    junk = [f.name for f in (tmp / "src").iterdir() if f.name != "app.py" and not f.name.endswith(".pyc")]
    if "2" in content and not junk:
        return True, "ok"
    return False, f"content={content.strip()!r}, junk={junk}"


def _test_fix_bug(build_fn, tmp: Path) -> tuple[bool, str]:
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
    _invoke(
        agent,
        "FAILED: factorial(5) returned 24, expected 120.\n"
        "Read `/src/math_utils.py`, find the off-by-one bug, fix it.",
    )
    content = (tmp / "src" / "math_utils.py").read_text()
    if "n+1" in content or "n + 1" in content:
        return True, "ok"
    return False, f"content has range: {'range' in content}"


TESTS = [
    ("write", _test_write),
    ("read→edit", _test_read_edit),
    ("write_blocked→edit", _test_write_blocked_edit),
    ("fix_bug", _test_fix_bug),
]


# ─── Runner ──────────────────────────────────────────────────────────────


def run_suite(suite_name: str, build_fn, rounds: int) -> dict[str, list[bool]]:
    results: dict[str, list[bool]] = {name: [] for name, _ in TESTS}

    for r in range(1, rounds + 1):
        print(f"\n  Round {r}/{rounds}")
        for name, test_fn in TESTS:
            tmp = Path(tempfile.mkdtemp(prefix=f"stab_{suite_name}_"))
            try:
                t0 = time.time()
                ok, detail = test_fn(build_fn, tmp)
                dt = time.time() - t0
                mark = "✓" if ok else "✗"
                print(f"    {mark} {name} ({dt:.1f}s){'' if ok else ' — ' + detail}")
                results[name].append(ok)
            except Exception as exc:
                print(f"    ✗ {name} — ERROR: {exc}")
                results[name].append(False)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)

    return results


def print_summary(suite_name: str, results: dict[str, list[bool]], rounds: int):
    print(f"\n{'─' * 50}")
    print(f"  {suite_name}: {rounds} rounds")
    print(f"{'─' * 50}")
    all_pass = 0
    all_total = 0
    for name, outcomes in results.items():
        p = sum(outcomes)
        t = len(outcomes)
        rate = p / t * 100 if t else 0
        bar = "".join("✓" if o else "✗" for o in outcomes)
        print(f"  {name:25s}  {p}/{t} ({rate:5.1f}%)  {bar}")
        all_pass += p
        all_total += t
    rate = all_pass / all_total * 100 if all_total else 0
    print(f"  {'TOTAL':25s}  {all_pass}/{all_total} ({rate:.1f}%)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()
    rounds = args.rounds

    print(f"LLM Stability Test — {rounds} rounds per suite")
    print(f"Model: {LOCAL_MODEL} @ {LOCAL_BASE_URL}")

    print(f"\n{'=' * 50}")
    print("Suite A: Raw FilesystemBackend")
    print(f"{'=' * 50}")
    raw_results = run_suite("raw", _build_raw_agent, rounds)

    print(f"\n{'=' * 50}")
    print("Suite B: PolicyBackend")
    print(f"{'=' * 50}")
    policy_results = run_suite("policy", _build_policy_agent, rounds)

    print_summary("Raw FilesystemBackend", raw_results, rounds)
    print_summary("PolicyBackend", policy_results, rounds)

    total_fail = sum(not o for outcomes in raw_results.values() for o in outcomes)
    total_fail += sum(not o for outcomes in policy_results.values() for o in outcomes)
    return 0 if total_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
