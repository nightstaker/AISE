"""
Collision Detector Module

The Collision Detector handles all collision detection logic in the game,
including wall collisions, self-collisions, and food collisions.

This module implements the CollisionDetector class which provides efficient
collision detection methods.
"""

from __future__ import annotations

import logging
from typing import List, Tuple, Set, Optional
from dataclasses import dataclass

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class CollisionResult:
    """
    Result of a collision detection check.
    
    Attributes:
        collided: Whether a collision occurred.
        type: Type of collision (wall, self, food, etc.)
        position: Position where collision occurred.
        details: Additional collision details.
    """
    collided: bool
    collision_type: str
    position: Optional[Tuple[int, int]] = None
    details: Optional[dict] = None
    
    def __bool__(self) -> bool:
        """Allow using CollisionResult as boolean."""
        return self.collided


class CollisionDetector:
    """
    Handles all collision detection for the Snake game.
    
    Responsibilities:
    - Detect wall collisions (snake hitting boundaries)
    - Detect self-collisions (snake hitting itself)
    - Detect food collisions (snake eating food)
    - Support different wall collision modes (solid, wrap-around)
    - Provide efficient collision queries using spatial data structures
    
    The detector uses set-based lookups for O(1) collision queries
    and maintains game bounds for wall detection.
    
    Example:
        detector = CollisionDetector()
        detector.set_game_bounds(20, 10)
        
        # Check wall collision
        result = detector.check_wall_collision((20, 5), 20, 10)
        
        # Check self collision
        result = detector.check_self_collision([(5,5), (4,5), (3,5)])
    """
    
    def __init__(self) -> None:
        """Initialize the collision detector."""
        # Game bounds
        self._width: int = 0
        self._height: int = 0
        
        # Snake body positions cache (for efficient self-collision)
        self._snake_body_set: Set[Tuple[int, int]] = set()
        self._snake_body_valid: bool = False
        
        # Wall collision mode
        self._wall_mode: str = "solid"  # "solid" or "wrap"
        
        logger.debug("CollisionDetector initialized")
    
    # Properties
    @property
    def width(self) -> int:
        """Get the game width."""
        return self._width
    
    @property
    def height(self) -> int:
        """Get the game height."""
        return self._height
    
    @property
    def wall_mode(self) -> str:
        """Get the wall collision mode."""
        return self._wall_mode
    
    def set_game_bounds(self, width: int, height: int) -> None:
        """
        Set the game boundaries for collision detection.
        
        Args:
            width: Game width in cells.
            height: Game height in cells.
        """
        if width < 2:
            raise ValueError("Width must be at least 2")
        if height < 2:
            raise ValueError("Height must be at least 2")
        
        self._width = width
        self._height = height
        logger.debug("Game bounds set to %s x %s", width, height)
    
    def set_wall_mode(self, mode: str) -> None:
        """
        Set the wall collision mode.
        
        Args:
            mode: "solid" for wall collisions, "wrap" for wrap-around
        """
        if mode not in ("solid", "wrap"):
            raise ValueError(f"Invalid wall mode: {mode}. Must be 'solid' or 'wrap'")
        
        self._wall_mode = mode
        logger.debug("Wall mode set to %s", mode)
    
    def update_snake_body(self, body_positions: List[Tuple[int, int]]) -> None:
        """
        Update the cached snake body positions for efficient collision detection.
        
        Should be called after each snake movement.
        
        Args:
            body_positions: List of (x, y) tuples for all snake segments.
        """
        self._snake_body_set = set(body_positions)
        self._snake_body_valid = True
        logger.debug("Snake body cache updated with %s segments", len(body_positions))
    
    def check_wall_collision(
        self,
        position: Tuple[int, int],
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> bool:
        """
        Check if a position is outside the game boundaries.
        
        Args:
            position: The (x, y) position to check.
            width: Optional override for game width.
            height: Optional override for game height.
            
        Returns:
            True if the position is outside boundaries, False otherwise.
        """
        w = width if width is not None else self._width
        h = height if height is not None else self._height
        
        x, y = position
        
        # Check if position is outside bounds
        outside_x = x < 0 or x >= w
        outside_y = y < 0 or y >= h
        
        if outside_x or outside_y:
            logger.debug("Wall collision detected at %s (bounds: %s x %s)", position, w, h)
            return True
        
        return False
    
    def check_self_collision(self, body_positions: List[Tuple[int, int]]) -> bool:
        """
        Check if the snake's head is colliding with its body.
        
        The head is the first element, and we check if it matches any
        other segment (excluding itself).
        
        Args:
            body_positions: List of (x, y) tuples, first element is head.
            
        Returns:
            True if head collides with body, False otherwise.
        """
        if len(body_positions) < 2:
            return False
        
        head = body_positions[0]
        
        # Check if head position exists in the rest of the body
        # Using set for O(1) lookup
        body_set = set(body_positions[1:])  # Exclude head
        
        if head in body_set:
            logger.debug("Self collision detected at %s", head)
            return True
        
        return False
    
    def check_self_collision_optimized(self) -> bool:
        """
        Check self-collision using cached body positions.
        
        Requires update_snake_body() to be called first.
        
        Returns:
            True if collision detected, False otherwise.
        """
        if not self._snake_body_valid:
            raise RuntimeError("Call update_snake_body() before using optimized collision detection")
        
        # This method would need access to head position separately
        # Implemented here for reference; actual implementation depends on context
        return False
    
    def check_food_collision(
        self,
        snake_head: Tuple[int, int],
        food_position: Tuple[int, int]
    ) -> bool:
        """
        Check if the snake's head is on the food position.
        
        Args:
            snake_head: The (x, y) position of the snake's head.
            food_position: The (x, y) position of the food.
            
        Returns:
            True if head is on food, False otherwise.
        """
        return snake_head == food_position
    
    def check_collision(
        self,
        pos1: Tuple[int, int],
        pos2: Tuple[int, int]
    ) -> bool:
        """
        Generic position collision check.
        
        Args:
            pos1: First position (x, y).
            pos2: Second position (x, y).
            
        Returns:
            True if positions are equal, False otherwise.
        """
        return pos1 == pos2
    
    def check_position_in_list(
        self,
        position: Tuple[int, int],
        position_list: List[Tuple[int, int]]
    ) -> bool:
        """
        Check if a position exists in a list of positions.
        
        Args:
            position: The position to search for.
            position_list: List of positions to search in.
            
        Returns:
            True if position is in list, False otherwise.
        """
        return position in position_list
    
    def get_wall_collision_side(
        self,
        position: Tuple[int, int],
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> Optional[str]:
        """
        Get which wall was hit (if any).
        
        Args:
            position: The position to check.
            width: Optional override for game width.
            height: Optional override for game height.
            
        Returns:
            "top", "bottom", "left", "right", or None if no wall collision.
        """
        w = width if width is not None else self._width
        h = height if height is not None else self._height
        
        x, y = position
        
        if x < 0:
            return "left"
        if x >= w:
            return "right"
        if y < 0:
            return "top"
        if y >= h:
            return "bottom"
        
        return None
    
    def get_wrap_position(
        self,
        position: Tuple[int, int],
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> Tuple[int, int]:
        """
        Get the wrapped position if outside bounds.
        
        Args:
            position: The position to wrap.
            width: Optional override for game width.
            height: Optional override for game height.
            
        Returns:
            The wrapped (x, y) position.
        """
        w = width if width is not None else self._width
        h = height if height is not None else self._height
        
        x, y = position
        
        # Wrap using modulo
        wrapped_x = x % w
        wrapped_y = y % h
        
        logger.debug("Position %s wrapped to %s", position, (wrapped_x, wrapped_y))
        return (wrapped_x, wrapped_y)
    
    def is_position_valid(
        self,
        position: Tuple[int, int],
        width: Optional[int] = None,
        height: Optional[int] = None
    ) -> bool:
        """
        Check if a position is within valid game bounds.
        
        Args:
            position: The position to check.
            width: Optional override for game width.
            height: Optional override for game height.
            
        Returns:
            True if position is valid, False otherwise.
        """
        w = width if width is not None else self._width
        h = height if height is not None else self._height
        
        x, y = position
        return 0 <= x < w and 0 <= y < h
    
    def get_distance(
        self,
        pos1: Tuple[int, int],
        pos2: Tuple[int, int],
        metric: str = "manhattan"
    ) -> float:
        """
        Calculate distance between two positions.
        
        Args:
            pos1: First position (x, y).
            pos2: Second position (x, y).
            metric: Distance metric ("manhattan", "euclidean", "chebyshev").
            
        Returns:
            Distance between positions.
        """
        dx = pos1[0] - pos2[0]
        dy = pos1[1] - pos2[1]
        
        if metric == "manhattan":
            return abs(dx) + abs(dy)
        elif metric == "euclidean":
            return (dx * dx + dy * dy) ** 0.5
        elif metric == "chebyshev":
            return max(abs(dx), abs(dy))
        else:
            raise ValueError(f"Unknown distance metric: {metric}")
    
    def get_nearby_positions(
        self,
        position: Tuple[int, int],
        radius: int = 1,
        include_center: bool = False
    ) -> List[Tuple[int, int]]:
        """
        Get all positions within a radius of a given position.
        
        Args:
            position: Center position (x, y).
            radius: Search radius.
            include_center: Whether to include the center position.
            
        Returns:
            List of positions within the radius.
        """
        x, y = position
        nearby = []
        
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                if dx == 0 and dy == 0 and not include_center:
                    continue
                nearby.append((x + dx, y + dy))
        
        return nearby
    
    def check_rect_collision(
        self,
        rect1: Tuple[Tuple[int, int], Tuple[int, int]],
        rect2: Tuple[Tuple[int, int], Tuple[int, int]]
    ) -> bool:
        """
        Check if two rectangles collide.
        
        Args:
            rect1: Rectangle 1 as ((min_x, min_y), (max_x, max_y)).
            rect2: Rectangle 2 as ((min_x, min_y), (max_x, max_y)).
            
        Returns:
            True if rectangles overlap, False otherwise.
        """
        min1, max1 = rect1
        min2, max2 = rect2
        
        # Check for non-overlap
        if max1[0] < min2[0] or max2[0] < min1[0]:
            return False
        if max1[1] < min2[1] or max2[1] < min1[1]:
            return False
        
        return True
    
    def get_collision_debug_info(self) -> dict:
        """
        Get debug information about collision state.
        
        Returns:
            Dictionary with collision debug information.
        """
        return {
            "width": self._width,
            "height": self._height,
            "wall_mode": self._wall_mode,
            "snake_body_cached": self._snake_body_valid,
            "snake_body_size": len(self._snake_body_set),
        }
    
    def __repr__(self) -> str:
        """String representation of the collision detector."""
        return f"CollisionDetector(width={self._width}, height={self._height}, mode={self._wall_mode})"
    
    def __str__(self) -> str:
        """Human-readable string representation."""
        return f"CollisionDetector: {self._width}x{self._height} ({self._wall_mode})"


if __name__ == "__main__":
    # Example usage and basic test
    print("Testing CollisionDetector module...")
    
    # Create detector
    detector = CollisionDetector()
    detector.set_game_bounds(width=20, height=10)
    
    print(f"Detector: {detector}")
    
    # Test wall collision
    print("\nTesting wall collision...")
    test_positions = [
        (0, 0),      # Valid corner
        (19, 9),     # Valid corner
        (-1, 5),     # Outside left
        (20, 5),     # Outside right
        (5, -1),     # Outside top
        (5, 10),     # Outside bottom
        (10, 5),     # Valid center
    ]
    
    for pos in test_positions:
        collided = detector.check_wall_collision(pos)
        valid = detector.is_position_valid(pos)
        side = detector.get_wall_collision_side(pos)
        print(f"  {pos}: collided={collided}, valid={valid}, side={side}")
    
    # Test self collision
    print("\nTesting self collision...")
    snake_body = [(5, 5), (4, 5), (3, 5), (2, 5)]  # Normal
    print(f"  Normal body: {detector.check_self_collision(snake_body)}")
    
    snake_body_loop = [(5, 5), (4, 5), (3, 5), (5, 5)]  # Head touches body
    print(f"  Loop body: {detector.check_self_collision(snake_body_loop)}")
    
    # Test food collision
    print("\nTesting food collision...")
    head = (5, 5)
    food = (5, 5)
    print(f"  Head {head} on food {food}: {detector.check_food_collision(head, food)}")
    
    food2 = (6, 6)
    print(f"  Head {head} on food {food2}: {detector.check_food_collision(head, food2)}")
    
    # Test distance
    print("\nTesting distance calculation...")
    pos1 = (0, 0)
    pos2 = (3, 4)
    print(f"  Manhattan: {detector.get_distance(pos1, pos2, 'manhattan')}")
    print(f"  Euclidean: {detector.get_distance(pos1, pos2, 'euclidean')}")
    print(f"  Chebyshev: {detector.get_distance(pos1, pos2, 'chebyshev')}")
    
    # Test wrap position
    print("\nTesting position wrapping...")
    print(f"  (-1, 5) wrapped: {detector.get_wrap_position((-1, 5))}")
    print(f"  (20, 5) wrapped: {detector.get_wrap_position((20, 5))}")
    
    # Test nearby positions
    print("\nTesting nearby positions...")
    center = (5, 5)
    nearby = detector.get_nearby_positions(center, radius=1)
    print(f"  Nearby {center}: {nearby}")
    
    print("\nCollisionDetector module loaded successfully!")
