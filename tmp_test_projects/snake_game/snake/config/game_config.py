"""
Game Configuration Module

Provides comprehensive configuration management for the Snake game,
including board settings, speed controls, visual options, and
configuration persistence.

This module supports:
- Default configuration values
- JSON-based configuration files
- Runtime configuration overrides
- Configuration validation
- Configuration inheritance
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, asdict
from enum import Enum, auto
from pathlib import Path
from typing import Any, Optional, Dict, List, Union
from copy import deepcopy


class Theme(Enum):
    """Visual theme options for the game."""
    DEFAULT = auto()
    DARK = auto()
    RETRO = auto()
    MINIMAL = auto()


class SnakeDirection(Enum):
    """Valid directions for snake movement."""
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()


@dataclass
class KeyboardConfig:
    """Keyboard control configuration."""
    
    up: str = "w"
    down: str = "s"
    left: str = "a"
    right: str = "d"
    pause: str = "p"
    quit: str = "q"
    restart: str = "r"
    
    # Alternative controls using arrow keys
    up_alt: Optional[str] = None
    down_alt: Optional[str] = None
    left_alt: Optional[str] = None
    right_alt: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate keyboard configuration."""
        self._validate_keys()
    
    def _validate_keys(self) -> None:
        """Ensure all required keys are set."""
        required = ["up", "down", "left", "right"]
        for key in required:
            if not getattr(self, key):
                raise ValueError(f"Keyboard control '{key}' cannot be empty")
    
    def get_direction_key(self, direction: SnakeDirection) -> List[str]:
        """Get all key bindings for a direction."""
        mapping = {
            SnakeDirection.UP: ["up", "up_alt"],
            SnakeDirection.DOWN: ["down", "down_alt"],
            SnakeDirection.LEFT: ["left", "left_alt"],
            SnakeDirection.RIGHT: ["right", "right_alt"],
        }
        
        keys = []
        for attr in mapping[direction]:
            value = getattr(self, attr, None)
            if value:
                keys.append(value)
        return keys
    
    def get_all_keys(self) -> List[str]:
        """Get all configured keys."""
        keys = []
        for attr in dir(self):
            if not attr.startswith("_") and attr != "get_all_keys":
                value = getattr(self, attr)
                if isinstance(value, str):
                    keys.append(value)
        return list(set(keys))


@dataclass
class BoardConfig:
    """Game board configuration."""
    
    width: int = 40
    height: int = 20
    border: bool = True
    
    def __post_init__(self) -> None:
        """Validate board dimensions."""
        self._validate_dimensions()
    
    def _validate_dimensions(self) -> None:
        """Ensure board dimensions are valid."""
        if self.width < 10:
            raise ValueError("Board width must be at least 10")
        if self.height < 8:
            raise ValueError("Board height must be at least 8")
        if self.width > 200:
            raise ValueError("Board width cannot exceed 200")
        if self.height > 100:
            raise ValueError("Board height cannot exceed 100")
    
    def area(self) -> int:
        """Calculate total playable area."""
        inner_width = self.width - 4 if self.border else self.width
        inner_height = self.height - 2 if self.border else self.height
        return inner_width * inner_height
    
    def is_valid_position(self, x: int, y: int) -> bool:
        """Check if a position is within board bounds."""
        if self.border:
            return (1 <= x < self.width - 1) and (1 <= y < self.height - 1)
        return (0 <= x < self.width) and (0 <= y < self.height)


@dataclass
class SpeedConfig:
    """Game speed configuration."""
    
    base_delay_ms: int = 150
    min_delay_ms: int = 50
    max_delay_ms: int = 500
    acceleration_per_food: int = 2
    max_speed_increase: int = 50
    
    def __post_init__(self) -> None:
        """Validate speed configuration."""
        self._validate_speeds()
    
    def _validate_speeds(self) -> None:
        """Ensure speed values are in valid ranges."""
        if self.base_delay_ms < self.min_delay_ms:
            raise ValueError("base_delay_ms must be >= min_delay_ms")
        if self.base_delay_ms > self.max_delay_ms:
            raise ValueError("base_delay_ms must be <= max_delay_ms")
        if self.min_delay_ms < 20:
            raise ValueError("min_delay_ms cannot be less than 20ms")
        if self.max_delay_ms > 2000:
            raise ValueError("max_delay_ms cannot exceed 2000ms")
    
    def calculate_delay(self, foods_eaten: int) -> int:
        """Calculate current delay based on foods eaten."""
        speed_increase = min(foods_eaten * self.acceleration_per_food, 
                           self.max_speed_increase)
        delay = self.base_delay_ms - speed_increase
        return max(self.min_delay_ms, min(self.max_delay_ms, delay))


@dataclass
class VisualConfig:
    """Visual appearance configuration."""
    
    theme: Theme = Theme.DEFAULT
    snake_head: str = "@"
    snake_body: str = "o"
    food: str = "*"
    wall: str = "#"
    empty: str = " "
    score_prefix: str = "Score: "
    high_score_prefix: str = "Best: "
    
    def get_colors(self) -> Dict[str, str]:
        """Get ANSI color codes for current theme."""
        themes = {
            Theme.DEFAULT: {
                "snake_head": "\033[32m",
                "snake_body": "\033[2m\033[32m",
                "food": "\033[31m",
                "wall": "\033[37m",
                "reset": "\033[0m",
            },
            Theme.DARK: {
                "snake_head": "\033[92m",
                "snake_body": "\033[32m",
                "food": "\033[91m",
                "wall": "\033[37m",
                "reset": "\033[0m",
            },
            Theme.RETRO: {
                "snake_head": "\033[42m\033[30m",
                "snake_body": "\033[42m\033[30m",
                "food": "\033[41m\033[30m",
                "wall": "\033[47m\033[30m",
                "reset": "\033[0m",
            },
            Theme.MINIMAL: {
                "snake_head": "",
                "snake_body": "",
                "food": "",
                "wall": "",
                "reset": "",
            },
        }
        return themes.get(self.theme, themes[Theme.DEFAULT])


@dataclass
class SoundConfig:
    """Sound configuration."""
    
    enabled: bool = False
    volume: int = 50
    eat_sound: Optional[str] = None
    game_over_sound: Optional[str] = None
    level_up_sound: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Validate sound configuration."""
        if not 0 <= self.volume <= 100:
            raise ValueError("Volume must be between 0 and 100")


@dataclass
class GameConfig:
    """
    Main game configuration container.
    
    Aggregates all sub-configurations and provides unified access
    to game settings with validation and persistence support.
    """
    
    # Sub-configurations
    board: BoardConfig = field(default_factory=BoardConfig)
    speed: SpeedConfig = field(default_factory=SpeedConfig)
    visual: VisualConfig = field(default_factory=VisualConfig)
    keyboard: KeyboardConfig = field(default_factory=KeyboardConfig)
    sound: SoundConfig = field(default_factory=SoundConfig)
    
    # Global settings
    show_fps: bool = False
    fullscreen: bool = False
    auto_restart: bool = False
    confirm_quit: bool = True
    
    # File paths
    config_path: Optional[str] = None
    save_path: Optional[str] = None
    
    def __post_init__(self) -> None:
        """Initialize default paths if not set."""
        if not self.config_path:
            self.config_path = self._default_config_path()
        if not self.save_path:
            self.save_path = self._default_save_path()
    
    def _default_config_path(self) -> str:
        """Get default configuration file path."""
        config_dir = Path.home() / ".snake"
        config_dir.mkdir(parents=True, exist_ok=True)
        return str(config_dir / "config.json")
    
    def _default_save_path(self) -> str:
        """Get default save file path."""
        save_dir = Path.home() / ".snake"
        save_dir.mkdir(parents=True, exist_ok=True)
        return str(save_dir / "savegame.json")
    
    @classmethod
    def default(cls) -> GameConfig:
        """Create a new configuration with default values."""
        return cls()
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> GameConfig:
        """Create configuration from dictionary."""
        config = cls()
        config.update(data)
        return config
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert configuration to dictionary."""
        return {
            "board": asdict(self.board),
            "speed": asdict(self.speed),
            "visual": {
                **asdict(self.visual),
                "theme": self.visual.theme.name,
            },
            "keyboard": asdict(self.keyboard),
            "sound": asdict(self.sound),
            "show_fps": self.show_fps,
            "fullscreen": self.fullscreen,
            "auto_restart": self.auto_restart,
            "confirm_quit": self.confirm_quit,
        }
    
    def update(self, data: Dict[str, Any]) -> None:
        """Update configuration from dictionary."""
        if "board" in data:
            for key, value in data["board"].items():
                if hasattr(self.board, key):
                    setattr(self.board, key, value)
        
        if "speed" in data:
            for key, value in data["speed"].items():
                if hasattr(self.speed, key):
                    setattr(self.speed, key, value)
        
        if "visual" in data:
            for key, value in data["visual"].items():
                if key == "theme" and isinstance(value, str):
                    setattr(self.visual, key, Theme[value])
                elif hasattr(self.visual, key):
                    setattr(self.visual, key, value)
        
        if "keyboard" in data:
            for key, value in data["keyboard"].items():
                if hasattr(self.keyboard, key):
                    setattr(self.keyboard, key, value)
        
        if "sound" in data:
            for key, value in data["sound"].items():
                if hasattr(self.sound, key):
                    setattr(self.sound, key, value)
        
        for key in ["show_fps", "fullscreen", "auto_restart", "confirm_quit"]:
            if key in data:
                setattr(self, key, data[key])
    
    def load(self, path: Optional[str] = None) -> None:
        """Load configuration from file."""
        filepath = path or self.config_path
        if not filepath or not os.path.exists(filepath):
            return
        
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.update(data)
        except (json.JSONDecodeError, IOError) as e:
            print(f"Warning: Could not load config from {filepath}: {e}")
    
    def save(self, path: Optional[str] = None) -> None:
        """Save configuration to file."""
        filepath = path or self.config_path
        try:
            directory = os.path.dirname(filepath)
            if directory:
                os.makedirs(directory, exist_ok=True)
            
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.to_dict(), f, indent=2)
        except IOError as e:
            print(f"Error: Could not save config to {filepath}: {e}")
    
    def reset(self) -> None:
        """Reset all configuration to defaults."""
        self.__init__()
    
    def copy(self) -> GameConfig:
        """Create a deep copy of the configuration."""
        return deepcopy(self)
    
    def get_initial_delay(self) -> int:
        """Get the initial game delay in milliseconds."""
        return self.speed.base_delay_ms
    
    def get_min_delay(self) -> int:
        """Get the minimum possible delay."""
        return self.speed.min_delay_ms
    
    def get_max_delay(self) -> int:
        """Get the maximum possible delay."""
        return self.speed.max_delay_ms


class ConfigManager:
    """
    Singleton configuration manager.
    
    Provides centralized access to game configuration with
    support for multiple configuration profiles.
    """
    
    _instance: Optional["ConfigManager"] = None
    _config: Optional[GameConfig] = None
    _profiles: Dict[str, GameConfig] = {}
    
    def __new__(cls) -> "ConfigManager":
        """Singleton pattern implementation."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self) -> None:
        """Initialize configuration manager."""
        if self._config is None:
            self._config = GameConfig.default()
    
    @property
    def config(self) -> GameConfig:
        """Get current configuration."""
        return self._config
    
    @config.setter
    def config(self, value: GameConfig) -> None:
        """Set current configuration."""
        self._config = value
    
    def load(self, path: Optional[str] = None) -> None:
        """Load configuration from file."""
        self._config.load(path)
    
    def save(self, path: Optional[str] = None) -> None:
        """Save configuration to file."""
        self._config.save(path)
    
    def reset(self) -> None:
        """Reset configuration to defaults."""
        self._config = GameConfig.default()
    
    def create_profile(self, name: str) -> None:
        """Create a new configuration profile."""
        if name not in self._profiles:
            self._profiles[name] = self._config.copy()
    
    def load_profile(self, name: str) -> bool:
        """Load a configuration profile."""
        if name in self._profiles:
            self._config = self._profiles[name].copy()
            return True
        return False
    
    def list_profiles(self) -> List[str]:
        """List all available profiles."""
        return list(self._profiles.keys())
    
    def delete_profile(self, name: str) -> bool:
        """Delete a configuration profile."""
        if name in self._profiles:
            del self._profiles[name]
            return True
        return False
    
    def set_value(self, path: str, value: Any) -> None:
        """
        Set a configuration value using dot notation.
        
        Example: config_manager.set_value("board.width", 50)
        """
        parts = path.split(".")
        obj = self._config
        
        for part in parts[:-1]:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                raise AttributeError(f"Config path '{path}' is invalid")
        
        if hasattr(obj, parts[-1]):
            setattr(obj, parts[-1], value)
        else:
            raise AttributeError(f"Config key '{parts[-1]}' does not exist")
    
    def get_value(self, path: str) -> Any:
        """
        Get a configuration value using dot notation.
        
        Example: config_manager.get_value("board.width")
        """
        parts = path.split(".")
        obj = self._config
        
        for part in parts:
            if hasattr(obj, part):
                obj = getattr(obj, part)
            else:
                raise AttributeError(f"Config path '{path}' is invalid")
        
        return obj


# Module-level configuration instance for convenience
config: ConfigManager = ConfigManager()


def main() -> None:
    """Demonstrate configuration functionality."""
    # Create new configuration
    game_config = GameConfig.default()
    
    print("Default Configuration:")
    print(f"  Board: {game_config.board.width}x{game_config.board.height}")
    print(f"  Base Speed: {game_config.speed.base_delay_ms}ms")
    print(f"  Theme: {game_config.visual.theme.name}")
    print(f"  Snake Head: {game_config.visual.snake_head}")
    print()
    
    # Modify configuration
    game_config.board.width = 60
    game_config.speed.base_delay_ms = 100
    game_config.visual.theme = Theme.RETRO
    
    print("Modified Configuration:")
    print(f"  Board: {game_config.board.width}x{game_config.board.height}")
    print(f"  Base Speed: {game_config.speed.base_delay_ms}ms")
    print(f"  Theme: {game_config.visual.theme.name}")
    print()
    
    # Test speed calculation
    print("Speed Progression:")
    for foods in [0, 5, 10, 20]:
        delay = game_config.speed.calculate_delay(foods)
        print(f"  After {foods} foods: {delay}ms")
    print()
    
    # Test config manager
    manager = ConfigManager()
    manager.set_value("board.height", 25)
    print(f"Config Manager - Board Height: {manager.get_value('board.height')}")


if __name__ == "__main__":
    main()

---