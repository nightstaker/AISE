"""
Storage Subsystem

Handles all persistence operations for the Snake game including:
- High score management
- Game state saving/loading
"""

from .score_repository import (
    GameScore,
    ScoreRepository,
    ScoreRepositoryConfig,
    get_repository,
)

from .game_saver import (
    GameState,
    SaveSlotInfo,
    GameSaver,
    GameSaverConfig,
    SaveError,
    SaveNotFoundError,
    SaveCorruptedError,
    SaveValidationError,
    get_saver,
    SAVE_FORMAT_VERSION,
)

__all__ = [
    # Score Repository
    "GameScore",
    "ScoreRepository",
    "ScoreRepositoryConfig",
    "get_repository",
    
    # Game Saver
    "GameState",
    "SaveSlotInfo",
    "GameSaver",
    "GameSaverConfig",
    "SaveError",
    "SaveNotFoundError",
    "SaveCorruptedError",
    "SaveValidationError",
    "get_saver",
    "SAVE_FORMAT_VERSION",
]
