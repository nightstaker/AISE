"""Integration test: --version flag behavior.

When running the CLI tool with --version, it should output the version
string '0.1.0' to stdout and exit with code 0.
"""

import subprocess
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_version_flag():
    """Run src/main.py --version and verify stdout contains '0.1.0'."""
    result = subprocess.run(
        ["python", "src/main.py", "--version"],
        capture_output=True,
        text=True,
        cwd=PROJECT_ROOT,
    )
    assert result.returncode == 0, f"Expected exit code 0, got {result.returncode}. stderr: {result.stderr}"
    assert "0.1.0" in result.stdout, (
        f"Expected '0.1.0' in stdout, got: {result.stdout!r}"
    )
