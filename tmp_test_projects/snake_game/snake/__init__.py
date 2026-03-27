"""
Snake Game Package

A classic Snake game implementation with modular architecture.

This package provides a complete Snake game with:
- Snake entity with movement and growth mechanics
- Food spawning and consumption
- Collision detection
- Score tracking
- Configurable game settings
- Terminal-based display

Example:
    >>> from snake import SnakeGame
    >>> game = SnakeGame()
    >>> game.run()

Attributes:
    __version__: Current version of the package
    __author__: Package author
"""

__version__ = "1.0.0"
__author__ = "Game Developer"

from .main import SnakeGame, GameResult, GameStatus

__all__ = ["SnakeGame", "GameResult", "GameStatus", "__version__", "__author__"]
