"""Pytest configuration — ensure src package is importable."""

import sys
from pathlib import Path

# Add project root to sys.path so 'src' is importable as a package.
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
