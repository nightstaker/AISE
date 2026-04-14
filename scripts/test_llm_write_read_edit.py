"""Test LLM's ability to use write_file, read_file, edit_file correctly.

This script creates a deepagents agent with a FilesystemBackend and
gives it a series of tasks that require the write→read→edit cycle.
It checks whether the LLM can:

1. Write a new file
2. Read the file back
3. Edit a specific part of the file (requires matching old_string exactly)
4. Handle "already exists" error and use edit_file instead
5. Fix a bug given test failure output (read→diagnose→edit)

Each test is a self-contained scenario. Results are printed as PASS/FAIL
with diagnostic details on failure.

Usage:
    python scripts/test_llm_write_read_edit.py

    # Override model/endpoint:
    AISE_LOCAL_BASE_URL=http://127.0.0.1:8088/v1 AISE_LOCAL_MODEL=qwen3.5 python scripts/test_llm_write_read_edit.py
"""

from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

LOCAL_BASE_URL = os.environ.get("AISE_LOCAL_BASE_URL", "http://127.0.0.1:8088/v1")
LOCAL_MODEL = os.environ.get("AISE_LOCAL_MODEL", "qwen3.5")
LOCAL_API_KEY = os.environ.get("AISE_LOCAL_API_KEY", "local-no-key-required")


def build_agent(root_dir: str, system_prompt: str):
    """Create a deepagents agent with FilesystemBackend."""
    from deepagents import create_deep_agent
    from deepagents.backends import FilesystemBackend
    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model=LOCAL_MODEL,
        api_key=LOCAL_API_KEY,
        base_url=LOCAL_BASE_URL,
        temperature=0.2,
        max_tokens=4096,
    )
    backend = FilesystemBackend(root_dir=root_dir, virtual_mode=True)
    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        backend=backend,
        name="test_agent",
    )
    return agent, backend


def invoke(agent, prompt: str, max_retries: int = 1) -> str:
    """Invoke the agent and extract text response."""
    from langchain_core.messages import AIMessage, HumanMessage

    for attempt in range(max_retries + 1):
        try:
            result = agent.invoke({"messages": [HumanMessage(content=prompt)]})
            messages = result.get("messages", [])
            for msg in reversed(messages):
                if isinstance(msg, AIMessage):
                    text = msg.content if isinstance(msg.content, str) else ""
                    if text.strip():
                        return text
            return ""
        except Exception as exc:
            if attempt == max_retries:
                return f"ERROR: {exc}"
    return ""


def count_tool_calls(agent, prompt: str) -> dict:
    """Invoke and count tool calls by name."""
    from langchain_core.messages import AIMessage, HumanMessage

    result = agent.invoke({"messages": [HumanMessage(content=prompt)]})
    messages = result.get("messages", [])
    counts: dict[str, int] = {}
    files_written: list[str] = []
    errors: list[str] = []

    for msg in messages:
        if isinstance(msg, AIMessage):
            for tc in getattr(msg, "tool_calls", []) or []:
                name = tc.get("name", "")
                counts[name] = counts.get(name, 0) + 1
                if name == "write_file":
                    files_written.append(tc.get("args", {}).get("file_path", "?"))
        # Check tool results for errors
        msg_type = type(msg).__name__
        if msg_type == "ToolMessage":
            content = getattr(msg, "content", "")
            if isinstance(content, str) and ("Error" in content or "Cannot write" in content):
                errors.append(content[:150])

    return {
        "counts": counts,
        "files_written": files_written,
        "errors": errors,
        "total_messages": len(messages),
    }


# ─── Test Scenarios ──────────────────────────────────────────────────────


def test_1_basic_write(tmp: Path) -> tuple[bool, str]:
    """Can the LLM write a file with write_file?"""
    agent, backend = build_agent(str(tmp), "You are a helpful coding assistant.")
    invoke(agent, 'Create a file `/src/hello.py` with content: print("hello world")')
    target = tmp / "src" / "hello.py"
    if target.exists() and "hello" in target.read_text():
        return True, f"File created: {target.read_text().strip()}"
    return False, f"File not found or wrong content. Exists={target.exists()}"


def test_2_read_after_write(tmp: Path) -> tuple[bool, str]:
    """Can the LLM write a file then read it back and report content?"""
    agent, backend = build_agent(
        str(tmp),
        "You are a coding assistant. Always use tools to interact with files.",
    )
    response = invoke(
        agent,
        'First, write a file `/src/calc.py` with this content:\n'
        '```\ndef add(a, b):\n    return a + b\n```\n'
        'Then read the file back with read_file and tell me what the function name is.',
    )
    target = tmp / "src" / "calc.py"
    file_ok = target.exists() and "def add" in target.read_text()
    response_ok = "add" in response.lower()
    if file_ok and response_ok:
        return True, "Write + read + report succeeded"
    return False, f"file_ok={file_ok}, response_mentions_add={response_ok}, response={response[:200]}"


def test_3_edit_existing_file(tmp: Path) -> tuple[bool, str]:
    """Can the LLM use edit_file to modify an existing file?"""
    # Pre-create the file
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")

    agent, backend = build_agent(
        str(tmp),
        "You are a coding assistant. Use edit_file to modify existing files. "
        "Do NOT use write_file on files that already exist.",
    )
    invoke(
        agent,
        'The file `/src/calc.py` has a function `add`. '
        'Use edit_file to change the function name from `add` to `sum_two`. '
        'First read_file to see the exact content, then edit_file with the exact old_string.',
    )
    content = (tmp / "src" / "calc.py").read_text()
    if "sum_two" in content and "add" not in content.replace("sum_two", ""):
        return True, f"Edit succeeded: {content.strip()}"
    return False, f"Edit failed. Content: {content.strip()}"


def test_4_write_already_exists_then_edit(tmp: Path) -> tuple[bool, str]:
    """When write_file fails with 'already exists', does the LLM switch to edit_file?"""
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "app.py").write_text("VERSION = 1\n")

    agent, backend = build_agent(
        str(tmp),
        "You are a coding assistant. If write_file says a file already exists, "
        "use read_file then edit_file instead. Never create a new filename.",
    )
    result = count_tool_calls(
        agent,
        'Update `/src/app.py` to change VERSION from 1 to 2. Use write_file first.',
    )
    content = (tmp / "src" / "app.py").read_text()
    has_v2 = "VERSION = 2" in content or "VERSION=2" in content or "2" in content

    used_edit = result["counts"].get("edit_file", 0) > 0
    wrote_new_files = any(p != "/src/app.py" for p in result["files_written"] if "app" in p)

    if has_v2 and not wrote_new_files:
        return True, f"Correctly updated. Used edit={used_edit}. Counts={result['counts']}"
    return False, (
        f"has_v2={has_v2}, wrote_new_files={wrote_new_files}, "
        f"counts={result['counts']}, errors={result['errors'][:2]}"
    )


def test_5_fix_bug_from_test_output(tmp: Path) -> tuple[bool, str]:
    """Given pytest failure output, can the LLM read code and fix the bug?"""
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "tests").mkdir(parents=True, exist_ok=True)

    # Buggy code: off-by-one
    (tmp / "src" / "math_utils.py").write_text(
        "def factorial(n):\n"
        "    if n <= 0:\n"
        "        return 1\n"
        "    result = 1\n"
        "    for i in range(1, n):  # BUG: should be range(1, n+1)\n"
        "        result *= i\n"
        "    return result\n"
    )
    (tmp / "tests" / "test_math.py").write_text(
        "from src.math_utils import factorial\n\n"
        "def test_factorial_5():\n"
        "    assert factorial(5) == 120\n\n"
        "def test_factorial_0():\n"
        "    assert factorial(0) == 1\n"
    )

    agent, backend = build_agent(
        str(tmp),
        "You are a developer who fixes bugs. "
        "Read the failing code, identify the bug, then use edit_file to fix it. "
        "Do NOT rewrite the whole file. Only change the buggy line.",
    )
    invoke(
        agent,
        "pytest output:\n"
        "```\n"
        "FAILED tests/test_math.py::test_factorial_5 - assert 24 == 120\n"
        "```\n"
        "The function `factorial(5)` returns 24 instead of 120. "
        "Read `/src/math_utils.py`, find the bug, and fix it with edit_file.",
    )

    content = (tmp / "src" / "math_utils.py").read_text()
    # Check if the fix was applied: range(1, n+1) or range(1, n + 1)
    if "n+1" in content or "n + 1" in content:
        return True, f"Bug fixed: {content.strip()}"
    return False, f"Bug not fixed. Content:\n{content}"


# ─── Runner ──────────────────────────────────────────────────────────────


TESTS = [
    ("1. Basic write_file", test_1_basic_write),
    ("2. Write then read", test_2_read_after_write),
    ("3. Edit existing file (read→edit)", test_3_edit_existing_file),
    ("4. Write fails → switch to edit", test_4_write_already_exists_then_edit),
    ("5. Fix bug from pytest output", test_5_fix_bug_from_test_output),
]


def main() -> int:
    print(f"Testing LLM write/read/edit capabilities")
    print(f"Model: {LOCAL_MODEL} @ {LOCAL_BASE_URL}")
    print(f"{'=' * 60}\n")

    passed = 0
    failed = 0

    for name, test_fn in TESTS:
        tmp = Path(tempfile.mkdtemp(prefix="llm_test_"))
        try:
            print(f"[TEST] {name}")
            ok, detail = test_fn(tmp)
            if ok:
                print(f"  PASS: {detail}\n")
                passed += 1
            else:
                print(f"  FAIL: {detail}\n")
                failed += 1
        except Exception as exc:
            print(f"  ERROR: {exc}\n")
            failed += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    print(f"{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed out of {len(TESTS)}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
