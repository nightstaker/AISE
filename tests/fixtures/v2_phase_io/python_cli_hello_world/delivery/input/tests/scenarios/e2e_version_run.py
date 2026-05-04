"""E2E scenario: end-to-end --version run via subprocess.

Simulates a user running `python src/main.py --version` in the terminal.
Verifies stdout contains the version string and exit code is 0.
"""

import subprocess
import sys
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent.parent / "src" / "main.py"


def test_e2e_version_run():
    """End-to-end: running --version prints version string."""
    result = subprocess.run(
        [sys.executable, str(MAIN), "--version"],
        capture_output=True,
        text=True,
        cwd=MAIN.parent,
    )
    assert result.returncode == 0, (
        f"Expected exit code 0, got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "0.1.0" in result.stdout, (
        f"Expected '0.1.0' in stdout, got: {result.stdout!r}"
    )
