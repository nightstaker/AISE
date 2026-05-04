"""E2E scenario: end-to-end --help run via subprocess.

Simulates a user running `python src/main.py --help` in the terminal.
Verifies stdout contains help text and exit code is 0.
"""

import subprocess
import sys
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent.parent / "src" / "main.py"


def test_e2e_help_run():
    """End-to-end: running --help displays help information."""
    result = subprocess.run(
        [sys.executable, str(MAIN), "--help"],
        capture_output=True,
        text=True,
        cwd=MAIN.parent,
    )
    assert result.returncode == 0, (
        f"Expected exit code 0, got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "usage" in result.stdout.lower(), (
        f"Expected 'usage' in stdout, got: {result.stdout!r}"
    )
