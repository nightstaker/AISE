"""Main entry point for the hello-world CLI tool."""

import argparse
import sys
import os

# Ensure the project root is on sys.path so 'src' imports work when
# running as a script (python src/main.py).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.greet import greet
from src.version import get_version


def build_parser() -> argparse.ArgumentParser:
    """Build and return the argument parser."""
    parser = argparse.ArgumentParser(
        prog="hello",
        description="A simple CLI tool that prints 'hello, world'.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"hello {get_version()}",
    )
    return parser


def main() -> None:
    """Main entry point: parse args and print greeting."""
    parser = build_parser()
    parser.parse_args()

    # Default action: print the greeting
    greet()


if __name__ == "__main__":
    main()
