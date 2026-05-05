"""Integration test: exit code is zero for all normal paths.

All normal execution paths (no args, --version, --help) should return
exit code 0.
"""

import subprocess
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_exit_code_zero():
    """Verify that all normal paths return exit code 0."""
    commands = [
        ["python", "src/main.py"],
        ["python", "src/main.py", "--version"],
        ["python", "src/main.py", "--help"],
    ]
    for cmd in commands:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=PROJECT_ROOT,
        )
        assert result.returncode == 0, (
            f"Command {' '.join(cmd)} returned non-zero exit code: {result.returncode}. "
            f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
        )
