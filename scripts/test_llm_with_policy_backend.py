"""Test LLM write/read/edit with PolicyBackend applied.

Same tests as test_llm_write_read_edit.py but using our PolicyBackend
wrapper. This isolates whether the PolicyBackend changes break the
LLM's ability to use the file tools correctly.

Usage:
    python scripts/test_llm_with_policy_backend.py
"""

from __future__ import annotations

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


def build_agent_with_policy(root_dir: str, system_prompt: str):
    """Create a deepagents agent with PolicyBackend."""
    from deepagents import create_deep_agent
    from langchain_openai import ChatOpenAI

    from aise.runtime.models import OutputLayout
    from aise.runtime.policy_backend import make_policy_backend

    llm = ChatOpenAI(
        model=LOCAL_MODEL,
        api_key=LOCAL_API_KEY,
        base_url=LOCAL_BASE_URL,
        temperature=0.2,
        max_tokens=4096,
    )
    layout = OutputLayout(paths={"source": "src/", "tests": "tests/"})
    backend = make_policy_backend(root_dir, layout=layout, agent_name="test_dev")

    agent = create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        backend=backend,
        name="test_agent",
    )
    return agent, backend


def invoke(agent, prompt: str) -> str:
    from langchain_core.messages import AIMessage, HumanMessage

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
        return f"ERROR: {exc}"


def count_tool_calls(agent, prompt: str) -> dict:
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


# ─── Tests ───────────────────────────────────────────────────────────────


def test_1_basic_write(tmp: Path) -> tuple[bool, str]:
    """Write a file via PolicyBackend."""
    agent, _ = build_agent_with_policy(str(tmp), "You are a helpful coding assistant.")
    invoke(agent, 'Create a file `/src/hello.py` containing: print("hello world")')
    target = tmp / "src" / "hello.py"
    if target.exists() and "hello" in target.read_text():
        return True, f"File created: {target.read_text().strip()}"
    return False, f"Exists={target.exists()}"


def test_2_read_returns_raw_content(tmp: Path) -> tuple[bool, str]:
    """PolicyBackend read_file should return raw content (no line numbers)."""
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")

    agent, backend = build_agent_with_policy(
        str(tmp), "You are a coding assistant."
    )
    # Read the file through the backend directly
    content = backend.read("src/calc.py")
    has_line_numbers = content.strip().startswith("     1")
    if has_line_numbers:
        return False, f"read_file returns line numbers! Content: {content[:200]!r}"
    if "def add" in content:
        return True, f"Raw content returned: {content.strip()!r}"
    return False, f"Unexpected content: {content[:200]!r}"


def test_3_edit_after_read(tmp: Path) -> tuple[bool, str]:
    """LLM reads file via PolicyBackend, then edits it. old_string should match."""
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n")

    agent, _ = build_agent_with_policy(
        str(tmp),
        "You are a coding assistant. To modify files: first read_file, then edit_file "
        "with the exact old_string from the read output.",
    )
    invoke(
        agent,
        'Read `/src/calc.py`, then use edit_file to rename the function from `add` to `sum_two`.',
    )
    content = (tmp / "src" / "calc.py").read_text()
    if "sum_two" in content:
        return True, f"Edit succeeded: {content.strip()}"
    return False, f"Edit failed. Content: {content.strip()}"


def test_4_write_overwrite_blocked(tmp: Path) -> tuple[bool, str]:
    """Write to existing file should fail, LLM should use edit_file."""
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "app.py").write_text("VERSION = 1\n")

    agent, _ = build_agent_with_policy(
        str(tmp),
        "You are a coding assistant. If write_file fails because file exists, "
        "use read_file then edit_file. Never invent new filenames.",
    )
    result = count_tool_calls(
        agent,
        'Change VERSION from 1 to 2 in `/src/app.py`.',
    )
    content = (tmp / "src" / "app.py").read_text()
    has_v2 = "2" in content

    # Check: did it create any *_v2 or similar junk files?
    junk = [f for f in (tmp / "src").iterdir() if f.name != "app.py"]

    if has_v2 and not junk:
        return True, f"Updated correctly. Counts={result['counts']}"
    return False, (
        f"has_v2={has_v2}, junk_files={[f.name for f in junk]}, "
        f"counts={result['counts']}, errors={result['errors'][:2]}"
    )


def test_5_fix_bug(tmp: Path) -> tuple[bool, str]:
    """Fix a bug using read→edit through PolicyBackend."""
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "tests").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "math_utils.py").write_text(
        "def factorial(n):\n"
        "    if n <= 0:\n"
        "        return 1\n"
        "    result = 1\n"
        "    for i in range(1, n):  # BUG: should be range(1, n+1)\n"
        "        result *= i\n"
        "    return result\n"
    )

    agent, _ = build_agent_with_policy(
        str(tmp),
        "You fix bugs. Read the file, find the bug, use edit_file to fix only the buggy line.",
    )
    invoke(
        agent,
        "FAILED tests/test_math.py::test_factorial_5 - assert 24 == 120\n"
        "Read `/src/math_utils.py`, find the off-by-one bug, fix it with edit_file.",
    )
    content = (tmp / "src" / "math_utils.py").read_text()
    if "n+1" in content or "n + 1" in content:
        return True, f"Bug fixed: {content.strip()}"
    return False, f"Not fixed:\n{content}"


# ─── Runner ──────────────────────────────────────────────────────────────


TESTS = [
    ("1. Basic write via PolicyBackend", test_1_basic_write),
    ("2. read_file returns raw content (no line numbers)", test_2_read_returns_raw_content),
    ("3. Read → Edit cycle", test_3_edit_after_read),
    ("4. Write blocked → switch to edit (no junk files)", test_4_write_overwrite_blocked),
    ("5. Fix bug via read → edit", test_5_fix_bug),
]


def main() -> int:
    print(f"Testing LLM with PolicyBackend")
    print(f"Model: {LOCAL_MODEL} @ {LOCAL_BASE_URL}")
    print(f"{'=' * 60}\n")

    passed = 0
    failed = 0

    for name, test_fn in TESTS:
        tmp = Path(tempfile.mkdtemp(prefix="llm_policy_test_"))
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
