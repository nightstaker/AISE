"""E2E scenario: end-to-end invalid arguments handling.

When the tool is run with an unknown / invalid argument it should
exit with a non-zero code and print an error message to stderr.
This matches behavioral_contract.json scenario e2e_invalid_args:
  - stderr_contains: "error"
  - exit_code_not_zero: true
"""

import subprocess
import sys
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent.parent / "src" / "main.py"


def test_e2e_invalid_args():
    """Running with unknown arguments should produce an error and non-zero exit code."""
    result = subprocess.run(
        [sys.executable, str(MAIN), "--unknown-flag"],
        capture_output=True,
        text=True,
        cwd=MAIN.parent,
    )
    # argparse prints an error message to stderr and exits with code 2.
    assert result.returncode != 0, (
        f"Expected non-zero exit code for invalid args, got {result.returncode}. "
        f"stdout: {result.stdout!r}, stderr: {result.stderr!r}"
    )
    combined = result.stdout + result.stderr
    assert "error" in combined.lower(), (
        f"Expected 'error' in combined output for invalid args, "
        f"got stdout={result.stdout!r}, stderr={result.stderr!r}"
    )
