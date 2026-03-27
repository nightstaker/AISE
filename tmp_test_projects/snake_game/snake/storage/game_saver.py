"""
Game Saver Module

Handles saving and loading of game state for the Snake game.
Supports multiple save slots, versioning, and data validation.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path
import json
import threading
from datetime import datetime
import logging
import hashlib

# Configure logging
logger = logging.getLogger(__name__)

# Current save format version
SAVE_FORMAT_VERSION = 1


@dataclass
class GameState:
    """Represents the complete state of a Snake game."""
    
    # Game configuration
    width: int = 20
    height: 20
    initial_speed: float = 0.2
    speed_increase: float = 0.005
    
    # Game state
    snake: list[tuple[int, int]] = field(default_factory=list)
    food: Optional[tuple[int, int]] = None
    direction: str = "RIGHT"
    next_direction: str = "RIGHT"
    
    # Scoring
    score: int = 0
    high_score: int = 0
    
    # Game progress
    game_over: bool = False
    paused: bool = False
    level: int = 1
    speed: float = 0.2
    
    # Metadata
    game_mode: str = "classic"
    player_name: str = "Player"
    start_time: str = field(default_factory=lambda: datetime.now().isoformat())
    play_time: float = 0.0  # In seconds
    
    def to_dict(self) -> dict:
        """Convert game state to dictionary for serialization."""
        return {
            "version": SAVE_FORMAT_VERSION,
            "width": self.width,
            "height": self.height,
            "initial_speed": self.initial_speed,
            "speed_increase": self.speed_increase,
            "snake": self.snake,
            "food": self.food,
            "direction": self.direction,
            "next_direction": self.next_direction,
            "score": self.score,
            "high_score": self.high_score,
            "game_over": self.game_over,
            "paused": self.paused,
            "level": self.level,
            "speed": self.speed,
            "game_mode": self.game_mode,
            "player_name": self.player_name,
            "start_time": self.start_time,
            "play_time": self.play_time,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> GameState:
        """Create a GameState from a dictionary."""
        # Handle version migration if needed
        version = data.get("version", 1)
        if version < SAVE_FORMAT_VERSION:
            logger.warning(f"Migrating save data from version {version} to {SAVE_FORMAT_VERSION}")
        
        return cls(
            width=data.get("width", 20),
            height=data.get("height", 20),
            initial_speed=data.get("initial_speed", 0.2),
            speed_increase=data.get("speed_increase", 0.005),
            snake=data.get("snake", []),
            food=data.get("food"),
            direction=data.get("direction", "RIGHT"),
            next_direction=data.get("next_direction", "RIGHT"),
            score=data.get("score", 0),
            high_score=data.get("high_score", 0),
            game_over=data.get("game_over", False),
            paused=data.get("paused", False),
            level=data.get("level", 1),
            speed=data.get("speed", 0.2),
            game_mode=data.get("game_mode", "classic"),
            player_name=data.get("player_name", "Player"),
            start_time=data.get("start_time", datetime.now().isoformat()),
            play_time=data.get("play_time", 0.0),
        )
    
    def validate(self) -> list[str]:
        """
        Validate the game state for consistency.
        
        Returns:
            List of validation error messages (empty if valid).
        """
        errors = []
        
        # Validate dimensions
        if self.width < 10 or self.width > 100:
            errors.append(f"Invalid width: {self.width}")
        if self.height < 10 or self.height > 100:
            errors.append(f"Invalid height: {self.height}")
        
        # Validate snake positions
        for i, pos in enumerate(self.snake):
            if not isinstance(pos, (list, tuple)) or len(pos) != 2:
                errors.append(f"Invalid snake position at index {i}: {pos}")
                continue
            x, y = pos
            if not (0 <= x < self.width and 0 <= y < self.height):
                errors.append(f"Snake body out of bounds at index {i}: ({x}, {y})")
        
        # Validate food position
        if self.food:
            x, y = self.food
            if not (0 <= x < self.width and 0 <= y < self.height):
                errors.append(f"Food out of bounds: ({x}, {y})")
        
        # Validate direction
        valid_directions = ["UP", "DOWN", "LEFT", "RIGHT"]
        if self.direction not in valid_directions:
            errors.append(f"Invalid direction: {self.direction}")
        if self.next_direction not in valid_directions:
            errors.append(f"Invalid next_direction: {self.next_direction}")
        
        # Validate scores
        if self.score < 0:
            errors.append(f"Negative score: {self.score}")
        if self.high_score < 0:
            errors.append(f"Negative high_score: {self.high_score}")
        
        return errors


@dataclass
class SaveSlotInfo:
    """Information about a save slot."""
    
    slot: int
    exists: bool
    player_name: str = ""
    score: int = 0
    game_mode: str = "classic"
    last_saved: str = ""
    file_size: int = 0
    checksum: str = ""


@dataclass
class GameSaverConfig:
    """Configuration for the GameSaver."""
    
    save_directory: Path = field(default_factory=lambda: Path("data/saves"))
    max_save_slots: int = 5
    backup_on_save: bool = True
    auto_cleanup: bool = True


class SaveError(Exception):
    """Base exception for save-related errors."""
    pass


class SaveNotFoundError(SaveError):
    """Raised when a save file is not found."""
    pass


class SaveCorruptedError(SaveError):
    """Raised when a save file is corrupted."""
    pass


class SaveValidationError(SaveError):
    """Raised when saved data fails validation."""
    pass


class GameSaver:
    """
    Handles saving and loading of Snake game state.
    
    Features:
    - Multiple save slots
    - JSON-based persistence
    - Data validation
    - Checksum verification
    - Automatic backups
    """
    
    def __init__(self, config: Optional[GameSaverConfig] = None):
        """
        Initialize the game saver.
        
        Args:
            config: Optional configuration object.
        """
        self.config = config or GameSaverConfig()
        self._lock = threading.RLock()
        
        # Ensure save directory exists
        self.config.save_directory.mkdir(parents=True, exist_ok=True)
    
    def _get_save_path(self, slot: int) -> Path:
        """Get the file path for a save slot."""
        return self.config.save_directory / f"save_{slot:02d}.json"
    
    def _get_backup_path(self, slot: int) -> Path:
        """Get the backup file path for a save slot."""
        return self.config.save_directory / f"save_{slot:02d}.json.bak"
    
    def _calculate_checksum(self, data: str) -> str:
        """Calculate MD5 checksum of data."""
        return hashlib.md5(data.encode("utf-8")).hexdigest()
    
    def _get_slot_info(self, slot: int) -> SaveSlotInfo:
        """
        Get information about a save slot without loading the full state.
        
        Args:
            slot: The save slot number.
            
        Returns:
            SaveSlotInfo object with metadata about the slot.
        """
        save_path = self._get_save_path(slot)
        info = SaveSlotInfo(slot=slot, exists=False)
        
        if not save_path.exists():
            return info
        
        info.exists = True
        info.file_size = save_path.stat().st_size
        
        try:
            with open(save_path, "r", encoding="utf-8") as f:
                content = f.read()
                info.checksum = self._calculate_checksum(content)
                
                data = json.loads(content)
                info.player_name = data.get("player_name", "Unknown")
                info.score = data.get("score", 0)
                info.game_mode = data.get("game_mode", "classic")
                info.last_saved = data.get("start_time", "")
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Could not read metadata for slot {slot}: {e}")
        
        return info
    
    def save_game(self, slot: int, game_state: GameState) -> bool:
        """
        Save game state to a slot.
        
        Args:
            slot: The save slot number (0-4 by default).
            game_state: The game state to save.
            
        Returns:
            True if saved successfully, False otherwise.
            
        Raises:
            SaveError: If the slot is invalid or save fails.
        """
        with self._lock:
            # Validate slot number
            if slot < 0 or slot >= self.config.max_save_slots:
                raise SaveError(f"Invalid slot number: {slot}. Must be 0-{self.config.max_save_slots - 1}")
            
            # Validate game state
            errors = game_state.validate()
            if errors:
                raise SaveValidationError(f"Game state validation failed: {errors}")
            
            save_path = self._get_save_path(slot)
            
            try:
                # Create backup if enabled and file exists
                if self.config.backup_on_save and save_path.exists():
                    backup_path = self._get_backup_path(slot)
                    with open(save_path, "r", encoding="utf-8") as src:
                        with open(backup_path, "w", encoding="utf-8") as dst:
                            dst.write(src.read())
                    logger.debug(f"Created backup for slot {slot}")
                
                # Serialize game state
                data = game_state.to_dict()
                json_str = json.dumps(data, indent=2, ensure_ascii=False)
                
                # Write atomically
                temp_path = save_path.with_suffix(".json.tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    f.write(json_str)
                
                temp_path.rename(save_path)
                
                logger.info(f"Game saved to slot {slot}")
                return True
                
            except Exception as e:
                logger.error(f"Failed to save game to slot {slot}: {e}")
                raise SaveError(f"Save failed: {e}")
    
    def load_game(self, slot: int) -> GameState:
        """
        Load game state from a slot.
        
        Args:
            slot: The save slot number.
            
        Returns:
            The loaded GameState.
            
        Raises:
            SaveNotFoundError: If no save exists for the slot.
            SaveCorruptedError: If the save file is corrupted.
            SaveValidationError: If the loaded data fails validation.
        """
        with self._lock:
            save_path = self._get_save_path(slot)
            
            if not save_path.exists():
                raise SaveNotFoundError(f"No save found for slot {slot}")
            
            try:
                with open(save_path, "r", encoding="utf-8") as f:
                    content = f.read()
                
                # Verify checksum if available
                stored_checksum = self._calculate_checksum(content)
                
                data = json.loads(content)
                game_state = GameState.from_dict(data)
                
                # Validate loaded state
                errors = game_state.validate()
                if errors:
                    raise SaveValidationError(f"Loaded game state failed validation: {errors}")
                
                logger.info(f"Game loaded from slot {slot}")
                return game_state
                
            except json.JSONDecodeError as e:
                raise SaveCorruptedError(f"Save file for slot {slot} is corrupted: {e}")
            except Exception as e:
                logger.error(f"Failed to load game from slot {slot}: {e}")
                raise SaveError(f"Load failed: {e}")
    
    def get_save_slots(self) -> list[SaveSlotInfo]:
        """
        Get information about all save slots.
        
        Returns:
            List of SaveSlotInfo objects for all slots.
        """
        with self._lock:
            return [
                self._get_slot_info(slot)
                for slot in range(self.config.max_save_slots)
            ]
    
    def delete_save(self, slot: int) -> bool:
        """
        Delete a save from a slot.
        
        Args:
            slot: The save slot number.
            
        Returns:
            True if a save was deleted, False if no save existed.
        """
        with self._lock:
            if slot < 0 or slot >= self.config.max_save_slots:
                raise SaveError(f"Invalid slot number: {slot}")
            
            save_path = self._get_save_path(slot)
            backup_path = self._get_backup_path(slot)
            
            deleted = False
            
            if save_path.exists():
                save_path.unlink()
                deleted = True
            
            if backup_path.exists():
                backup_path.unlink()
            
            if deleted:
                logger.info(f"Deleted save from slot {slot}")
            
            return deleted
    
    def delete_all_saves(self) -> int:
        """
        Delete all saves.
        
        Returns:
            Number of saves deleted.
        """
        with self._lock:
            deleted = 0
            
            for slot in range(self.config.max_save_slots):
                if self.delete_save(slot):
                    deleted += 1
            
            logger.info(f"Deleted {deleted} save(s)")
            return deleted
    
    def get_available_slots(self) -> list[int]:
        """
        Get list of empty save slots.
        
        Returns:
            List of slot numbers that don't have saves.
        """
        with self._lock:
            return [
                slot for slot in range(self.config.max_save_slots)
                if not self._get_save_path(slot).exists()
            ]
    
    def get_latest_save(self) -> Optional[tuple[int, GameState]]:
        """
        Get the most recently saved game.
        
        Returns:
            Tuple of (slot, GameState) or None if no saves exist.
        """
        with self._lock:
            latest_slot = None
            latest_time = None
            
            for slot in range(self.config.max_save_slots):
                save_path = self._get_save_path(slot)
                if save_path.exists():
                    try:
                        mtime = save_path.stat().st_mtime
                        if latest_time is None or mtime > latest_time:
                            latest_time = mtime
                            latest_slot = slot
                    except OSError:
                        continue
            
            if latest_slot is not None:
                return (latest_slot, self.load_game(latest_slot))
            return None
    
    def restore_from_backup(self, slot: int) -> bool:
        """
        Restore a save from its backup.
        
        Args:
            slot: The save slot number.
            
        Returns:
            True if restored successfully, False if no backup exists.
        """
        with self._lock:
            if slot < 0 or slot >= self.config.max_save_slots:
                raise SaveError(f"Invalid slot number: {slot}")
            
            backup_path = self._get_backup_path(slot)
            save_path = self._get_save_path(slot)
            
            if not backup_path.exists():
                logger.warning(f"No backup found for slot {slot}")
                return False
            
            try:
                with open(backup_path, "r", encoding="utf-8") as src:
                    content = src.read()
                
                with open(save_path, "w", encoding="utf-8") as dst:
                    dst.write(content)
                
                logger.info(f"Restored slot {slot} from backup")
                return True
                
            except Exception as e:
                logger.error(f"Failed to restore slot {slot} from backup: {e}")
                return False
    
    def verify_saves(self) -> dict:
        """
        Verify integrity of all saves.
        
        Returns:
            Dictionary with verification results.
        """
        with self._lock:
            results = {
                "total": 0,
                "valid": 0,
                "corrupted": 0,
                "issues": [],
            }
            
            for slot in range(self.config.max_save_slots):
                save_path = self._get_save_path(slot)
                if not save_path.exists():
                    continue
                
                results["total"] += 1
                try:
                    with open(save_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    game_state = GameState.from_dict(data)
                    errors = game_state.validate()
                    
                    if errors:
                        results["issues"].append({
                            "slot": slot,
                            "type": "validation",
                            "errors": errors,
                        })
                        results["corrupted"] += 1
                    else:
                        results["valid"] += 1
                        
                except json.JSONDecodeError as e:
                    results["issues"].append({
                        "slot": slot,
                        "type": "corrupted",
                        "error": str(e),
                    })
                    results["corrupted"] += 1
                except Exception as e:
                    results["issues"].append({
                        "slot": slot,
                        "type": "unknown",
                        "error": str(e),
                    })
                    results["corrupted"] += 1
            
            return results


# Singleton instance for convenience
_default_saver: Optional[GameSaver] = None


def get_saver(config: Optional[GameSaverConfig] = None) -> GameSaver:
    """
    Get or create the default game saver instance.
    
    Args:
        config: Optional configuration for a new saver.
        
    Returns:
        The default GameSaver instance.
    """
    global _default_saver
    if _default_saver is None or config is not None:
        _default_saver = GameSaver(config)
    return _default_saver
