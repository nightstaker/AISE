"""Tests for the main module."""

import subprocess
import sys


def test_main_prints_hello_world():
    """Running main.py should print 'hello, world' to stdout."""
    result = subprocess.run(
        [sys.executable, "src/main.py"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "hello, world" in result.stdout.strip()


def test_main_no_error_output():
    """Running main.py should produce no stderr output."""
    result = subprocess.run(
        [sys.executable, "src/main.py"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert result.stderr.strip() == ""
