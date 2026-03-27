"""
Food Manager Module

The Food Manager handles food spawning, placement (ensuring it doesn't overlap with snake),
food types, and food collection tracking.

This module implements the FoodManager class which manages all food-related logic.
"""

from __future__ import annotations

import logging
import random
from enum import Enum, auto
from typing import List, Tuple, Optional, Set, Callable, TYPE_CHECKING
from dataclasses import dataclass, field
from collections import deque

if TYPE_CHECKING:
    from .snake_controller import SnakeController

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class FoodType(Enum):
    """Enum representing different types of food with varying effects."""
    NORMAL = auto()        # Standard food, +1 length, base points
    SUPER = auto()         # Super food, +2 length, bonus points
    GHOST = auto()         # Ghost food, passes through snake (special mode)
    SHRINK = auto()        # Negative food, -1 length (risky)
    SPEED_UP = auto()      # Speed boost food
    SLOW_DOWN = auto()     # Slow down food


@dataclass
class FoodProperties:
    """Properties associated with a food type."""
    type: FoodType
    points: int = 10
    length_change: int = 1
    color: str = "🍎"  # ASCII representation
    sound: Optional[str] = None
    probability: float = 1.0  # Spawn probability (0.0 to 1.0)
    
    @classmethod
    def defaults(cls) -> dict[FoodType, "FoodProperties"]:
        """Get default properties for all food types."""
        return {
            FoodType.NORMAL: cls(
                type=FoodType.NORMAL,
                points=10,
                length_change=1,
                color="*",
                probability=0.85
            ),
            FoodType.SUPER: cls(
                type=FoodType.SUPER,
                points=25,
                length_change=2,
                color="@",
                probability=0.10
            ),
            FoodType.SHRINK: cls(
                type=FoodType.SHRINK,
                points=5,
                length_change=-1,
                color=".",
                probability=0.03
            ),
            FoodType.SPEED_UP: cls(
                type=FoodType.SPEED_UP,
                points=15,
                length_change=1,
                color="+",
                probability=0.02
            ),
        }


@dataclass
class Food:
    """
    Represents a piece of food in the game.
    
    Attributes:
        x: X coordinate (column)
        y: Y coordinate (row)
        food_type: Type of food
        points: Points awarded when eaten
        is_collected: Whether this food has been collected
    """
    x: int
    y: int
    food_type: FoodType = FoodType.NORMAL
    points: int = 10
    is_collected: bool = False
    
    def __hash__(self) -> int:
        """Make food hashable for set operations."""
        return hash((self.x, self.y, self.food_type))
    
    def __eq__(self, other: object) -> bool:
        """Check equality with another food item."""
        if isinstance(other, Food):
            return (self.x == other.x and 
                    self.y == other.y and 
                    self.food_type == other.food_type)
        return False
    
    def to_tuple(self) -> Tuple[int, int]:
        """Convert position to tuple representation."""
        return (self.x, self.y)
    
    def collect(self) -> None:
        """Mark this food as collected."""
        self.is_collected = True
    
    @property
    def position(self) -> Tuple[int, int]:
        """Get position as a tuple."""
        return self.to_tuple()


class FoodManager:
    """
    Manager for food items in the Snake game.
    
    Responsibilities:
    - Spawn food at random valid positions
    - Ensure food doesn't overlap with snake or other food
    - Support multiple food types with different properties
    - Track food spawn history for variety
    - Provide food collision detection support
    
    The manager uses a weighted random selection to determine food type,
    with NORMAL food being most common.
    
    Example:
        manager = FoodManager()
        manager.set_snake_positions([(5, 5), (4, 5), (3, 5)])
        manager.spawn_food()
        print(manager.food_position)
    """
    
    def __init__(self, seed: Optional[int] = None) -> None:
        """
        Initialize the food manager.
        
        Args:
            seed: Optional random seed for reproducible food placement.
        """
        # Current food item
        self._current_food: Optional[Food] = None
        
        # Game bounds
        self._width: int = 0
        self._height: int = 0
        
        # Snake positions (for collision avoidance)
        self._snake_positions: Set[Tuple[int, int]] = set()
        
        # Other food positions (for multi-food support)
        self._other_food_positions: Set[Tuple[int, int]] = set()
        
        # Food properties configuration
        self._food_properties: dict[FoodType, FoodProperties] = FoodProperties.defaults()
        
        # Random number generator
        self._rng = random.Random(seed)
        
        # Spawn history (for avoiding immediate respawns in same location)
        self._spawn_history: deque[Tuple[int, int]] = deque(maxlen=10)
        
        # Statistics
        self._foods_spawned: int = 0
        self._foods_by_type: dict[FoodType, int] = {ft: 0 for ft in FoodType}
        
        # Callback for when food is eaten
        self._on_food_eaten: Optional[Callable[[Food], None]] = None
        
        logger.debug("FoodManager initialized with seed: %s", seed)
    
    # Properties
    @property
    def current_food(self) -> Optional[Food]:
        """Get the current food item."""
        return self._current_food
    
    @property
    def food_position(self) -> Optional[Tuple[int, int]]:
        """Get the current food position as a tuple."""
        return self._current_food.to_tuple() if self._current_food else None
    
    @property
    def food_type(self) -> Optional[FoodType]:
        """Get the current food type."""
        return self._current_food.food_type if self._current_food else None
    
    @property
    def food_points(self) -> int:
        """Get the points for the current food."""
        return self._current_food.points if self._current_food else 0
    
    @property
    def width(self) -> int:
        """Get the game width."""
        return self._width
    
    @property
    def height(self) -> int:
        """Get the game height."""
        return self._height
    
    @property
    def foods_spawned(self) -> int:
        """Get total foods spawned."""
        return self._foods_spawned
    
    def set_game_bounds(self, width: int, height: int) -> None:
        """
        Set the game boundaries.
        
        Args:
            width: Game width in cells.
            height: Game height in cells.
        """
        if width < 2 or height < 2:
            raise ValueError("Game dimensions must be at least 2x2")
        
        self._width = width
        self._height = height
        logger.debug("Game bounds set to %s x %s", width, height)
    
    def set_snake_positions(self, positions: List[Tuple[int, int]]) -> None:
        """
        Set the current snake positions for collision avoidance.
        
        Args:
            positions: List of (x, y) tuples representing snake segments.
        """
        self._snake_positions = set(positions)
        logger.debug("Snake positions updated: %s segments", len(positions))
    
    def set_food_properties(self, properties: dict[FoodType, FoodProperties]) -> None:
        """
        Set custom food properties.
        
        Args:
            properties: Dictionary mapping food types to their properties.
        """
        self._food_properties = properties
        logger.debug("Food properties updated")
    
    def configure_food_type(self, food_type: FoodType, **kwargs) -> None:
        """
        Configure a specific food type's properties.
        
        Args:
            food_type: The food type to configure.
            **kwargs: Property overrides (points, length_change, etc.)
        """
        if food_type not in self._food_properties:
            self._food_properties[food_type] = FoodProperties(type=food_type)
        
        for key, value in kwargs.items():
            if hasattr(self._food_properties[food_type], key):
                setattr(self._food_properties[food_type], key, value)
        
        logger.debug("Configured food type %s: %s", food_type, kwargs)
    
    def spawn_food(self) -> Food:
        """
        Spawn a new food item at a random valid position.
        
        Returns:
            The spawned Food object.
            
        Raises:
            RuntimeError: If game bounds are not set.
            RuntimeError: If no valid position is available.
        """
        if self._width == 0 or self._height == 0:
            raise RuntimeError("Game bounds not set. Call set_game_bounds() first.")
        
        # Determine food type based on probabilities
        food_type = self._select_food_type()
        props = self._food_properties.get(food_type)
        
        # Try to find a valid position
        max_attempts = self._width * self._height
        attempt = 0
        
        while attempt < max_attempts:
            position = self._get_random_valid_position()
            if position is not None:
                x, y = position
                
                # Create food item
                food = Food(
                    x=x,
                    y=y,
                    food_type=food_type,
                    points=props.points if props else 10
                )
                
                # Update tracking
                self._current_food = food
                self._other_food_positions.add(position)
                self._spawn_history.append(position)
                self._foods_spawned += 1
                self._foods_by_type[food_type] += 1
                
                logger.debug("Spawned %s food at %s", food_type, position)
                return food
            
            attempt += 1
        
        # If we get here, no valid position was found
        raise RuntimeError(f"No valid position available for food (tried {max_attempts} times)")
    
    def _select_food_type(self) -> FoodType:
        """
        Select a food type based on configured probabilities.
        
        Returns:
            The selected food type.
        """
        # Build weighted list
        options = []
        total_weight = 0.0
        
        for food_type, props in self._food_properties.items():
            if props.probability > 0:
                options.append((food_type, props.probability))
                total_weight += props.probability
        
        if not options:
            return FoodType.NORMAL
        
        # Weighted random selection
        rand_value = self._rng.random() * total_weight
        cumulative = 0.0
        
        for food_type, weight in options:
            cumulative += weight
            if rand_value <= cumulative:
                return food_type
        
        return FoodType.NORMAL
    
    def _get_random_valid_position(self) -> Optional[Tuple[int, int]]:
        """
        Get a random position that doesn't overlap with snake or other food.
        
        Returns:
            A valid (x, y) position, or None if not found.
        """
        # Generate all possible positions
        all_positions = set()
        for x in range(self._width):
            for y in range(self._height):
                all_positions.add((x, y))
        
        # Remove occupied positions
        available = all_positions - self._snake_positions - self._other_food_positions
        
        if not available:
            return None
        
        # Prefer positions not in recent spawn history
        available_not_recent = available - set(self._spawn_history)
        if available_not_recent:
            positions_to_choose = available_not_recent
        else:
            positions_to_choose = available
        
        return self._rng.choice(list(positions_to_choose))
    
    def clear_food(self) -> None:
        """Clear the current food without spawning a new one."""
        if self._current_food:
            self._other_food_positions.discard(self._current_food.to_tuple())
        self._current_food = None
        logger.debug("Food cleared")
    
    def is_position_food(self, x: int, y: int) -> bool:
        """
        Check if a position contains food.
        
        Args:
            x: X coordinate to check.
            y: Y coordinate to check.
            
        Returns:
            True if the position contains the current food.
        """
        return self._current_food is not None and \
               self._current_food.x == x and \
               self._current_food.y == y
    
    def eat_food(self) -> Optional[Food]:
        """
        Mark the current food as eaten and return it.
        
        Returns:
            The eaten Food object, or None if no food exists.
        """
        if self._current_food:
            food = self._current_food
            food.collect()
            
            if self._on_food_eaten:
                self._on_food_eaten(food)
            
            logger.debug("Food eaten at %s", food.to_tuple())
            return food
        return None
    
    def set_food_eaten_callback(self, callback: Callable[[Food], None]) -> None:
        """
        Set a callback to be called when food is eaten.
        
        Args:
            callback: Function to call with the eaten Food object.
        """
        self._on_food_eaten = callback
        logger.debug("Food eaten callback registered")
    
    def get_available_positions(self) -> List[Tuple[int, int]]:
        """
        Get all positions available for food spawning.
        
        Returns:
            List of (x, y) tuples that are available.
        """
        all_positions = set()
        for x in range(self._width):
            for y in range(self._height):
                all_positions.add((x, y))
        
        return list(all_positions - self._snake_positions - self._other_food_positions)
    
    def get_food_density(self) -> float:
        """
        Calculate the food spawn density (available positions / total positions).
        
        Returns:
            Density ratio between 0.0 and 1.0.
        """
        total_positions = self._width * self._height
        if total_positions == 0:
            return 0.0
        
        available = len(self.get_available_positions())
        return available / total_positions
    
    def get_statistics(self) -> dict:
        """
        Get food manager statistics.
        
        Returns:
            Dictionary containing various statistics.
        """
        return {
            "foods_spawned": self._foods_spawned,
            "foods_by_type": dict(self._foods_by_type),
            "available_positions": len(self.get_available_positions()),
            "density": self.get_food_density(),
            "history_size": len(self._spawn_history),
        }
    
    def reset(self) -> None:
        """Reset the food manager to initial state."""
        self._current_food = None
        self._other_food_positions.clear()
        self._spawn_history.clear()
        self._foods_spawned = 0
        self._foods_by_type = {ft: 0 for ft in FoodType}
        logger.debug("FoodManager reset")
    
    def set_seed(self, seed: int) -> None:
        """
        Set a new random seed.
        
        Args:
            seed: The new seed value.
        """
        self._rng.seed(seed)
        logger.debug("Random seed set to %s", seed)
    
    def __repr__(self) -> str:
        """String representation of the food manager."""
        pos = self.food_position
        return f"FoodManager(food={pos}, type={self.food_type.name if self.food_type else None})"
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        pos = self.food_position
        food_str = f"at {pos}" if pos else "none"
        return f"Food: {food_str}"


if __name__ == "__main__":
    # Example usage and basic test
    print("Testing FoodManager module...")
    
    # Create manager
    manager = FoodManager(seed=42)
    
    # Set game bounds
    manager.set_game_bounds(width=20, height=10)
    
    # Set snake positions
    snake_positions = [(5, 5), (4, 5), (3, 5)]
    manager.set_snake_positions(snake_positions)
    
    print(f"Game bounds: {manager.width} x {manager.height}")
    print(f"Snake positions: {snake_positions}")
    
    # Spawn food
    print("\nSpawning food...")
    for i in range(5):
        food = manager.spawn_food()
        print(f"  Food {i+1}: {food}")
        manager.clear_food()
    
    # Spawn and keep food
    manager.spawn_food()
    print(f"\nCurrent food: {manager.food_position}")
    print(f"Food type: {manager.food_type}")
    print(f"Food points: {manager.food_points}")
    
    # Test position checking
    print(f"\nIs position {manager.food_position} food? {manager.is_position_food(*manager.food_position)}")
    
    # Test statistics
    stats = manager.get_statistics()
    print(f"\nStatistics: {stats}")
    
    print("\nFoodManager module loaded successfully!")
