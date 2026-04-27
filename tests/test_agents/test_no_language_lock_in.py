"""Regression tests: agent prompts and orchestrator phase prompts must
NOT lock the project into a single language (Python by default). Where
specific commands or file paths are necessary as examples, they must be
accompanied by examples for at least one non-Python mainstream language
within a small window of context.

The user feedback that motivated these tests:

  > 当前的部分 agent 中有大量特殊化的提示，如限定于 Python 语言的要求和指导
  > 模板等，应当尽可能去掉这些特殊化的语言约束。如果确实需要约束，应该包括
  > 主流语言的示例

Mainstream non-Python languages we accept as "the file is multi-lingual":
TypeScript / JavaScript, Go, Rust, Java, Kotlin, C# / .NET.

The check works by counting Python-specific tokens (e.g. ``pytest``,
``ruff``, ``mypy``, ``pyproject.toml``) and Python-specific commands
(e.g. ``python -m pytest``, ``find ... '*.py'``). For every file
inspected, we either accept that the Python tokens are absent or
require that at least one non-Python mainstream-language token is
present in the same file. This catches "I added a Python example and
nothing else" regressions.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_PYTHON_TOKENS = (
    "python -m pytest",
    "pytest tests/",
    "ruff check",
    "mypy ",
    "pyproject.toml",
    "tests/test_<module>.py",
    "src/<module>.py",
    "find src -type f -name \"*.py\"",
    "find src -type f -name '*.py'",
    "pytest --cov",
    "--cov=src",
)

_NON_PYTHON_LANGUAGE_MARKERS = (
    # TypeScript / JavaScript
    "vitest",
    "jest",
    "npx ",
    "tsc ",
    "package.json",
    "tsconfig.json",
    # Go
    "go test",
    "go vet",
    "go.mod",
    "gofmt",
    # Rust
    "cargo test",
    "cargo check",
    "cargo clippy",
    "Cargo.toml",
    # Java / Kotlin
    "mvn test",
    "gradle ",
    "pom.xml",
    "build.gradle",
    # C# / .NET
    "dotnet ",
    # Generic multi-language placeholders explicitly used in our prompts
    "match the project's stack",
    "matching your stack",
    "matching the project's language",
    "language's idiomatic",
    "Do NOT default to Python",
    "do NOT default to Python",
)


def _file_passes(path: Path) -> tuple[bool, str]:
    """Return (passes, reason). True if no Python lock-in OR multilingual."""
    text = path.read_text(encoding="utf-8")
    py_hits = [tok for tok in _PYTHON_TOKENS if tok in text]
    if not py_hits:
        return True, "no Python-specific tokens"
    # File mentions Python — must also mention a non-Python language
    multi_hits = [m for m in _NON_PYTHON_LANGUAGE_MARKERS if m in text]
    if multi_hits:
        return True, (
            f"Python tokens present ({len(py_hits)}) but balanced by "
            f"{len(multi_hits)} non-Python markers"
        )
    return False, (
        f"Python-locked: tokens present {py_hits[:3]} but no non-Python "
        f"language markers found anywhere in the file"
    )


# Files that orchestrate or guide developer work and therefore must NOT
# be Python-locked. Each is checked independently.
_AGENT_FILES = [
    "src/aise/agents/architect.md",
    "src/aise/agents/developer.md",
    "src/aise/agents/qa_engineer.md",
    "src/aise/agents/product_manager.md",
    "src/aise/agents/code_reviewer.md",
    "src/aise/agents/project_manager.md",
    "src/aise/agents/rd_director.md",
    "src/aise/agents/_runtime_skills/tdd/SKILL.md",
    "src/aise/agents/_runtime_skills/code_inspection/SKILL.md",
    "src/aise/runtime/project_session.py",
]


@pytest.mark.parametrize("relpath", _AGENT_FILES)
def test_agent_prompt_is_not_python_locked(relpath):
    """Every agent prompt / skill / orchestrator phase prompt that
    contains Python-specific tokens MUST also contain at least one
    non-Python mainstream-language marker in the same file.

    This is a regression guard: if a future edit adds a Python-only
    example without the multi-language counterpart, this test fails
    immediately.
    """
    repo_root = Path(__file__).resolve().parents[2]
    path = repo_root / relpath
    assert path.is_file(), f"missing file: {path}"
    ok, reason = _file_passes(path)
    assert ok, f"{relpath}: {reason}"


def test_continuation_prompt_uses_multilingual_test_command():
    """The runtime's continuation prompt previously hard-coded
    ``execute_shell('python -m pytest tests/...')``. It must now
    instruct the orchestrator using language-aware phrasing — e.g.
    "the project's full-suite test command" — with examples spanning
    multiple mainstream test runners.
    """
    repo_root = Path(__file__).resolve().parents[2]
    text = (repo_root / "src/aise/runtime/project_session.py").read_text(encoding="utf-8")
    # Find the _render_continuation_prompt body
    match = re.search(
        r"def _render_continuation_prompt\(self\) -> str:\s*\"\"\"(?:[^\"]|\"(?!\"\"))*\"\"\"(.*?)(?=\n    def |\Z)",
        text,
        re.DOTALL,
    )
    assert match, "could not locate _render_continuation_prompt body"
    body = match.group(1)
    # Must NOT contain a bare standalone Python pytest invocation as the
    # only test-runner instruction. We look for "the project's full-suite
    # test command" anywhere in the body, OR an explicit list of multiple
    # runners.
    has_generic = "full-suite test command" in body or "project's full-suite" in body
    runners_listed = sum(
        marker in body
        for marker in ("pytest", "vitest", "jest", "go test", "cargo test", "mvn test")
    )
    assert has_generic or runners_listed >= 3, (
        "continuation prompt must either use generic 'project's test command' "
        "phrasing or list 3+ test runners; found generic="
        f"{has_generic}, runners_listed={runners_listed}"
    )
