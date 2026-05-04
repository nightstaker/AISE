"""E2E scenario: end-to-end exit code verification.

Verifies that all valid invocation paths (default, --version, --help)
return exit code 0.
"""

import subprocess
import sys
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent.parent / "src" / "main.py"


def test_e2e_exit_codes():
    """All valid invocations return exit code 0."""
    commands = [
        [sys.executable, str(MAIN)],
        [sys.executable, str(MAIN), "--version"],
        [sys.executable, str(MAIN), "--help"],
    ]
    for cmd in commands:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=MAIN.parent,
        )
        assert result.returncode == 0, (
            f"Expected exit code 0 for command {cmd}, got "
            f"{result.returncode}. stderr: {result.stderr}"
        )
