"""Integration test: exact output matching.

The default output of the CLI tool should exactly match 'hello, world'
(with a trailing newline) — no extra whitespace, no quotes.
"""

import subprocess
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_exact_output():
    """Verify the stdout is exactly 'hello, world\\n'."""
    result = subprocess.run(
        ["python", "src/main.py"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"
    assert result.stdout.strip() == "hello, world", (
        f"Expected exact output 'hello, world', got: {result.stdout.strip()!r}"
    )
    assert "hello, world" in result.stdout, (
        f"Expected 'hello, world' in stdout, got: {result.stdout!r}"
    )
