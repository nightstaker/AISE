"""
Difficulty Levels Module

Defines difficulty levels and their associated game parameters
for the Snake game. Supports multiple difficulty presets and
custom difficulty configuration.

Features:
- Enum-based difficulty levels
- Speed configurations per difficulty
- Score multipliers
- Obstacle and power-up settings
- Difficulty factory functions
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Tuple, Callable


class Difficulty(Enum):
    """Game difficulty levels."""
    
    EASY = auto()
    """Beginner-friendly with slow speed and no obstacles."""
    
    NORMAL = auto()
    """Standard gameplay experience."""
    
    HARD = auto()
    """Challenging with faster speed and some obstacles."""
    
    EXPERT = auto()
    """Very challenging with maximum speed and obstacles."""
    
    INSANE = auto()
    """For experts only - maximum difficulty."""
    
    CUSTOM = auto()
    """Custom difficulty with user-defined settings."""
    
    def __str__(self) -> str:
        """Return difficulty name."""
        return self.name.upper()
    
    def __lt__(self, other: "Difficulty") -> bool:
        """Enable comparison between difficulties."""
        if not isinstance(other, Difficulty):
            return NotImplemented
        return self.value < other.value
    
    def next_level(self) -> Optional["Difficulty"]:
        """Get the next difficulty level."""
        levels = list(Difficulty)
        try:
            idx = levels.index(self)
            if idx < len(levels) - 1 and levels[idx + 1] != Difficulty.CUSTOM:
                return levels[idx + 1]
        except ValueError:
            pass
        return None
    
    def previous_level(self) -> Optional["Difficulty"]:
        """Get the previous difficulty level."""
        levels = list(Difficulty)
        try:
            idx = levels.index(self)
            if idx > 0 and levels[idx - 1] != Difficulty.CUSTOM:
                return levels[idx - 1]
        except ValueError:
            pass
        return None


@dataclass
class DifficultySettings:
    """
    Complete settings for a difficulty level.
    
    Contains all game parameters that vary by difficulty.
    """
    
    name: str
    """Display name for the difficulty."""
    
    description: str
    """Brief description of the difficulty."""
    
    # Speed settings
    initial_delay_ms: int = 200
    """Initial snake movement delay in milliseconds."""
    
    min_delay_ms: int = 100
    """Minimum delay (maximum speed)."""
    
    max_delay_ms: int = 500
    """Maximum delay (minimum speed)."""
    
    speed_increase_per_food: int = 5
    """Delay reduction per food eaten (in ms)."""
    
    max_speed_increase: int = 100
    """Maximum total speed increase (in ms)."""
    
    # Score settings
    base_score_per_food: int = 10
    """Base points for eating food."""
    
    score_multiplier: float = 1.0
    """Multiplier for all score calculations."""
    
    combo_bonus_enabled: bool = True
    """Whether combo bonuses are enabled."""
    
    combo_bonus_multiplier: float = 1.5
    """Multiplier for combo bonuses."""
    
    # Gameplay settings
    obstacles_enabled: bool = False
    """Whether obstacles are present on the board."""
    
    obstacle_density: float = 0.0
    """Percentage of board covered by obstacles (0.0 to 0.2)."""
    
    power_ups_enabled: bool = False
    """Whether power-ups spawn."""
    
    power_up_frequency: float = 0.1
    """Chance of power-up spawning per food (0.0 to 1.0)."""
    
    # Snake settings
    initial_snake_length: int = 3
    """Starting snake length."""
    
    max_snake_length: int = 100
    """Maximum snake length allowed."""
    
    tail_damage: bool = False
    """Whether hitting your own tail causes damage (not death)."""
    
    # Advanced settings
    wall_collision: bool = True
    """Whether walls cause death."""
    
    wall_pass_through: bool = False
    """Whether snake can pass through walls (teleport)."""
    
    invincible_start: bool = False
    """Whether snake starts invincible for a few seconds."""
    
    invincible_duration_ms: int = 0
    """Duration of invincibility in milliseconds."""
    
    def __post_init__(self) -> None:
        """Validate difficulty settings."""
        self._validate_settings()
    
    def _validate_settings(self) -> None:
        """Ensure all settings are within valid ranges."""
        # Speed validation
        if self.initial_delay_ms < self.min_delay_ms:
            raise ValueError("initial_delay_ms must be >= min_delay_ms")
        if self.initial_delay_ms > self.max_delay_ms:
            raise ValueError("initial_delay_ms must be <= max_delay_ms")
        if self.min_delay_ms < 30:
            raise ValueError("min_delay_ms cannot be less than 30ms")
        if self.max_delay_ms > 1000:
            raise ValueError("max_delay_ms cannot exceed 1000ms")
        
        # Range validation
        if not 0.0 <= self.obstacle_density <= 0.3:
            raise ValueError("obstacle_density must be between 0.0 and 0.3")
        if not 0.0 <= self.power_up_frequency <= 1.0:
            raise ValueError("power_up_frequency must be between 0.0 and 1.0")
        if self.score_multiplier < 0.5:
            raise ValueError("score_multiplier must be at least 0.5")
        
        # Logical validation
        if self.wall_pass_through and self.wall_collision:
            raise ValueError("Cannot have both wall_collision and wall_pass_through enabled")
    
    def calculate_delay(self, foods_eaten: int) -> int:
        """
        Calculate current delay based on foods eaten.
        
        Args:
            foods_eaten: Number of foods consumed.
            
        Returns:
            Current delay in milliseconds.
        """
        speed_increase = min(
            foods_eaten * self.speed_increase_per_food,
            self.max_speed_increase
        )
        delay = self.initial_delay_ms - speed_increase
        return max(self.min_delay_ms, min(self.max_delay_ms, delay))
    
    def calculate_score(self, foods_eaten: int, combo: int = 1) -> int:
        """
        Calculate score for eating food.
        
        Args:
            foods_eaten: Total foods eaten in game.
            combo: Current combo multiplier.
            
        Returns:
            Points awarded for this food.
        """
        base = self.base_score_per_food
        if self.combo_bonus_enabled and combo > 1:
            base *= (1 + (combo - 1) * 0.5 * self.combo_bonus_multiplier)
        return int(base * self.score_multiplier)
    
    def calculate_obstacle_count(self, board_width: int, board_height: int) -> int:
        """
        Calculate number of obstacles for given board size.
        
        Args:
            board_width: Width of the game board.
            board_height: Height of the game board.
            
        Returns:
            Number of obstacles to place.
        """
        if not self.obstacles_enabled:
            return 0
        
        # Calculate playable area (excluding borders)
        playable_area = (board_width - 4) * (board_height - 2)
        return max(0, int(playable_area * self.obstacle_density))
    
    def get_power_up_chance(self) -> float:
        """Get the probability of a power-up spawning."""
        return self.power_up_frequency if self.power_ups_enabled else 0.0


# Standard difficulty presets
DIFFICULTY_PRESETS: Dict[Difficulty, DifficultySettings] = {
    Difficulty.EASY: DifficultySettings(
        name="Easy",
        description="Perfect for beginners - slow and steady!",
        initial_delay_ms=250,
        min_delay_ms=150,
        max_delay_ms=400,
        speed_increase_per_food=3,
        max_speed_increase=80,
        base_score_per_food=10,
        score_multiplier=1.0,
        obstacles_enabled=False,
        obstacle_density=0.0,
        power_ups_enabled=False,
        power_up_frequency=0.0,
        initial_snake_length=3,
        max_snake_length=150,
        tail_damage=True,
    ),
    
    Difficulty.NORMAL: DifficultySettings(
        name="Normal",
        description="Balanced gameplay for most players.",
        initial_delay_ms=180,
        min_delay_ms=100,
        max_delay_ms=300,
        speed_increase_per_food=5,
        max_speed_increase=100,
        base_score_per_food=10,
        score_multiplier=1.0,
        obstacles_enabled=False,
        obstacle_density=0.0,
        power_ups_enabled=True,
        power_up_frequency=0.1,
        initial_snake_length=3,
        max_snake_length=100,
        tail_damage=True,
    ),
    
    Difficulty.HARD: DifficultySettings(
        name="Hard",
        description="For experienced players who want a challenge.",
        initial_delay_ms=150,
        min_delay_ms=80,
        max_delay_ms=250,
        speed_increase_per_food=7,
        max_speed_increase=120,
        base_score_per_food=15,
        score_multiplier=1.5,
        obstacles_enabled=True,
        obstacle_density=0.05,
        power_ups_enabled=True,
        power_up_frequency=0.15,
        initial_snake_length=4,
        max_snake_length=80,
        tail_damage=False,
    ),
    
    Difficulty.EXPERT: DifficultySettings(
        name="Expert",
        description="Serious challenge - speed and precision required.",
        initial_delay_ms=120,
        min_delay_ms=60,
        max_delay_ms=200,
        speed_increase_per_food=10,
        max_speed_increase=150,
        base_score_per_food=20,
        score_multiplier=2.0,
        obstacles_enabled=True,
        obstacle_density=0.10,
        power_ups_enabled=True,
        power_up_frequency=0.2,
        initial_snake_length=5,
        max_snake_length=60,
        tail_damage=False,
        wall_collision=True,
    ),
    
    Difficulty.INSANE: DifficultySettings(
        name="Insane",
        description="Only for true masters - good luck!",
        initial_delay_ms=100,
        min_delay_ms=45,
        max_delay_ms=180,
        speed_increase_per_food=12,
        max_speed_increase=180,
        base_score_per_food=25,
        score_multiplier=2.5,
        obstacles_enabled=True,
        obstacle_density=0.15,
        power_ups_enabled=True,
        power_up_frequency=0.25,
        initial_snake_length=5,
        max_snake_length=50,
        tail_damage=False,
        wall_collision=True,
    ),
}


@dataclass
class DifficultyProgression:
    """
    Handles difficulty progression over time or score.
    
    Allows for dynamic difficulty adjustment based on player
    performance or game time.
    """
    
    enabled: bool = False
    """Whether difficulty progression is enabled."""
    
    progression_type: str = "score"
    """Type of progression: 'score', 'time', or 'foods'."""
    
    base_difficulty: Difficulty = Difficulty.NORMAL
    """Starting difficulty level."""
    
    # Score-based progression
    score_thresholds: List[int] = field(default_factory=lambda: [100, 300, 500, 1000])
    """Score thresholds for difficulty increases."""
    
    speed_increase_per_threshold: int = 10
    """Additional speed increase per threshold reached."""
    
    # Time-based progression
    time_interval_ms: int = 60000
    """Time between difficulty increases (in ms)."""
    
    time_speed_increase: int = 5
    """Speed increase per time interval."""
    
    # Food-based progression
    food_thresholds: List[int] = field(default_factory=lambda: [10, 25, 50, 100])
    """Food counts for difficulty increases."""
    
    food_speed_increase: int = 8
    """Speed increase per food threshold."""
    
    # Limits
    max_progression_level: int = 5
    """Maximum number of difficulty increases."""
    
    def get_progression_level(self, score: int = 0, 
                             time_elapsed: int = 0,
                             foods_eaten: int = 0) -> int:
        """
        Calculate current progression level.
        
        Args:
            score: Current game score.
            time_elapsed: Time elapsed in milliseconds.
            foods_eaten: Number of foods eaten.
            
        Returns:
            Current progression level (0 to max_progression_level).
        """
        if not self.enabled:
            return 0
        
        level = 0
        
        if self.progression_type == "score":
            level = sum(1 for t in self.score_thresholds if score >= t)
        elif self.progression_type == "time":
            level = min(time_elapsed // self.time_interval_ms, self.max_progression_level)
        elif self.progression_type == "foods":
            level = sum(1 for t in self.food_thresholds if foods_eaten >= t)
        
        return min(level, self.max_progression_level)
    
    def get_additional_speed_increase(self, score: int = 0,
                                     time_elapsed: int = 0,
                                     foods_eaten: int = 0) -> int:
        """
        Calculate additional speed increase from progression.
        
        Args:
            score: Current game score.
            time_elapsed: Time elapsed in milliseconds.
            foods_eaten: Number of foods eaten.
            
        Returns:
            Additional speed increase in milliseconds.
        """
        level = self.get_progression_level(score, time_elapsed, foods_eaten)
        
        if self.progression_type == "score":
            return level * self.speed_increase_per_threshold
        elif self.progression_type == "time":
            return level * self.time_speed_increase
        elif self.progression_type == "foods":
            return level * self.food_speed_increase
        
        return 0


class DifficultyFactory:
    """
    Factory class for creating and managing difficulty configurations.
    
    Provides methods for creating, modifying, and combining
    difficulty settings.
    """
    
    @staticmethod
    def get_settings(difficulty: Difficulty) -> DifficultySettings:
        """
        Get settings for a difficulty level.
        
        Args:
            difficulty: The difficulty level.
            
        Returns:
            DifficultySettings for the specified difficulty.
        """
        if difficulty == Difficulty.CUSTOM:
            return DifficultySettings(
                name="Custom",
                description="Custom difficulty settings",
                initial_delay_ms=150,
                min_delay_ms=80,
                max_delay_ms=300,
                speed_increase_per_food=5,
                max_speed_increase=100,
                base_score_per_food=10,
                score_multiplier=1.0,
                obstacles_enabled=False,
                obstacle_density=0.0,
                power_ups_enabled=True,
                power_up_frequency=0.1,
                initial_snake_length=3,
                max_snake_length=100,
                tail_damage=True,
            )
        
        if difficulty not in DIFFICULTY_PRESETS:
            raise ValueError(f"Unknown difficulty: {difficulty}")
        
        return DIFFICULTY_PRESETS[difficulty]
    
    @staticmethod
    def create_custom(
        name: str,
        initial_delay_ms: int = 150,
        min_delay_ms: int = 80,
        max_delay_ms: int = 300,
        speed_increase_per_food: int = 5,
        max_speed_increase: int = 100,
        base_score_per_food: int = 10,
        score_multiplier: float = 1.0,
        obstacles_enabled: bool = False,
        obstacle_density: float = 0.0,
        power_ups_enabled: bool = True,
        power_up_frequency: float = 0.1,
        initial_snake_length: int = 3,
        max_snake_length: int = 100,
        tail_damage: bool = True,
    ) -> DifficultySettings:
        """
        Create custom difficulty settings.
        
        Args:
            name: Name for the custom difficulty.
            initial_delay_ms: Initial movement delay.
            min_delay_ms: Minimum delay (max speed).
            max_delay_ms: Maximum delay (min speed).
            speed_increase_per_food: Speed increase per food.
            max_speed_increase: Maximum speed increase.
            base_score_per_food: Base score per food.
            score_multiplier: Score multiplier.
            obstacles_enabled: Whether obstacles are enabled.
            obstacle_density: Obstacle density (0.0 to 0.3).
            power_ups_enabled: Whether power-ups are enabled.
            power_up_frequency: Power-up spawn frequency.
            initial_snake_length: Starting snake length.
            max_snake_length: Maximum snake length.
            tail_damage: Whether tail hit causes damage.
            
        Returns:
            New DifficultySettings instance.
        """
        return DifficultySettings(
            name=name,
            description="Custom difficulty",
            initial_delay_ms=initial_delay_ms,
            min_delay_ms=min_delay_ms,
            max_delay_ms=max_delay_ms,
            speed_increase_per_food=speed_increase_per_food,
            max_speed_increase=max_speed_increase,
            base_score_per_food=base_score_per_food,
            score_multiplier=score_multiplier,
            obstacles_enabled=obstacles_enabled,
            obstacle_density=obstacle_density,
            power_ups_enabled=power_ups_enabled,
            power_up_frequency=power_up_frequency,
            initial_snake_length=initial_snake_length,
            max_snake_length=max_snake_length,
            tail_damage=tail_damage,
        )
    
    @staticmethod
    def modify_settings(
        base_difficulty: Difficulty,
        speed_modifier: float = 1.0,
        score_modifier: float = 1.0,
        obstacles_modifier: float = 1.0,
    ) -> DifficultySettings:
        """
        Create modified difficulty settings based on a base difficulty.
        
        Args:
            base_difficulty: Base difficulty to modify.
            speed_modifier: Multiplier for speed settings (>1 = faster).
            score_modifier: Multiplier for score settings.
            obstacles_modifier: Multiplier for obstacle density.
            
        Returns:
            Modified DifficultySettings.
        """
        base = DifficultyFactory.get_settings(base_difficulty)
        
        # Apply speed modifier (inverted since higher speed = lower delay)
        speed_factor = 1.0 / speed_modifier
        modified = DifficultySettings(
            name=f"{base.name} (Modified)",
            description=f"Modified {base.name} difficulty",
            initial_delay_ms=int(base.initial_delay_ms * speed_factor),
            min_delay_ms=int(base.min_delay_ms * speed_factor),
            max_delay_ms=int(base.max_delay_ms * speed_factor),
            speed_increase_per_food=int(base.speed_increase_per_food * speed_factor),
            max_speed_increase=int(base.max_speed_increase * speed_factor),
            base_score_per_food=int(base.base_score_per_food * score_modifier),
            score_multiplier=base.score_multiplier * score_modifier,
            obstacles_enabled=base.obstacles_enabled,
            obstacle_density=min(0.3, base.obstacle_density * obstacles_modifier),
            power_ups_enabled=base.power_ups_enabled,
            power_up_frequency=base.power_up_frequency,
            initial_snake_length=base.initial_snake_length,
            max_snake_length=base.max_snake_length,
            tail_damage=base.tail_damage,
        )
        
        return modified
    
    @staticmethod
    def interpolate_difficulty(
        difficulty_a: Difficulty,
        difficulty_b: Difficulty,
        factor: float,
    ) -> DifficultySettings:
        """
        Create difficulty settings interpolated between two difficulties.
        
        Args:
            difficulty_a: First difficulty.
            difficulty_b: Second difficulty.
            factor: Interpolation factor (0.0 = difficulty_a, 1.0 = difficulty_b).
            
        Returns:
            Interpolated DifficultySettings.
        """
        if not 0.0 <= factor <= 1.0:
            raise ValueError("Factor must be between 0.0 and 1.0")
        
        settings_a = DifficultyFactory.get_settings(difficulty_a)
        settings_b = DifficultyFactory.get_settings(difficulty_b)
        
        def interpolate(a: float, b: float, f: float) -> float:
            return a + (b - a) * f
        
        return DifficultySettings(
            name=f"{settings_a.name} -> {settings_b.name}",
            description=f"Interpolated difficulty ({factor:.0%})",
            initial_delay_ms=int(interpolate(settings_a.initial_delay_ms,
                                            settings_b.initial_delay_ms, factor)),
            min_delay_ms=int(interpolate(settings_a.min_delay_ms,
                                        settings_b.min_delay_ms, factor)),
            max_delay_ms=int(interpolate(settings_a.max_delay_ms,
                                        settings_b.max_delay_ms, factor)),
            speed_increase_per_food=int(interpolate(settings_a.speed_increase_per_food,
                                                   settings_b.speed_increase_per_food, factor)),
            max_speed_increase=int(interpolate(settings_a.max_speed_increase,
                                              settings_b.max_speed_increase, factor)),
            base_score_per_food=int(interpolate(settings_a.base_score_per_food,
                                               settings_b.base_score_per_food, factor)),
            score_multiplier=interpolate(settings_a.score_multiplier,
                                        settings_b.score_multiplier, factor),
            obstacles_enabled=settings_b.obstacles_enabled if factor > 0.5 else settings_a.obstacles_enabled,
            obstacle_density=interpolate(settings_a.obstacle_density,
                                        settings_b.obstacle_density, factor),
            power_ups_enabled=settings_b.power_ups_enabled if factor > 0.5 else settings_a.power_ups_enabled,
            power_up_frequency=interpolate(settings_a.power_up_frequency,
                                          settings_b.power_up_frequency, factor),
            initial_snake_length=int(interpolate(settings_a.initial_snake_length,
                                                settings_b.initial_snake_length, factor)),
            max_snake_length=int(interpolate(settings_a.max_snake_length,
                                            settings_b.max_snake_length, factor)),
            tail_damage=settings_b.tail_damage if factor > 0.5 else settings_a.tail_damage,
        )
    
    @staticmethod
    def get_all_difficulties() -> List[Tuple[Difficulty, DifficultySettings]]:
        """
        Get all available difficulty levels with their settings.
        
        Returns:
            List of (Difficulty, DifficultySettings) tuples.
        """
        return [(d, DIFFICULTY_PRESETS[d]) for d in DIFFICULTY_PRESETS.keys()]
    
    @staticmethod
    def get_difficulty_names() -> List[str]:
        """Get list of all difficulty names."""
        return [d.name for d in DIFFICULTY_PRESETS.keys()]
    
    @staticmethod
    def parse_difficulty(name: str) -> Difficulty:
        """
        Parse difficulty name to Difficulty enum.
        
        Args:
            name: Difficulty name (case-insensitive).
            
        Returns:
            Corresponding Difficulty enum value.
            
        Raises:
            ValueError: If name is not recognized.
        """
        name_upper = name.upper()
        for difficulty in Difficulty:
            if difficulty.name == name_upper:
                return difficulty
        raise ValueError(f"Unknown difficulty: {name}")


def get_difficulty_comparison(difficulty_a: Difficulty, 
                             difficulty_b: Difficulty) -> Dict[str, float]:
    """
    Compare two difficulties and return ratio of their settings.
    
    Args:
        difficulty_a: First difficulty.
        difficulty_b: Second difficulty.
        
    Returns:
        Dictionary with comparison ratios (b/a).
    """
    settings_a = DifficultyFactory.get_settings(difficulty_a)
    settings_b = DifficultyFactory.get_settings(difficulty_b)
    
    return {
        "initial_speed": settings_b.initial_delay_ms / settings_a.initial_delay_ms,
        "min_speed": settings_b.min_delay_ms / settings_a.min_delay_ms,
        "score_multiplier": settings_b.score_multiplier / settings_a.score_multiplier,
        "obstacle_density": (settings_b.obstacle_density or 0.001) / 
                           (settings_a.obstacle_density or 0.001),
        "power_up_frequency": (settings_b.power_up_frequency or 0.001) / 
                             (settings_a.power_up_frequency or 0.001),
    }


def main() -> None:
    """Demonstrate difficulty functionality."""
    print("=" * 60)
    print("DIFFICULTY LEVELS DEMONSTRATION")
    print("=" * 60)
    print()
    
    # Show all difficulties
    print("Available Difficulties:")
    print("-" * 40)
    for difficulty, settings in DifficultyFactory.get_all_difficulties():
        print(f"  {difficulty.name:12} - {settings.name:12} - {settings.description}")
    print()
    
    # Show difficulty details
    print("Normal Difficulty Settings:")
    print("-" * 40)
    normal = DifficultyFactory.get_settings(Difficulty.NORMAL)
    print(f"  Initial Delay: {normal.initial_delay_ms}ms")
    print(f"  Min Delay: {normal.min_delay_ms}ms")
    print(f"  Max Delay: {normal.max_delay_ms}ms")
    print(f"  Score Multiplier: {normal.score_multiplier}x")
    print(f"  Obstacles: {normal.obstacles_enabled}")
    print(f"  Power-ups: {normal.power_ups_enabled}")
    print()
    
    # Show speed progression
    print("Speed Progression (Normal):")
    print("-" * 40)
    for foods in [0, 5, 10, 20, 30]:
        delay = normal.calculate_delay(foods)
        print(f"  After {foods:2d} foods: {delay:4d}ms")
    print()
    
    # Show score calculation
    print("Score Calculation (Normal):")
    print("-" * 40)
    for combo in [1, 2, 3, 4]:
        score = normal.calculate_score(foods_eaten=10, combo=combo)
        print(f"  Combo {combo}: {score} points")
    print()
    
    # Show custom difficulty
    print("Custom Difficulty:")
    print("-" * 40)
    custom = DifficultyFactory.create_custom(
        name="Beginner",
        initial_delay_ms=300,
        min_delay_ms=200,
        obstacles_enabled=False,
        tail_damage=True,
    )
    print(f"  Name: {custom.name}")
    print(f"  Initial Delay: {custom.initial_delay_ms}ms")
    print(f"  Obstacles: {custom.obstacles_enabled}")
    print()
    
    # Show difficulty modification
    print("Modified Difficulty (Hard x 1.5 speed):")
    print("-" * 40)
    modified = DifficultyFactory.modify_settings(
        Difficulty.HARD,
        speed_modifier=1.5,
        score_modifier=1.2,
    )
    print(f"  Name: {modified.name}")
    print(f"  Initial Delay: {modified.initial_delay_ms}ms")
    print(f"  Score Multiplier: {modified.score_multiplier}x")
    print()
    
    # Show difficulty comparison
    print("Difficulty Comparison (Easy vs Hard):")
    print("-" * 40)
    comparison = get_difficulty_comparison(Difficulty.EASY, Difficulty.HARD)
    for key, value in comparison.items():
        print(f"  {key}: {value:.2f}x")


if __name__ == "__main__":
    main()

---

## Summary

### Key Features Implemented:

#### `game_config.py`:
- **`GameConfig`**: Main configuration container with sub-configurations
- **`BoardConfig`**: Board dimensions and bounds validation
- **`SpeedConfig`**: Speed settings with delay calculation
- **`VisualConfig`**: Visual appearance and ANSI colors
- **`KeyboardConfig`**: Keyboard controls with direction mapping
- **`SoundConfig`**: Sound settings (placeholder for future)
- **`ConfigManager`**: Singleton for centralized config access
- **JSON persistence**: Load/save configuration files
- **Dot-notation access**: `config_manager.set_value("board.width", 50)`

#### `difficulty_levels.py`:
- **`Difficulty` enum**: EASY, NORMAL, HARD, EXPERT, INSANE, CUSTOM
- **`DifficultySettings`**: Complete settings per difficulty
- **`DIFFICULTY_PRESETS`**: Pre-configured difficulty levels
- **`DifficultyFactory`**: Create/modify/interpolate difficulties
- **`DifficultyProgression`**: Dynamic difficulty over time/score
- **Speed progression**: Automatic speed increase on eating food
- **Score calculation**: Base score with combo bonuses

### Usage Example:

from snake.config.game_config import GameConfig, ConfigManager
from snake.config.difficulty_levels import DifficultyFactory, Difficulty

# Load configuration
config = GameConfig.default()
config.load()  # Load from ~/.snake/config.json

# Get difficulty settings
settings = DifficultyFactory.get_settings(Difficulty.HARD)
print(f"Initial delay: {settings.initial_delay_ms}ms")

# Calculate speed after eating 10 foods
current_delay = settings.calculate_delay(foods_eaten=10)
print(f"Delay after 10 foods: {current_delay}ms")

# Use config manager
manager = ConfigManager()
manager.set_value("board.width", 60)
manager.save()
