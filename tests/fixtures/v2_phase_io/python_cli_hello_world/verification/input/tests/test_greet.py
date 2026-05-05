"""Tests for the greet module."""

from src.greet import greet


def test_greet_returns_hello_world():
    """greet() should return 'hello, world'."""
    result = greet()
    assert result == "hello, world"


def test_greet_prints_to_stdout(capsys):
    """greet() should print 'hello, world' to stdout."""
    greet()
    captured = capsys.readouterr()
    assert captured.out.strip() == "hello, world"
