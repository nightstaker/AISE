"""Integration test: default print behavior.

When running the CLI tool with no arguments, it should output
'hello, world' to stdout and exit with code 0.
"""

import subprocess
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_default_print():
    """Run src/main.py with no arguments and verify stdout contains 'hello, world'."""
    result = subprocess.run(
        ["python", "src/main.py"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"
    assert "hello, world" in result.stdout, (
        f"Expected 'hello, world' in stdout, got: {result.stdout!r}"
    )
