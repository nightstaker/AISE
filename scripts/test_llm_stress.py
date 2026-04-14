"""Stress test: simulate the real project failure pattern.

Tests the LLM's ability to handle the write→modify cycle with the
NATIVE deepagents FilesystemBackend (no PolicyBackend overrides).

The real failure pattern observed in project traces:

1. LLM writes src/models.py (first write — succeeds)
2. LLM writes tests/test_models.py (first write — succeeds)
3. LLM wants to UPDATE src/models.py → write_file → "already exists"
4. LLM tries edit_file with fabricated old_string → "string not found"
5. LLM falls into a loop: write(exists) → edit(nomatch) → write_new_name → ...

This test checks:
- Scenario A: Write 1 file, then read+edit it (simple modify)
- Scenario B: Write 2 files, then go back and modify the first (the real pattern)
- Scenario C: Write 5 files in TDD order, then modify one (full project simulation)
- Scenario D: Write a file, get "already exists", recover via read+edit

Each scenario runs N rounds. Reports pass rate and failure details.

Usage:
    python scripts/test_llm_stress.py --rounds 10
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


def make_agent(root_dir: str, system_prompt: str):
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
    return create_deep_agent(
        model=llm,
        system_prompt=system_prompt,
        backend=backend,
        name="dev",
    )


def invoke_and_analyze(agent, prompt: str) -> dict:
    from langchain_core.messages import AIMessage, HumanMessage

    t0 = time.time()
    result = agent.invoke({"messages": [HumanMessage(content=prompt)]})
    dt = time.time() - t0
    msgs = result.get("messages", [])

    tool_calls = []
    errors = []
    for msg in msgs:
        for tc in getattr(msg, "tool_calls", []) or []:
            name = tc.get("name", "")
            args = tc.get("args", {})
            tool_calls.append(name)
            if name == "write_file":
                fp = args.get("file_path", "?")
                if "_v" in fp or "_new" in fp or "_final" in fp or "_clean" in fp:
                    errors.append(f"junk_filename:{fp}")
        if type(msg).__name__ == "ToolMessage":
            c = getattr(msg, "content", "")
            if isinstance(c, str):
                if "Cannot write" in c or "already exists" in c:
                    errors.append("write_exists")
                elif "String not found" in c:
                    errors.append("edit_nomatch")

    return {
        "time": dt,
        "msg_count": len(msgs),
        "tool_calls": tool_calls,
        "write_count": tool_calls.count("write_file"),
        "edit_count": tool_calls.count("edit_file"),
        "read_count": tool_calls.count("read_file"),
        "errors": errors,
        "write_exists": errors.count("write_exists"),
        "edit_nomatch": errors.count("edit_nomatch"),
        "junk_files": [e for e in errors if e.startswith("junk_filename:")],
    }


# ─── Scenarios ───────────────────────────────────────────────────────────

SIMPLE_PROMPT = (
    "You are a developer. Use write_file for new files. "
    "If write_file says 'already exists', use read_file to see the content, "
    "then edit_file with the exact old_string from read output. "
    "Never create files with _v2, _new, _final suffixes."
)

# The real system prompt that deepagents injects for the developer agent,
# extracted from an actual project trace. ~9000 chars.
_REAL_PROMPT_PATH = Path(__file__).parent.parent / "src" / "aise" / "agents" / "developer.md"


def _load_real_prompt() -> str:
    """Build a system prompt that matches the real project runtime.

    Combines the developer.md prompt with the deepagents boilerplate
    that gets injected (write_todos docs, skills system docs, task
    subagent docs, conventions, tool usage docs).
    """
    agent_prompt = _REAL_PROMPT_PATH.read_text(encoding="utf-8")
    # Extract content after "# System Prompt" and before "## Skills"
    import re

    match = re.search(r"# System Prompt\s*\n(.*?)(?=\n## Skills|\Z)", agent_prompt, re.DOTALL)
    custom = match.group(1).strip() if match else agent_prompt

    # Append the deepagents framework boilerplate (same text injected at runtime)
    boilerplate = """
## `write_todos`

You have access to the `write_todos` tool to help you manage and plan complex objectives.
Use this tool for complex objectives to ensure that you are tracking each necessary step and giving the user visibility into your progress.
This tool is very helpful for planning complex objectives, and for breaking down these larger complex objectives into smaller steps.

It is critical that you mark todos as completed as soon as you are done with a step. Do not batch up multiple steps before marking them as completed.
For simple objectives that only require a few steps, it is better to just complete the objective directly and NOT use this tool.
Writing todos takes time and tokens, use it when it is helpful for managing complex many-step problems! But not for simple few-step requests.

## Important To-Do List Usage Notes to Remember
- The `write_todos` tool should never be called multiple times in parallel.
- Don't be afraid to revise the To-Do list as you go. New information may reveal new tasks that need to be done, or old tasks that are irrelevant.



## Skills System

You have access to a skills library that provides specialized capabilities and domain knowledge.

**_runtime_skills Skills**: `/home/ntstaker/workspace/AISE/src/aise/agents/_runtime_skills` (higher priority)

**Available Skills:**

- **tdd**: Test-Driven Development workflow with 1:1 source-to-test file mapping

**How to Use Skills (Progressive Disclosure):**

Skills follow a **progressive disclosure** pattern - you see their name and description above, but only read full instructions when needed:

1. **Recognize when a skill applies**: Check if the user's task matches a skill's description
2. **Read the skill's full instructions**: Use the path shown in the skill list above
3. **Follow the skill's instructions**: SKILL.md contains step-by-step workflows, best practices, and examples
4. **Access supporting files**: Skills may include helper scripts, configs, or reference docs - use absolute paths

**When to Use Skills:**
- User's request matches a skill's domain (e.g., "research X" -> web-research skill)
- You need specialized knowledge or structured workflows
- A skill provides proven patterns for complex tasks

**Executing Skill Scripts:**
Skills may contain Python scripts or other executable files. Always use absolute paths from the skill list.

Remember: Skills make you more capable and consistent. When in doubt, check if a skill exists for the task!


## Following Conventions

- Read files before editing — understand existing content before making changes
- Mimic existing style, naming conventions, and patterns

## Tool Usage and File Reading

Follow the tool docs for the available tools. In particular, for filesystem tools, use pagination (offset/limit) when reading large files.

## Filesystem Tools `ls`, `read_file`, `write_file`, `edit_file`, `glob`, `grep`

You have access to a filesystem which you can interact with using these tools.
All file paths must start with a /.

- ls: list files in a directory (requires absolute path)
- read_file: read a file from the filesystem
- write_file: write to a file in the filesystem
- edit_file: edit a file in the filesystem
- glob: find files matching a pattern (e.g., "**/*.py")
- grep: search for text within files


## `task` (subagent spawner)

You have access to a `task` tool to launch short-lived subagents that handle isolated tasks. These agents are ephemeral — they live only for the duration of the task and return a single result.

When to use the task tool:
- When a task is complex and multi-step, and can be fully delegated in isolation
- When a task is independent of other tasks and can run in parallel
- When a task requires focused reasoning or heavy token/context usage that would bloat the orchestrator thread
- When sandboxing improves reliability (e.g. code execution, structured searches, data formatting)
- When you only care about the output of the subagent, and not the intermediate steps

Subagent lifecycle:
1. **Spawn** → Provide clear role, instructions, and expected output
2. **Run** → The subagent completes the task autonomously
3. **Return** → The subagent provides a single structured result
4. **Reconcile** → Incorporate or synthesize the result into the main thread

When NOT to use the task tool:
- If you need to see the intermediate reasoning or steps after the subagent has completed
- If the task is trivial (a few tool calls or simple lookup)
- If delegating does not reduce token usage, complexity, or context switching
- If splitting would add latency without benefit

## Important Task Tool Usage Notes to Remember
- Whenever possible, parallelize the work that you do.
- Remember to use the `task` tool to silo independent tasks within a multi-part objective.
- You should use the `task` tool whenever you have a complex task that will take multiple steps, and is independent from other tasks.

Available subagent types:
- general-purpose: General-purpose agent for researching complex questions, searching for files and content, and executing multi-step tasks.
"""
    return custom + "\n\n" + boilerplate


REAL_PROMPT = _load_real_prompt()
SYSTEM_PROMPT = REAL_PROMPT  # Use real prompt by default


def scenario_a(tmp: Path) -> tuple[bool, str, dict]:
    """Write 1 file, then modify it."""
    agent = make_agent(str(tmp), SYSTEM_PROMPT)
    stats = invoke_and_analyze(
        agent,
        "Step 1: Write `/src/point.py` with:\n"
        "```\nclass Point:\n    def __init__(self, x, y):\n        self.x = x\n        self.y = y\n```\n\n"
        "Step 2: Now modify `/src/point.py` to add a `move(dx, dy)` method that returns a new Point.",
    )
    content = (tmp / "src" / "point.py").read_text() if (tmp / "src" / "point.py").exists() else ""
    ok = "move" in content and not stats["junk_files"]
    detail = f"move={'move' in content}, junk={stats['junk_files']}, exists_err={stats['write_exists']}, nomatch={stats['edit_nomatch']}"
    return ok, detail, stats


def scenario_b(tmp: Path) -> tuple[bool, str, dict]:
    """Write test + src, then go back and modify src (the real project pattern)."""
    agent = make_agent(str(tmp), SYSTEM_PROMPT)
    stats = invoke_and_analyze(
        agent,
        "Step 1: Write `/tests/test_calc.py` with:\n"
        "```python\nfrom src.calc import add, multiply\n\n"
        "def test_add():\n    assert add(2, 3) == 5\n\n"
        "def test_multiply():\n    assert multiply(2, 3) == 6\n```\n\n"
        "Step 2: Write `/src/calc.py` with just the `add` function:\n"
        "```python\ndef add(a, b):\n    return a + b\n```\n\n"
        "Step 3: Now UPDATE `/src/calc.py` to also include the `multiply` function.",
    )
    content = (tmp / "src" / "calc.py").read_text() if (tmp / "src" / "calc.py").exists() else ""
    ok = "multiply" in content and "add" in content and not stats["junk_files"]
    detail = f"has_both={'multiply' in content and 'add' in content}, junk={stats['junk_files']}, exists_err={stats['write_exists']}, nomatch={stats['edit_nomatch']}"
    return ok, detail, stats


def scenario_c(tmp: Path) -> tuple[bool, str, dict]:
    """Write 5 TDD file pairs, then modify one source file."""
    agent = make_agent(str(tmp), SYSTEM_PROMPT)
    stats = invoke_and_analyze(
        agent,
        "Write these files IN ORDER:\n"
        "1. `/tests/test_point.py` — test Point class (x, y attributes)\n"
        "2. `/src/point.py` — Point class with x, y\n"
        "3. `/tests/test_direction.py` — test Direction enum (UP, DOWN, LEFT, RIGHT)\n"
        "4. `/src/direction.py` — Direction enum\n"
        "5. `/tests/test_snake.py` — test Snake class\n"
        "6. `/src/snake.py` — Snake class with body list\n\n"
        "After writing all 6 files, UPDATE `/src/point.py` to add a `move(dx, dy)` method "
        "that returns a new Point(self.x + dx, self.y + dy).",
    )
    point = (tmp / "src" / "point.py").read_text() if (tmp / "src" / "point.py").exists() else ""
    src_files = sorted(f.name for f in (tmp / "src").rglob("*.py")) if (tmp / "src").exists() else []
    test_files = sorted(f.name for f in (tmp / "tests").rglob("*.py")) if (tmp / "tests").exists() else []
    junk = [f for f in src_files + test_files if "_v" in f or "_new" in f or "_final" in f]
    ok = "move" in point and not junk
    detail = f"move={'move' in point}, src={src_files}, tests={test_files}, junk={junk}"
    return ok, detail, stats


def scenario_d(tmp: Path) -> tuple[bool, str, dict]:
    """Pre-create a file, then ask LLM to update it (forced 'already exists' path)."""
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "config.py").write_text("VERSION = 1\nDEBUG = False\n")
    agent = make_agent(str(tmp), SYSTEM_PROMPT)
    stats = invoke_and_analyze(
        agent,
        "The file `/src/config.py` already exists with `VERSION = 1` and `DEBUG = False`.\n"
        "Update it to set `VERSION = 2` and `DEBUG = True`.\n"
        "Remember: the file already exists, so write_file will fail. "
        "Use read_file first, then edit_file.",
    )
    content = (tmp / "src" / "config.py").read_text()
    ok = "2" in content and "True" in content and not stats["junk_files"]
    detail = f"content={content.strip()!r}, junk={stats['junk_files']}, exists_err={stats['write_exists']}, nomatch={stats['edit_nomatch']}"
    return ok, detail, stats


def scenario_e(tmp: Path) -> tuple[bool, str, dict]:
    """Simulate the real project dispatch: long task description with architecture references."""
    agent = make_agent(str(tmp), SYSTEM_PROMPT)
    stats = invoke_and_analyze(
        agent,
        "Implement the core logic for the Commercial Snake App based on the architecture.\n\n"
        "### Architecture Summary:\n"
        "- `src/models.py`: Direction enum (UP/DOWN/LEFT/RIGHT with delta tuples), "
        "Point class (x, y, move method), Snake class (body deque, direction, grow flag), "
        "Food class (position, point_value), GameState enum (PLAYING/PAUSED/GAME_OVER)\n"
        "- `src/collision.py`: CollisionDetector with check_wall, check_self, check_food methods\n"
        "- `src/scoring.py`: ScoreManager with score, level, speed multiplier, difficulty scaling\n"
        "- `src/engine.py`: GameEngine orchestrating Snake, Food, CollisionDetector, ScoreManager\n\n"
        "### Requirements:\n"
        "- FR-1.1: Snake moves continuously in current direction\n"
        "- FR-1.2: Player changes direction (no 180-degree reverse)\n"
        "- FR-1.3: Snake grows when eating food, score increases\n"
        "- FR-1.4: Game over on wall or self collision\n"
        "- FR-2.1: Score = base_points * level_multiplier\n\n"
        "### TDD Approach:\n"
        "For EACH module, write the test file FIRST, then the source file:\n"
        "1. `tests/test_models.py` → `src/models.py`\n"
        "2. `tests/test_collision.py` → `src/collision.py`\n"
        "3. `tests/test_scoring.py` → `src/scoring.py`\n"
        "4. `tests/test_engine.py` → `src/engine.py`\n\n"
        "Each test file tests exactly one source module. Do NOT put all tests in one file.\n"
        "After writing all 8 files, respond with a summary and STOP.",
    )
    src_files = sorted(f.name for f in (tmp / "src").rglob("*.py")) if (tmp / "src").exists() else []
    test_files = sorted(f.name for f in (tmp / "tests").rglob("*.py")) if (tmp / "tests").exists() else []
    junk = [f for f in src_files + test_files if "_v" in f or "_new" in f or "_final" in f or "_clean" in f]
    expected_src = {"models.py", "collision.py", "scoring.py", "engine.py"}
    expected_tests = {"test_models.py", "test_collision.py", "test_scoring.py", "test_engine.py"}
    has_src = expected_src.issubset(set(src_files))
    has_tests = expected_tests.issubset(set(test_files))
    ok = has_src and has_tests and not junk
    detail = f"src={src_files}, tests={test_files}, junk={junk}"
    return ok, detail, stats


def scenario_f(tmp: Path) -> tuple[bool, str, dict]:
    """Simulate fix iteration: pre-existing code + pytest failure output."""
    (tmp / "src").mkdir(parents=True, exist_ok=True)
    (tmp / "tests").mkdir(parents=True, exist_ok=True)
    (tmp / "src" / "models.py").write_text(
        "from enum import Enum\n\n"
        "class Direction(Enum):\n"
        "    UP = (0, -1)\n"
        "    DOWN = (0, 1)\n"
        "    LEFT = (-1, 0)\n"
        "    RIGHT = (1, 0)\n\n"
        "class Snake:\n"
        "    def __init__(self, start_pos, length=3):\n"
        "        self.body = [start_pos]\n"
        "        for i in range(1, length):\n"
        "            self.body.append((start_pos[0] - i, start_pos[1]))\n"
        "        self.direction = Direction.RIGHT\n"
        "        self.grow_flag = False\n\n"
        "    def move(self):\n"
        "        dx, dy = self.direction.value\n"
        "        head = self.body[0]\n"
        "        new_head = (head[0] + dx, head[1] + dy)\n"
        "        self.body.insert(0, new_head)\n"
        "        if not self.grow_flag:\n"
        "            self.body.pop()\n"
        "        self.grow_flag = False\n\n"
        "    def grow(self):\n"
        "        self.grow_flag = True\n"
    )
    (tmp / "tests" / "test_models.py").write_text(
        "from src.models import Snake, Direction\n\n"
        "def test_snake_move_right():\n"
        "    s = Snake((5, 5), length=3)\n"
        "    s.move()\n"
        "    assert s.body[0] == (6, 5)\n"
        "    assert len(s.body) == 3\n\n"
        "def test_snake_grow():\n"
        "    s = Snake((5, 5), length=3)\n"
        "    s.grow()\n"
        "    s.move()\n"
        "    assert len(s.body) == 4\n\n"
        "def test_snake_change_direction():\n"
        "    s = Snake((5, 5), length=3)\n"
        "    s.direction = Direction.DOWN\n"
        "    s.move()\n"
        "    assert s.body[0] == (5, 6)\n\n"
        "def test_no_reverse():\n"
        "    s = Snake((5, 5), length=3)\n"
        "    # Moving RIGHT, try to go LEFT (should be prevented)\n"
        "    s.direction = Direction.LEFT  # BUG: no reverse check\n"
        "    s.move()\n"
        "    # Should still be moving RIGHT, not LEFT\n"
        "    assert s.body[0] == (6, 5)  # This will FAIL because there's no reverse check\n"
    )
    agent = make_agent(str(tmp), SYSTEM_PROMPT)
    stats = invoke_and_analyze(
        agent,
        "The pytest output shows:\n"
        "```\n"
        "FAILED tests/test_models.py::test_no_reverse - assert (4, 5) == (6, 5)\n"
        "3 passed, 1 failed\n"
        "```\n\n"
        "The Snake class has no reverse-direction prevention. When moving RIGHT, "
        "setting direction to LEFT should be ignored.\n\n"
        "Fix `src/models.py`: add a `change_direction(new_dir)` method that prevents "
        "180-degree reversal. Update `tests/test_models.py::test_no_reverse` to use "
        "the new `change_direction` method.\n\n"
        "Use read_file to see current code, then edit_file to fix.",
    )
    content = (tmp / "src" / "models.py").read_text()
    test_content = (tmp / "tests" / "test_models.py").read_text()
    has_fix = "change_direction" in content or "reverse" in content or "opposite" in content
    junk = [f.name for f in (tmp / "src").iterdir() if "_v" in f.name or "_new" in f.name or "_final" in f.name]
    ok = has_fix and not junk
    detail = f"has_fix={has_fix}, junk={junk}, exists_err={stats['write_exists']}, nomatch={stats['edit_nomatch']}"
    return ok, detail, stats


SCENARIOS = [
    ("A: Write then modify", scenario_a),
    ("B: Write test+src, modify src", scenario_b),
    ("C: Write 6 files, modify one", scenario_c),
    ("D: Pre-existing file update", scenario_d),
    ("E: Real project dispatch (8 files)", scenario_e),
    ("F: Fix iteration (pytest failure)", scenario_f),
]


def run_suite(suite_label: str, prompt: str, rounds: int) -> dict[str, list[bool]]:
    global SYSTEM_PROMPT
    SYSTEM_PROMPT = prompt

    all_results: dict[str, list[bool]] = {}
    for name, fn in SCENARIOS:
        results: list[bool] = []
        print(f"  [{name}]")
        for r in range(1, rounds + 1):
            tmp = Path(tempfile.mkdtemp(prefix="stress_"))
            try:
                ok, detail, stats = fn(tmp)
                mark = "✓" if ok else "✗"
                t = stats["time"]
                m = stats["msg_count"]
                we = stats["write_exists"]
                en = stats["edit_nomatch"]
                print(f"    {r:2d}. {mark} ({t:.1f}s, {m} msgs, write_exists={we}, edit_nomatch={en})")
                if not ok:
                    print(f"        {detail}")
                results.append(ok)
            except Exception as exc:
                print(f"    {r:2d}. ERROR: {exc}")
                results.append(False)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
        rate = sum(results) / len(results) * 100
        print(f"    → {sum(results)}/{len(results)} ({rate:.0f}%)")
        all_results[name] = results
    return all_results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rounds", type=int, default=5)
    args = parser.parse_args()

    print(f"LLM Stress Test — Simple vs Real System Prompt")
    print(f"Model: {LOCAL_MODEL} @ {LOCAL_BASE_URL}")
    print(f"Rounds: {args.rounds}")
    print(f"Simple prompt: {len(SIMPLE_PROMPT)} chars")
    print(f"Real prompt:   {len(REAL_PROMPT)} chars")

    print(f"\n{'=' * 60}")
    print(f"Suite 1: SIMPLE prompt ({len(SIMPLE_PROMPT)} chars)")
    print(f"{'=' * 60}")
    simple_results = run_suite("simple", SIMPLE_PROMPT, args.rounds)

    print(f"\n{'=' * 60}")
    print(f"Suite 2: REAL prompt ({len(REAL_PROMPT)} chars)")
    print(f"{'=' * 60}")
    real_results = run_suite("real", REAL_PROMPT, args.rounds)

    print(f"\n{'=' * 60}")
    print("Comparison:")
    print(f"{'':4s}{'Scenario':42s} {'Simple':>10s}  {'Real':>10s}")
    print(f"{'':4s}{'-'*42} {'-'*10}  {'-'*10}")
    for name, _ in SCENARIOS:
        s = simple_results[name]
        r = real_results[name]
        sp = f"{sum(s)}/{len(s)}"
        rp = f"{sum(r)}/{len(r)}"
        print(f"    {name:42s} {sp:>10s}  {rp:>10s}")
    s_total = sum(sum(v) for v in simple_results.values())
    r_total = sum(sum(v) for v in real_results.values())
    s_count = sum(len(v) for v in simple_results.values())
    r_count = sum(len(v) for v in real_results.values())
    print(f"    {'TOTAL':42s} {s_total}/{s_count} ({s_total/s_count*100:.0f}%)   {r_total}/{r_count} ({r_total/r_count*100:.0f}%)")


if __name__ == "__main__":
    main()
