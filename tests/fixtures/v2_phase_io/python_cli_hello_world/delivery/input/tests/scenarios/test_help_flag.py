"""Integration test: --help flag behavior.

When running the CLI tool with --help, it should output help information
including 'usage' and exit with code 0.
"""

import subprocess
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_help_flag():
    """Run src/main.py --help and verify stdout contains 'usage'."""
    result = subprocess.run(
        ["python", "src/main.py", "--help"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"
    assert "usage" in result.stdout.lower(), (
        f"Expected 'usage' in stdout, got: {result.stdout!r}"
    )
