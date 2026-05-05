"""E2E scenario: end-to-end default run via subprocess.

Simulates a user running `python src/main.py` in the terminal.
Verifies stdout contains 'hello, world' and exit code is 0.
"""

import subprocess
import sys
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent.parent / "src" / "main.py"


def test_e2e_default_run():
    """End-to-end: running the tool prints 'hello, world'."""
    result = subprocess.run(
        [sys.executable, str(MAIN)],
        capture_output=True,
        text=True,
        cwd=MAIN.parent,
    )
    assert result.returncode == 0, (
        f"Expected exit code 0, got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "hello, world" in result.stdout, (
        f"Expected 'hello, world' in stdout, got: {result.stdout!r}"
    )
