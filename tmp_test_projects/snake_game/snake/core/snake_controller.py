"""
Snake Controller Module

The Snake Controller manages the snake entity - its position, movement, growth, and state.
This is the player's controllable element in the game.

This module implements the SnakeController class which handles all snake-related logic.
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import List, Tuple, Optional, TYPE_CHECKING
from collections import deque
from dataclasses import dataclass

if TYPE_CHECKING:
    from .game_engine import GameEngine

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Direction(Enum):
    """Enum representing the four cardinal directions the snake can move."""
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()


# Direction deltas for movement calculations
DIRECTION_DELTAS: dict[Direction, Tuple[int, int]] = {
    Direction.UP: (0, -1),
    Direction.DOWN: (0, 1),
    Direction.LEFT: (-1, 0),
    Direction.RIGHT: (1, 0),
}

# Opposite directions (used to prevent 180-degree turns)
OPPOSITE_DIRECTIONS: dict[Direction, Direction] = {
    Direction.UP: Direction.DOWN,
    Direction.DOWN: Direction.UP,
    Direction.LEFT: Direction.RIGHT,
    Direction.RIGHT: Direction.LEFT,
}

# Keyboard key mappings to directions
KEY_TO_DIRECTION: dict[str, Direction] = {
    "w": Direction.UP,
    "W": Direction.UP,
    "up": Direction.UP,
    "Up": Direction.UP,
    "UP": Direction.UP,
    "↑": Direction.UP,
    "s": Direction.DOWN,
    "S": Direction.DOWN,
    "down": Direction.DOWN,
    "Down": Direction.DOWN,
    "DOWN": Direction.DOWN,
    "↓": Direction.DOWN,
    "a": Direction.LEFT,
    "A": Direction.LEFT,
    "left": Direction.LEFT,
    "Left": Direction.LEFT,
    "LEFT": Direction.LEFT,
    "←": Direction.LEFT,
    "d": Direction.RIGHT,
    "D": Direction.RIGHT,
    "right": Direction.RIGHT,
    "Right": Direction.RIGHT,
    "RIGHT": Direction.RIGHT,
    "→": Direction.RIGHT,
}


@dataclass
class SnakeSegment:
    """
    Represents a single segment of the snake.
    
    Attributes:
        x: X coordinate (column)
        y: Y coordinate (row)
    """
    x: int
    y: int
    
    def __hash__(self) -> int:
        """Make segments hashable for set operations."""
        return hash((self.x, self.y))
    
    def __eq__(self, other: object) -> bool:
        """Check equality with another segment."""
        if isinstance(other, SnakeSegment):
            return self.x == other.x and self.y == other.y
        if isinstance(other, tuple):
            return self.x == other[0] and self.y == other[1]
        return False
    
    def to_tuple(self) -> Tuple[int, int]:
        """Convert to tuple representation."""
        return (self.x, self.y)
    
    @classmethod
    def from_tuple(cls, pos: Tuple[int, int]) -> "SnakeSegment":
        """Create a segment from a tuple."""
        return cls(x=pos[0], y=pos[1])


class SnakeController:
    """
    Controller for the snake entity in the Snake game.
    
    Responsibilities:
    - Maintain snake position and segments
    - Handle snake movement based on current direction
    - Process input for direction changes
    - Handle snake growth when food is eaten
    - Prevent invalid direction changes (180-degree turns)
    
    The snake is represented as a deque of segments, where the first element
    is the head and the last element is the tail.
    
    Example:
        controller = SnakeController()
        controller.reset(width=20, height=10, initial_length=3)
        controller.set_direction(Direction.RIGHT)
        controller.move()
    """
    
    def __init__(self) -> None:
        """Initialize the snake controller."""
        # Snake body as a deque of segments (head first, tail last)
        self._segments: deque[SnakeSegment] = deque()
        
        # Current movement direction
        self._current_direction: Direction = Direction.RIGHT
        
        # Next direction (set by input, applied on next move)
        self._next_direction: Optional[Direction] = None
        
        # Game bounds
        self._width: int = 0
        self._height: int = 0
        
        # Movement buffer (prevents multiple direction changes per tick)
        self._direction_changed_this_tick: bool = False
        
        logger.debug("SnakeController initialized")
    
    # Properties
    @property
    def segments(self) -> List[SnakeSegment]:
        """Get a copy of all snake segments."""
        return list(self._segments)
    
    @property
    def head_position(self) -> Optional[SnakeSegment]:
        """Get the head segment position."""
        return self._segments[0] if self._segments else None
    
    @property
    def tail_position(self) -> Optional[SnakeSegment]:
        """Get the tail segment position."""
        return self._segments[-1] if self._segments else None
    
    @property
    def body_positions(self) -> List[Tuple[int, int]]:
        """Get all body positions as list of tuples."""
        return [seg.to_tuple() for seg in self._segments]
    
    @property
    def body_positions_set(self) -> set[Tuple[int, int]]:
        """Get all body positions as a set for O(1) lookups."""
        return {seg.to_tuple() for seg in self._segments}
    
    @property
    def length(self) -> int:
        """Get the current length of the snake."""
        return len(self._segments)
    
    @property
    def current_direction(self) -> Direction:
        """Get the current movement direction."""
        return self._current_direction
    
    @property
    def width(self) -> int:
        """Get the game width."""
        return self._width
    
    @property
    def height(self) -> int:
        """Get the game height."""
        return self._height
    
    def reset(self, width: int, height: int, initial_length: int = 3) -> None:
        """
        Reset the snake to initial state.
        
        Args:
            width: Game width in cells.
            height: Game height in cells.
            initial_length: Initial snake length.
        """
        if width < 2 or height < 2:
            raise ValueError("Game dimensions must be at least 2x2")
        if initial_length < 1:
            raise ValueError("Initial length must be at least 1")
        if initial_length > width * height:
            raise ValueError(f"Initial length ({initial_length}) exceeds game area ({width}x{height})")
        
        self._width = width
        self._height = height
        self._current_direction = Direction.RIGHT
        self._next_direction = None
        self._direction_changed_this_tick = False
        
        # Initialize snake starting from center-left, extending leftward
        start_x = width // 2
        start_y = height // 2
        
        self._segments = deque()
        for i in range(initial_length):
            self._segments.append(SnakeSegment(x=start_x - i, y=start_y))
        
        logger.debug("Snake reset to length %s at position %s", initial_length, self.head_position)
    
    def set_direction(self, direction: Direction) -> bool:
        """
        Set the next direction for the snake.
        
        Prevents 180-degree turns (reversing direction).
        
        Args:
            direction: The direction to move toward.
            
        Returns:
            True if direction was set, False if invalid (180-degree turn).
        """
        # Check if this would be a 180-degree turn
        if direction == OPPOSITE_DIRECTIONS[self._current_direction]:
            logger.debug("Rejected 180-degree turn from %s to %s", 
                        self._current_direction, direction)
            return False
        
        # Check if direction already changed this tick
        if self._direction_changed_this_tick:
            logger.debug("Direction already changed this tick, ignoring")
            return False
        
        self._next_direction = direction
        self._direction_changed_this_tick = True
        logger.debug("Direction set to %s", direction)
        return True
    
    def handle_input(self, key: str) -> None:
        """
        Handle keyboard input for direction changes.
        
        Args:
            key: The key that was pressed.
        """
        direction = KEY_TO_DIRECTION.get(key)
        if direction:
            self.set_direction(direction)
        elif key in ("w", "a", "s", "d"):
            # Fallback for WASD keys
            self.handle_input(key.upper())
    
    def move(self) -> Tuple[int, int]:
        """
        Move the snake one step in the current direction.
        
        Returns:
            The new head position as a tuple (x, y).
        """
        # Apply queued direction change
        if self._next_direction is not None:
            self._current_direction = self._next_direction
            self._next_direction = None
        self._direction_changed_this_tick = False
        
        # Calculate new head position
        head = self.head_position
        if head is None:
            raise RuntimeError("Snake has no segments!")
        
        delta_x, delta_y = DIRECTION_DELTAS[self._current_direction]
        new_head_x = head.x + delta_x
        new_head_y = head.y + delta_y
        
        # Create new head segment
        new_head = SnakeSegment(x=new_head_x, y=new_head_y)
        
        # Add new head to front of deque
        self._segments.appendleft(new_head)
        
        # Remove tail (snake moves without growing)
        self._segments.pop()
        
        logger.debug("Snake moved to %s, direction: %s", new_head, self._current_direction)
        
        return new_head.to_tuple()
    
    def grow(self) -> None:
        """
        Grow the snake by one segment.
        
        The new segment is added at the current tail position,
        effectively extending the snake.
        """
        if not self._segments:
            logger.warning("Cannot grow empty snake")
            return
        
        # Get the current tail position
        tail = self.tail_position
        if tail is None:
            return
        
        # Add a new segment at the tail position
        # This makes the snake effectively one segment longer
        new_tail = SnakeSegment(x=tail.x, y=tail.y)
        self._segments.append(new_tail)
        
        logger.debug("Snake grew to length %s", self.length)
    
    def shrink(self) -> None:
        """
        Shrink the snake by one segment.
        
        Removes the tail segment.
        """
        if len(self._segments) > 1:
            self._segments.pop()
            logger.debug("Snake shrank to length %s", self.length)
    
    def set_position(self, x: int, y: int) -> None:
        """
        Set the snake's head position directly.
        
        Useful for debugging or special game mechanics.
        
        Args:
            x: X coordinate for the head.
            y: Y coordinate for the head.
        """
        if not self._segments:
            self._segments.append(SnakeSegment(x=x, y=y))
        else:
            self._segments[0] = SnakeSegment(x=x, y=y)
        logger.debug("Snake position set to %s, %s", x, y)
    
    def is_position_occupied(self, x: int, y: int) -> bool:
        """
        Check if a position is occupied by the snake.
        
        Args:
            x: X coordinate to check.
            y: Y coordinate to check.
            
        Returns:
            True if the position is occupied by any snake segment.
        """
        return (x, y) in self.body_positions_set
    
    def get_segment_at(self, index: int) -> Optional[SnakeSegment]:
        """
        Get a specific segment by index.
        
        Args:
            index: Index of the segment (0 = head).
            
        Returns:
            The segment at the given index, or None if invalid.
        """
        if 0 <= index < len(self._segments):
            return self._segments[index]
        return None
    
    def contains_position(self, segment: SnakeSegment) -> bool:
        """
        Check if the snake contains a specific segment.
        
        Args:
            segment: The segment to check for.
            
        Returns:
            True if the segment is part of the snake.
        """
        return segment in self._segments
    
    def get_bounding_box(self) -> Tuple[Tuple[int, int], Tuple[int, int]]:
        """
        Get the bounding box of the snake.
        
        Returns:
            Tuple of (min_pos, max_pos) where each is (x, y).
        """
        if not self._segments:
            return ((0, 0), (0, 0))
        
        min_x = min(seg.x for seg in self._segments)
        min_y = min(seg.y for seg in self._segments)
        max_x = max(seg.x for seg in self._segments)
        max_y = max(seg.y for seg in self._segments)
        
        return ((min_x, min_y), (max_x, max_y))
    
    def serialize(self) -> dict:
        """
        Serialize the snake state to a dictionary.
        
        Returns:
            Dictionary containing the snake's state.
        """
        return {
            "segments": [seg.to_tuple() for seg in self._segments],
            "direction": self._current_direction.name,
            "width": self._width,
            "height": self._height,
        }
    
    def deserialize(self, data: dict) -> None:
        """
        Deserialize the snake state from a dictionary.
        
        Args:
            data: Dictionary containing the snake's state.
        """
        self._width = data.get("width", 20)
        self._height = data.get("height", 10)
        self._current_direction = Direction[data.get("direction", "RIGHT")]
        self._next_direction = None
        self._direction_changed_this_tick = False
        self._segments = deque(
            SnakeSegment(x=x, y=y) for x, y in data.get("segments", [])
        )
    
    def __repr__(self) -> str:
        """String representation of the snake controller."""
        return f"SnakeController(length={self.length}, direction={self._current_direction.name})"
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        positions = " -> ".join(str(seg.to_tuple()) for seg in self._segments[:5])
        if len(self._segments) > 5:
            positions += f" ... ({len(self._segments)} total)"
        return f"Snake: {positions}"


if __name__ == "__main__":
    # Example usage and basic test
    print("Testing SnakeController module...")
    
    # Create controller
    controller = SnakeController()
    
    # Reset with initial settings
    controller.reset(width=20, height=10, initial_length=3)
    
    print(f"Initial state: {controller}")
    print(f"Head position: {controller.head_position}")
    print(f"Length: {controller.length}")
    print(f"Direction: {controller.current_direction}")
    
    # Test movement
    print("\nMoving snake...")
    for i in range(5):
        controller.move()
        print(f"  Step {i+1}: Head at {controller.head_position}")
    
    # Test direction change
    print("\nChanging direction...")
    controller.set_direction(Direction.DOWN)
    controller.move()
    print(f"After turning DOWN: Head at {controller.head_position}")
    
    # Test growth
    print("\nGrowing snake...")
    controller.grow()
    print(f"After growing: Length = {controller.length}")
    
    # Test 180-degree turn prevention
    print("\nTesting 180-degree turn prevention...")
    result = controller.set_direction(Direction.UP)
    print(f"Attempt to turn UP (180°): {result}")
    
    # Test serialization
    print("\nTesting serialization...")
    data = controller.serialize()
    print(f"Serialized: {data}")
    
    controller2 = SnakeController()
    controller2.deserialize(data)
    print(f"Deserialized: {controller2}")
    
    print("\nSnakeController module loaded successfully!")
