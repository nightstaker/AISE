# DETAILED DESIGN DOCUMENT

## Snake Game Application

---

## Table of Contents
1. [Game Engine](#module-game-engine)
2. [Snake Model](#module-snake-model)
3. [Food Model](#module-food-model)
4. [Collision Detection](#module-collision-detection)
5. [Input Handler](#module-input-handler)
6. [Display Module](#module-display-module)
7. [Score Manager](#module-score-manager)
8. [Game State](#module-game-state)
9. [Configuration](#module-configuration)
10. [Main Module](#module-main-module)

---

## Module: Game Engine

**File**: `snake/engine/game_engine.py`

### 1. Module Overview
The Game Engine is the central coordinator of the Snake game. It manages the game loop, synchronizes all game components, handles the game lifecycle, and processes game events.

**Key Functionalities**:
- Main game loop execution
- Game state management coordination
- Tick/event-driven updates
- Component lifecycle management
- Game over handling

### 2. Classes and Functions

##### Class: GameEngine
**Purpose**: Central coordinator that manages the game loop and orchestrates all game components.

**Attributes**:
- `game_state: GameState` - Current game state manager
- `snake: Snake` - The player's snake instance
- `food: Food` - Food manager instance
- `collision: CollisionDetector` - Collision detection instance
- `input_handler: InputHandler` - Input management instance
- `display: Display` - Rendering instance
- `score_manager: ScoreManager` - Score tracking instance
- `config: Config` - Configuration settings
- `running: bool` - Game running flag
- `tick_interval: float` - Game tick interval in seconds
- `last_tick: float` - Timestamp of last game tick

**Methods**:
```python
def __init__(self, config: Config) -> None:
    """
    Initialize the Game Engine with all game components.
    
    Args:
        config: Configuration settings for the game
    """
    pass

def initialize(self) -> None:
    """Initialize all game components and set up initial game state."""
    pass

def start(self) -> None:
    """Start the game loop."""
    pass

def stop(self) -> None:
    """Stop the game loop and clean up resources."""
    pass

def run(self) -> None:
    """
    Main game loop.
    
    Handles:
    - Game tick scheduling
    - Input processing
    - State updates
    - Rendering
    """
    pass

def _game_tick(self) -> None:
    """
    Execute one game tick.
    
    Flow:
    1. Process input
    2. Move snake
    3. Check collisions
    4. Update score
    5. Check game over
    """
    pass

def _handle_collision(self) -> None:
    """
    Handle collision events.
    
    - Food collision: Grow snake, spawn new food, update score
    - Wall/self collision: Trigger game over
    """
    pass

def _check_game_over(self) -> bool:
    """
    Check if game is over.
    
    Returns:
        True if game should end, False otherwise
    """
    pass

def reset(self) -> None:
    """Reset game to initial state for new game."""
    pass

def pause(self) -> None:
    """Pause the game."""
    pass

def resume(self) -> None:
    """Resume paused game."""
    pass

def get_game_speed(self) -> float:
    """Get current game speed (tick interval)."""
    pass

def set_game_speed(self, speed: float) -> None:
    """
    Set game speed.
    
    Args:
        speed: New tick interval in seconds (lower = faster)
    """
    pass
```

#### 3. Interfaces

**Public API**:
- `start()` - Begin game
- `stop()` - End game
- `reset()` - Restart game
- `pause()` / `resume()` - Control game flow
- `get_game_speed()` / `set_game_speed()` - Speed control

**Events/Callbacks**:
- `on_game_start`: Called when game begins
- `on_game_over`: Called when game ends (score passed)
- `on_level_up`: Called when player reaches new level
- `on_pause`: Called when game is paused
- `on_resume`: Called when game resumes

#### 4. Dependencies

```python
# Internal imports
from snake.core.game_state import GameState
from snake.models.snake import Snake
from snake.models.food import Food
from snake.core.collision import CollisionDetector
from snake.io.input_handler import InputHandler
from snake.io.display import Display
from snake.core.score_manager import ScoreManager
from snake.config.config import Config

# External imports
import time
from typing import Callable, Optional
from dataclasses import dataclass
```

---

## Module: Snake Model

**File**: `snake/models/snake.py`

### 1. Module Overview
The Snake model manages the player's snake entity including position tracking, movement logic, growth mechanics, and direction management.

**Key Functionalities**:
- Snake body segment management
- Movement in four directions
- Growth when eating food
- Direction validation
- Head and body position tracking

### 2. Classes and Functions

##### Enum: Direction
**Purpose**: Represents the four possible movement directions.

```python
class Direction(Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    
    def opposite(self) -> 'Direction':
        """Return the opposite direction."""
        pass
    
    def to_vector(self) -> tuple[int, int]:
        """Convert direction to (x, y) movement vector."""
        pass
```

##### Class: Snake
**Purpose**: Represents the player's snake with all movement and state logic.

**Attributes**:
- `body: list[tuple[int, int]]` - List of (x, y) positions for each segment (head first)
- `direction: Direction` - Current movement direction
- `next_direction: Direction` - Queued direction change
- `growing: bool` - Whether snake is currently growing
- `growth_pending: int` - Number of segments to add
- `alive: bool` - Whether snake is alive
- `max_length: int` - Maximum allowed length (0 = unlimited)

**Methods**:
```python
def __init__(
    self,
    start_position: tuple[int, int],
    initial_length: int = 3,
    direction: Direction = Direction.RIGHT,
    max_length: int = 0
) -> None:
    """
    Initialize snake at starting position.
    
    Args:
        start_position: (x, y) starting position of snake head
        initial_length: Starting snake length
        direction: Initial movement direction
        max_length: Maximum snake length (0 = unlimited)
    """
    pass

def get_head(self) -> tuple[int, int]:
    """
    Get the position of the snake's head.
    
    Returns:
        (x, y) position of head
    """
    pass

def get_body(self) -> list[tuple[int, int]]:
    """
    Get all body segment positions.
    
    Returns:
        List of (x, y) positions from head to tail
    """
    pass

def get_length(self) -> int:
    """Get current snake length."""
    pass

def set_direction(self, new_direction: Direction) -> bool:
    """
    Queue a direction change.
    
    Args:
        new_direction: Direction to move toward
        
    Returns:
        True if direction change is valid, False if invalid (e.g., reversing)
    """
    pass

def move(self) -> None:
    """
    Move snake one step in current direction.
    
    - Calculates new head position
    - Adds new head to body
    - Removes tail (unless growing)
    """
    pass

def grow(self, segments: int = 1) -> None:
    """
    Add segments to snake length.
    
    Args:
        segments: Number of segments to add
    """
    pass

def check_self_collision(self) -> bool:
    """
    Check if head collides with any body segment.
    
    Returns:
        True if collision detected, False otherwise
    """
    pass

def check_boundary_collision(self, width: int, height: int) -> bool:
    """
    Check if head is outside game boundaries.
    
    Args:
        width: Game board width
        height: Game board height
        
    Returns:
        True if collision detected, False otherwise
    """
    pass

def reset(self, start_position: tuple[int, int]) -> None:
    """
    Reset snake to initial state.
    
    Args:
        start_position: New starting position
    """
    pass

def contains_position(self, position: tuple[int, int]) -> bool:
    """
    Check if snake occupies a given position.
    
    Args:
        position: (x, y) position to check
        
    Returns:
        True if position is occupied by snake
    """
    pass

def get_next_head_position(self) -> tuple[int, int]:
    """
    Calculate where head will be after next move.
    
    Returns:
        (x, y) predicted head position
    """
    pass
```

#### 3. Interfaces

**Public API**:
- `get_head()` - Get head position
- `get_body()` - Get all segment positions
- `set_direction()` - Change movement direction
- `move()` - Advance snake one step
- `grow()` - Add segments to snake
- `check_self_collision()` - Detect self-collision
- `check_boundary_collision()` - Detect wall collision

#### 4. Dependencies

```python
# External imports
from enum import Enum
from typing import Optional
from dataclasses import dataclass, field
```

---

## Module: Food Model

**File**: `snake/models/food.py`

### 1. Module Overview
The Food model manages food entities in the game including spawning, positioning, and food types.

**Key Functionalities**:
- Random food spawning
- Food position validation
- Food type management
- Score values per food type

### 2. Classes and Functions

##### Enum: FoodType
**Purpose**: Represents different types of food with varying properties.

```python
class FoodType(Enum):
    NORMAL = "normal"      # Standard food, 10 points
    SUPER = "super"        # Bonus food, 50 points
    GROWTH = "growth"      # Extra growth, 20 points
    SPEED = "speed"        # Speed boost, 30 points
```

##### Class: Food
**Purpose**: Manages food spawning and positioning on the game board.

**Attributes**:
- `position: tuple[int, int]` - Current food position
- `food_type: FoodType` - Type of current food
- `board_width: int` - Game board width
- `board_height: int` - Game board height
- `occupied_positions: set[tuple[int, int]]` - Positions that cannot spawn food
- `super_food_probability: float` - Chance to spawn super food
- `current_food: FoodItem | None` - Current active food

**Methods**:
```python
def __init__(
    self,
    board_width: int,
    board_height: int,
    super_food_probability: float = 0.1
) -> None:
    """
    Initialize food manager.
    
    Args:
        board_width: Width of game board
        board_height: Height of game board
        super_food_probability: Chance (0-1) to spawn super food
    """
    pass

def spawn(self, occupied_positions: set[tuple[int, int]]) -> tuple[int, int]:
    """
    Spawn food at random valid position.
    
    Args:
        occupied_positions: Positions that cannot contain food
        
    Returns:
        (x, y) position of spawned food
    """
    pass

def get_position(self) -> tuple[int, int]:
    """Get current food position."""
    pass

def get_food_type(self) -> FoodType:
    """Get current food type."""
    pass

def get_score_value(self) -> int:
    """
    Get score value for current food.
    
    Returns:
        Points awarded for eating this food
    """
    pass

def set_occupied_positions(self, positions: set[tuple[int, int]]) -> None:
    """
    Update positions that cannot spawn food.
    
    Args:
        positions: Set of (x, y) positions to avoid
    """
    pass

def is_valid_position(self, position: tuple[int, int]) -> bool:
    """
    Check if position is valid for food spawn.
    
    Args:
        position: (x, y) position to check
        
    Returns:
        True if position is valid
    """
    pass

def _generate_random_position(self) -> tuple[int, int]:
    """Generate random position within board bounds."""
    pass

def _determine_food_type(self) -> FoodType:
    """Determine type of food to spawn based on probability."""
    pass
```

##### Class: FoodItem
**Purpose**: Represents a single food entity with its properties.

```python
@dataclass
class FoodItem:
    position: tuple[int, int]
    food_type: FoodType
    score_value: int
    growth_bonus: int = 1
    expires_at: Optional[float] = None  # For timed special food
    
    def is_expired(self) -> bool:
        """Check if food has expired."""
        pass
```

#### 3. Interfaces

**Public API**:
- `spawn()` - Create food at random position
- `get_position()` - Get current food location
- `get_food_type()` - Get food type
- `get_score_value()` - Get points for food
- `is_valid_position()` - Validate spawn position

#### 4. Dependencies

```python
# External imports
from enum import Enum
from typing import Optional
from dataclasses import dataclass
import random
import time
```

---

## Module: Collision Detection

**File**: `snake/core/collision.py`

### 1. Module Overview
The Collision Detection module handles all collision checks in the game including wall collisions, self-collisions, and food collisions.

**Key Functionalities**:
- Wall collision detection
- Self-collision detection
- Food collision detection
- Collision event reporting

### 2. Classes and Functions

##### Enum: CollisionType
**Purpose**: Types of collisions that can occur.

```python
class CollisionType(Enum):
    WALL = "wall"
    SELF = "self"
    FOOD = "food"
```

##### Class: CollisionEvent
**Purpose**: Data structure representing a collision event.

```python
@dataclass
class CollisionEvent:
    collision_type: CollisionType
    position: tuple[int, int]
    timestamp: float
    details: Optional[str] = None
```

##### Class: CollisionDetector
**Purpose**: Central collision detection system for the game.

**Attributes**:
- `board_width: int` - Game board width
- `board_height: int` - Game board height
- `wrap_walls: bool` - Whether walls wrap around
- `collision_callbacks: list[Callable]` - Registered collision handlers

**Methods**:
```python
def __init__(
    self,
    board_width: int,
    board_height: int,
    wrap_walls: bool = False
) -> None:
    """
    Initialize collision detector.
    
    Args:
        board_width: Width of game board
        board_height: Height of game board
        wrap_walls: Whether walls wrap (Pac-Man style)
    """
    pass

def check_wall_collision(
    self,
    position: tuple[int, int]
) -> CollisionEvent | None:
    """
    Check if position is outside game boundaries.
    
    Args:
        position: (x, y) position to check
        
    Returns:
        CollisionEvent if collision, None otherwise
    """
    pass

def check_self_collision(
    self,
    head_position: tuple[int, int],
    body_positions: list[tuple[int, int]]
) -> CollisionEvent | None:
    """
    Check if head collides with body.
    
    Args:
        head_position: (x, y) head position
        body_positions: List of (x, y) body positions
        
    Returns:
        CollisionEvent if collision, None otherwise
    """
    pass

def check_food_collision(
    self,
    head_position: tuple[int, int],
    food_position: tuple[int, int]
) -> CollisionEvent | None:
    """
    Check if head collides with food.
    
    Args:
        head_position: (x, y) head position
        food_position: (x, y) food position
        
    Returns:
        CollisionEvent if collision, None otherwise
    """
    pass

def check_all_collisions(
    self,
    snake_head: tuple[int, int],
    snake_body: list[tuple[int, int]],
    food_position: tuple[int, int]
) -> list[CollisionEvent]:
    """
    Check all collision types in one call.
    
    Args:
        snake_head: Snake head position
        snake_body: Snake body positions
        food_position: Food position
        
    Returns:
        List of all collision events detected
    """
    pass

def register_collision_callback(self, callback: Callable[[CollisionEvent], None]) -> None:
    """
    Register a callback for collision events.
    
    Args:
        callback: Function to call on collision
    """
    pass

def _notify_collision(self, event: CollisionEvent) -> None:
    """Notify all registered callbacks of a collision."""
    pass

def get_bounds(self) -> tuple[int, int, int, int]:
    """
    Get game board bounds.
    
    Returns:
        (min_x, max_x, min_y, max_y) bounds
    """
    pass
```

#### 3. Interfaces

**Public API**:
- `check_wall_collision()` - Detect wall hits
- `check_self_collision()` - Detect self hits
- `check_food_collision()` - Detect food hits
- `check_all_collisions()` - Comprehensive check
- `register_collision_callback()` - Event subscription

**Events/Callbacks**:
- `on_collision(CollisionEvent)` - Called when any collision occurs

#### 4. Dependencies

```python
# External imports
from enum import Enum
from typing import Callable, Optional, List
from dataclasses import dataclass
import time
```

---

## Module: Input Handler

**File**: `snake/io/input_handler.py`

### 1. Module Overview
The Input Handler manages all user input including keyboard controls, input validation, and input state management.

**Key Functionalities**:
- Keyboard input capture
- Direction input mapping
- Input validation (no reversing)
- Input buffering
- Command registration

### 2. Classes and Functions

##### Enum: KeyCode
**Purpose**: Represents keyboard keys for game input.

```python
class KeyCode(Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"
    W = "w"
    A = "a"
    S = "s"
    D = "d"
    SPACE = "space"
    ESC = "escape"
    R = "r"
    P = "p"
```

##### Class: InputEvent
**Purpose**: Represents a processed input event.

```python
@dataclass
class InputEvent:
    event_type: str
    key: KeyCode
    timestamp: float
    action: Optional[str] = None
```

##### Class: InputHandler
**Purpose**: Manages game input processing and validation.

**Attributes**:
- `key_direction_map: dict[KeyCode, Direction]` - Key to direction mapping
- `current_direction: Direction | None` - Last processed direction
- `pending_direction: Direction | None` - Buffered direction change
- `input_callbacks: dict[str, list[Callable]]` - Event callbacks
- `input_queue: list[InputEvent]` - Input event queue
- `last_input_time: float` - Timestamp of last input
- `input_cooldown: float` - Minimum time between inputs

**Methods**:
```python
def __init__(self) -> None:
    """Initialize input handler with default key mappings."""
    pass

def initialize(self) -> None:
    """Initialize input system and register key handlers."""
    pass

def shutdown(self) -> None:
    """Clean up input handlers and resources."""
    pass

def get_input(self) -> InputEvent | None:
    """
    Process and return pending input.
    
    Returns:
        InputEvent if input available, None otherwise
    """
    pass

def process_direction_input(self, key: KeyCode) -> bool:
    """
    Process directional input.
    
    Args:
        key: Key pressed
        
    Returns:
        True if direction was validly changed
    """
    pass

def set_current_direction(self, direction: Direction) -> None:
    """
    Set the current movement direction.
    
    Args:
        direction: Current direction
    """
    pass

def can_change_to_direction(self, new_direction: Direction) -> bool:
    """
    Check if direction change is valid (not reversing).
    
    Args:
        new_direction: Proposed new direction
        
    Returns:
        True if change is valid
    """
    pass

def register_callback(
    self,
    event_type: str,
    callback: Callable[[InputEvent], None]
) -> None:
    """
    Register callback for input events.
    
    Args:
        event_type: Type of event to listen for
        callback: Function to call on event
    """
    pass

def get_key_mapping(self) -> dict[KeyCode, Direction]:
    """Get current key to direction mapping."""
    pass

def set_key_mapping(self, mapping: dict[KeyCode, Direction]) -> None:
    """
    Set custom key mapping.
    
    Args:
        mapping: New key to direction mapping
    """
    pass

def handle_key_press(self, key: KeyCode) -> None:
    """
    Handle a key press event.
    
    Args:
        key: Key that was pressed
    """
    pass

def handle_key_release(self, key: KeyCode) -> None:
    """
    Handle a key release event.
    
    Args:
        key: Key that was released
    """
    pass

def _validate_direction_change(self, new_direction: Direction) -> bool:
    """
    Validate that direction change doesn't cause reversal.
    
    Args:
        new_direction: Proposed direction
        
    Returns:
        True if valid
    """
    pass
```

#### 3. Interfaces

**Public API**:
- `get_input()` - Get next input event
- `process_direction_input()` - Handle direction key
- `can_change_to_direction()` - Validate direction change
- `register_callback()` - Subscribe to input events
- `get_key_mapping()` / `set_key_mapping()` - Key mapping management

**Events/Callbacks**:
- `on_direction_change(Direction)` - Called when direction changes
- `on_pause_requested()` - Called when pause key pressed
- `on_restart_requested()` - Called when restart key pressed
- `on_quit_requested()` - Called when quit key pressed

#### 4. Dependencies

```python
# Internal imports
from snake.models.snake import Direction

# External imports
from enum import Enum
from typing import Callable, Optional, List, Dict
from dataclasses import dataclass
import time
```

---

## Module: Display Module

**File**: `snake/io/display.py`

### 1. Module Overview
The Display module handles all visual rendering of the game including the game board, snake, food, score, and UI elements.

**Key Functionalities**:
- Game board rendering
- Snake rendering
- Food rendering
- Score display
- UI updates
- Visual effects

### 2. Classes and Functions

##### Class: Display
**Purpose**: Main rendering system for the game.

**Attributes**:
- `board_width: int` - Game board width in characters
- `board_height: int` - Game board height in characters
- `frame: str` - Frame characters for borders
- `snake_head_char: str` - Character for snake head
- `snake_body_char: str` - Character for snake body
- `food_char: str` - Character for food
- `empty_char: str` - Character for empty space
- `title: str` - Game title
- `show_fps: bool` - Whether to show FPS counter
- `last_render_time: float` - Timestamp of last render

**Methods**:
```python
def __init__(
    self,
    board_width: int = 20,
    board_height: 15,
    title: str = "SNAKE"
) -> None:
    """
    Initialize display system.
    
    Args:
        board_width: Width of game board
        board_height: Height of game board
        title: Game title to display
    """
    pass

def initialize(self) -> None:
    """Initialize display system and clear screen."""
    pass

def shutdown(self) -> None:
    """Clean up display resources."""
    pass

def render(
    self,
    snake_body: list[tuple[int, int]],
    food_position: tuple[int, int],
    score: int,
    high_score: int,
    level: int = 1,
    game_state: str = "playing"
) -> None:
    """
    Render complete game frame.
    
    Args:
        snake_body: List of snake segment positions
        food_position: Food position
        score: Current score
        high_score: High score
        level: Current level
        game_state: Current game state
    """
    pass

def clear_screen(self) -> None:
    """Clear the display screen."""
    pass

def render_header(self, score: int, high_score: int, level: int) -> None:
    """
    Render game header with score information.
    
    Args:
        score: Current score
        high_score: High score
        level: Current level
    """
    pass

def render_board(
    self,
    snake_body: list[tuple[int, int]],
    food_position: tuple[int, int]
) -> None:
    """
    Render game board with snake and food.
    
    Args:
        snake_body: Snake positions
        food_position: Food position
    """
    pass

def render_footer(self, game_state: str, fps: float) -> None:
    """
    Render footer with game state and FPS.
    
    Args:
        game_state: Current game state
        fps: Current frames per second
    """
    pass

def render_snake(self, snake_body: list[tuple[int, int]]) -> str:
    """
    Create string representation of snake.
    
    Args:
        snake_body: Snake positions
        
    Returns:
        String with snake rendered
    """
    pass

def render_food(self, food_position: tuple[int, int]) -> str:
    """
    Create string representation of food.
    
    Args:
        food_position: Food position
        
    Returns:
        String with food rendered
    """
    pass

def render_game_over(self, final_score: int) -> None:
    """
    Render game over screen.
    
    Args:
        final_score: Final score achieved
    """
    pass

def render_pause(self, current_score: int) -> None:
    """
    Render pause screen.
    
    Args:
        current_score: Current score
    """
    pass

def render_start_screen(self) -> None:
    """Render game start screen with instructions."""
    pass

def set_colors(self, enabled: bool = True) -> None:
    """
    Enable or disable color output.
    
    Args:
        enabled: Whether colors are enabled
    """
    pass

def get_fps(self) -> float:
    """Get current frames per second."""
    pass
```

#### 3. Interfaces

**Public API**:
- `render()` - Render complete game frame
- `clear_screen()` - Clear display
- `render_game_over()` - Show game over screen
- `render_pause()` - Show pause screen
- `render_start_screen()` - Show start screen
- `set_colors()` - Toggle color output

#### 4. Dependencies

```python
# External imports
from typing import Optional
import time
import os
import sys
```

---

## Module: Score Manager

**File**: `snake/core/score_manager.py`

### 1. Module Overview
The Score Manager handles all scoring functionality including current score tracking, high score persistence, and score calculations.

**Key Functionalities**:
- Score tracking
- High score persistence
- Score calculation
- Level progression

### 2. Classes and Functions

##### Class: ScoreManager
**Purpose**: Manages game scoring and high scores.

**Attributes**:
- `current_score: int` - Current game score
- `high_score: int` - All-time high score
- `session_high_score: int` - High score for current session
- `level: int` - Current game level
- `points_per_level: int` - Points needed for next level
- `score_file: str` - Path to high score file
- `score_history: list[int]` - Recent scores for statistics

**Methods**:
```python
def __init__(self, score_file: str = "highscore.txt") -> None:
    """
    Initialize score manager.
    
    Args:
        score_file: Path to high score persistence file
    """
    pass

def initialize(self) -> None:
    """Initialize score manager and load high score."""
    pass

def add_score(self, points: int) -> int:
    """
    Add points to current score.
    
    Args:
        points: Points to add
        
    Returns:
        New total score
    """
    pass

def get_score(self) -> int:
    """Get current score."""
    pass

def get_high_score(self) -> int:
    """Get high score."""
    pass

def get_level(self) -> int:
    """Get current level."""
    pass

def check_level_up(self) -> bool:
    """
    Check if player has leveled up.
    
    Returns:
        True if level up occurred
    """
    pass

def reset_score(self) -> None:
    """Reset current score to zero."""
    pass

def save_score(self) -> bool:
    """
    Save current score if it's a new high score.
    
    Returns:
        True if score was saved as high score
    """
    pass

def load_high_score(self) -> int:
    """
    Load high score from file.
    
    Returns:
        High score value
    """
    pass

def _save_high_score(self, score: int) -> None:
    """Save high score to file."""
    pass

def calculate_level(self, score: int) -> int:
    """
    Calculate level from score.
    
    Args:
        score: Score to calculate level for
        
    Returns:
        Level number
    """
    pass

def get_points_for_level(self, level: int) -> int:
    """
    Get points needed for a specific level.
    
    Args:
        level: Level number
        
    Returns:
        Points required
    """
    pass

def get_game_speed_for_level(self, level: int) -> float:
    """
    Get game speed (tick interval) for level.
    
    Args:
        level: Level number
        
    Returns:
        Tick interval in seconds
    """
    pass

def add_to_history(self, score: int) -> None:
    """
    Add score to history for statistics.
    
    Args:
        score: Score to add
    """
    pass

def get_statistics(self) -> dict:
    """
    Get score statistics.
    
    Returns:
        Dictionary with statistical data
    """
    pass
```

#### 3. Interfaces

**Public API**:
- `add_score()` - Add points
- `get_score()` - Get current score
- `get_high_score()` - Get high score
- `check_level_up()` - Check for level up
- `reset_score()` - Reset score
- `get_game_speed_for_level()` - Get speed for level

#### 4. Dependencies

```python
# External imports
from typing import Optional
import json
import os
from pathlib import Path
```

---

## Module: Game State

**File**: `snake/core/game_state.py`

### 1. Module Overview
The Game State module manages the game's lifecycle states and state transitions.

**Key Functionalities**:
- State enumeration
- State transitions
- State validation
- State callbacks

### 2. Classes and Functions

##### Enum: GameStateType
**Purpose**: Represents all possible game states.

```python
class GameStateType(Enum):
    INITIALIZED = "initialized"
    READY = "ready"
    PLAYING = "playing"
    PAUSED = "paused"
    GAME_OVER = "game_over"
    LEVEL_TRANSITION = "level_transition"
```

##### Class: GameState
**Purpose**: Manages game state and transitions.

**Attributes**:
- `current_state: GameStateType` - Current game state
- `previous_state: GameStateType | None` - Previous state
- `state_callbacks: dict[GameStateType, list[Callable]]` - State change callbacks
- `state_history: list[GameStateType]` - State transition history
- `start_time: float` - Game start timestamp
- `play_time: float` - Total play time

**Methods**:
```python
def __init__(self) -> None:
    """Initialize game state manager."""
    pass

def get_state(self) -> GameStateType:
    """Get current game state."""
    pass

def set_state(self, new_state: GameStateType) -> bool:
    """
    Transition to new state.
    
    Args:
        new_state: State to transition to
        
    Returns:
        True if transition successful
    """
    pass

def can_transition_to(self, new_state: GameStateType) -> bool:
    """
    Check if transition to state is valid.
    
    Args:
        new_state: Proposed new state
        
    Returns:
        True if transition is valid
    """
    pass

def transition_to(self, new_state: GameStateType) -> None:
    """
    Perform state transition with validation.
    
    Args:
        new_state: State to transition to
    """
    pass

def register_state_callback(
    self,
    state: GameStateType,
    callback: Callable[[], None]
) -> None:
    """
    Register callback for state change.
    
    Args:
        state: State to listen for
        callback: Function to call on state change
    """
    pass

def _execute_state_callbacks(self, state: GameStateType) -> None:
    """Execute all callbacks for a state."""
    pass

def is_playing(self) -> bool:
    """Check if game is in playing state."""
    pass

def is_paused(self) -> bool:
    """Check if game is paused."""
    pass

def is_game_over(self) -> bool:
    """Check if game is over."""
    pass

def get_state_history(self) -> list[GameStateType]:
    """Get history of state transitions."""
    pass

def get_play_time(self) -> float:
    """Get total play time in seconds."""
    pass

def reset(self) -> None:
    """Reset state manager to initial state."""
    pass

def _validate_transition(
    self,
    from_state: GameStateType,
    to_state: GameStateType
) -> bool:
    """
    Validate state transition.
    
    Args:
        from_state: Current state
        to_state: Proposed new state
        
    Returns:
        True if valid
    """
    pass
```

#### 3. Interfaces

**Public API**:
- `get_state()` - Get current state
- `set_state()` - Change state
- `can_transition_to()` - Validate transition
- `register_state_callback()` - Subscribe to state changes
- `is_playing()` / `is_paused()` / `is_game_over()` - State checks

**Events/Callbacks**:
- `on_state_change(GameStateType)` - Called on any state change
- `on_game_start()` - Called when game starts
- `on_game_over()` - Called when game ends
- `on_pause()` / `on_resume()` - Called on pause/resume

#### 4. Dependencies

```python
# External imports
from enum import Enum
from typing import Callable, Optional, List
import time
```

---

## Module: Configuration

**File**: `snake/config/config.py`

### 1. Module Overview
The Configuration module manages all game settings, constants, and configurable parameters.

**Key Functionalities**:
- Game constants
- Configurable settings
- Configuration persistence
- Validation

### 2. Classes and Functions

##### Class: Config
**Purpose**: Central configuration manager for the game.

**Attributes**:
- `board_width: int` - Game board width
- `board_height: int` - Game board height
- `initial_speed: float` - Initial game speed (seconds per tick)
- `speed_decrease_per_level: float` - Speed increase per level
- `min_speed: float` - Minimum tick interval
- `initial_snake_length: int` - Starting snake length
- `points_per_food: int` - Points for normal food
- `wrap_walls: bool` - Whether walls wrap around
- `show_fps: bool` - Whether to display FPS
- `color_enabled: bool` - Whether colors are enabled
- `sound_enabled: bool` - Whether sound is enabled
- `config_file: str` - Path to config file

**Methods**:
```python
def __init__(self, config_file: str = "config.json") -> None:
    """
    Initialize configuration with defaults.
    
    Args:
        config_file: Path to configuration file
    """
    pass

def load(self) -> bool:
    """
    Load configuration from file.
    
    Returns:
        True if loaded successfully
    """
    pass

def save(self) -> bool:
    """
    Save configuration to file.
    
    Returns:
        True if saved successfully
    """
    pass

def reset_to_defaults(self) -> None:
    """Reset all settings to default values."""
    pass

def validate(self) -> list[str]:
    """
    Validate configuration values.
    
    Returns:
        List of validation error messages
    """
    pass

def get_board_size(self) -> tuple[int, int]:
    """Get board dimensions."""
    pass

def set_board_size(self, width: int, height: int) -> None:
    """
    Set board dimensions.
    
    Args:
        width: New width
        height: New height
    """
    pass

def get_initial_speed(self) -> float:
    """Get initial game speed."""
    pass

def set_initial_speed(self, speed: float) -> None:
    """
    Set initial game speed.
    
    Args:
        speed: Speed in seconds per tick
    """
    pass

def toggle_colors(self) -> bool:
    """Toggle color display."""
    pass

def toggle_sound(self) -> bool:
    """Toggle sound effects."""
    pass

def get_level_speed(self, level: int) -> float:
    """
    Calculate speed for a given level.
    
    Args:
        level: Level number
        
    Returns:
        Tick interval for level
    """
    pass
```

#### Constants

```python
# Game Constants
DEFAULT_BOARD_WIDTH = 20
DEFAULT_BOARD_HEIGHT = 15
DEFAULT_INITIAL_SPEED = 0.2  # 5 ticks per second
DEFAULT_INITIAL_SNAKE_LENGTH = 3
DEFAULT_POINTS_PER_FOOD = 10
DEFAULT_SPEED_DECREASE = 0.02  # Faster per level
DEFAULT_MIN_SPEED = 0.05  # Maximum speed

# Game Over Messages
GAME_OVER_MESSAGE = "GAME OVER"
PAUSE_MESSAGE = "PAUSED"
PRESS_START_MESSAGE = "Press SPACE to Start"
PRESS_RESTART_MESSAGE = "Press R to Restart"
```

#### 3. Interfaces

**Public API**:
- `load()` - Load config from file
- `save()` - Save config to file
- `reset_to_defaults()` - Reset to defaults
- `validate()` - Validate settings
- `get_board_size()` / `set_board_size()` - Board configuration
- `toggle_colors()` / `toggle_sound()` - Toggle options

#### 4. Dependencies

```python
# External imports
from typing import Optional
import json
from pathlib import Path
from dataclasses import dataclass, field
```

---

## Module: Main Module

**File**: `snake/main.py`

### 1. Module Overview
The Main module is the entry point for the Snake game application. It orchestrates the initialization and execution of all game components.

**Key Functionalities**:
- Application entry point
- Component initialization
- Game loop execution
- Graceful shutdown

### 2. Classes and Functions

##### Class: SnakeGame
**Purpose**: Main game application class that coordinates all components.

**Attributes**:
- `config: Config` - Game configuration
- `game_engine: GameEngine` - Game engine instance
- `running: bool` - Application running flag
- `exit_code: int` - Exit code for shutdown

**Methods**:
```python
def __init__(self) -> None:
    """Initialize Snake game application."""
    pass

def run(self) -> int:
    """
    Main application entry point.
    
    Returns:
        Exit code (0 for success)
    """
    pass

def _initialize(self) -> bool:
    """
    Initialize all game components.
    
    Returns:
        True if initialization successful
    """
    pass

def _setup(self) -> None:
    """Set up game after initialization."""
    pass

def _cleanup(self) -> None:
    """Clean up resources on shutdown."""
    pass

def _handle_exceptions(self) -> None:
    """Set up exception handling."""
    pass

def _signal_handler(self, signum: int, frame: any) -> None:
    """
    Handle system signals.
    
    Args:
        signum: Signal number
        frame: Current stack frame
    """
    pass
```

##### Module Functions

```python
def main() -> int:
    """
    Main entry point for the Snake game.
    
    Returns:
        Exit code
    """
    pass

def print_title() -> None:
    """Print game title and version."""
    pass

def print_usage() -> None:
    """Print command line usage information."""
    pass

def parse_command_line_args() -> dict:
    """
    Parse command line arguments.
    
    Returns:
        Dictionary of parsed arguments
    """
    pass
```

#### 3. Interfaces

**Public API**:
- `main()` - Entry point function
- `SnakeGame.run()` - Run game application

#### 4. Dependencies

```python
# Internal imports
from snake.engine.game_engine import GameEngine
from snake.config.config import Config

# External imports
import sys
import signal
import argparse
from typing import Optional
```

---

## Data Flow Between Modules

### Game Initialization Flow

```
┌─────────────┐
│    main.py  │
│             │
│  SnakeGame  │
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Config    │
│             │
│  load()     │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Component Initialization                  │
├────────┬─────────┬─────────┬──────────┬─────────┬──────────┤
│ Snake  │  Food   │Collision│  Input   │ Display │ ScoreMgr │
└───┬────┴───┬─────┴───┬─────┴───┬──────┴───┬─────┴───┬──────┘
    │        │         │         │          │         │
    └────────┴─────────┴─────────┴──────────┴─────────┴─────┐
                                                           │
                                                           ▼
                                              ┌──────────────────┐
                                              │   GameEngine     │
                                              │                  │
                                              │  Coordinates all │
                                              │    components    │
                                              └────────┬─────────┘
                                                       │
                                                       ▼
                                              ┌──────────────────┐
                                              │   GameState      │
                                              │                  │
                                              │  INITIALIZED →   │
                                              │     READY →      │
                                              │     PLAYING      │
                                              └──────────────────┘
```

### Game Tick Flow

```
                    ┌──────────────────┐
                    │   GameEngine     │
                    │   _game_tick()   │
                    └────────┬─────────┘
                             │
         ┌───────────────────┼───────────────────┐
         │                   │                   │
         ▼                   ▼                   ▼
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ InputHandler │    │    Snake     │    │  Collision   │
│ get_input()  │    │   move()     │    │  check_all() │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       │                   │                   │
       │         ┌─────────┴─────────┐         │
       │         │                   │         │
       ▼         ▼                   ▼         ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ Direction    │ │  New Head    │ │ Food Hit?    │
│ Updated      │ │  Position    │ │ Wall Hit?    │
└──────────────┘ └──────────────┘ │ Self Hit?    │
                                  └──────┬───────┘
                                         │
                         ┌───────────────┼───────────────┐
                         │               │               │
                         ▼               ▼               ▼
                  ┌──────────┐    ┌──────────┐    ┌──────────┐
                  │ Food     │    │ Score    │    │ Game     │
                  │ spawn()  │    │ add()    │    │ Over?    │
                  └────┬─────┘    └────┬─────┘    └────┬─────┘
                       │               │               │
                       └───────────────┴───────────────┘
                                   │
                                   ▼
                          ┌──────────────────┐
                          │    Display       │
                          │    render()      │
                          └──────────────────┘
```

### State Transition Diagram

```
                    ┌──────────────┐
                    │ INITIALIZED  │
                    └──────┬───────┘
                           │ start
                           ▼
                    ┌──────────────┐
                    │     READY    │──────────────┐
                    └──────┬───────┘              │
                           │ start game           │
                           ▼                      │
                    ┌──────────────┐              │
                    │   PLAYING    │◄─────────────┘
                    └──────┬───────┘     resume
         ┌────────────────┼────────────────┐
         │                │                │
         │ pause          │ game over      │
         ▼                ▼                ▼
┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│   PAUSED     │  │  GAME_OVER   │  │ LEVEL_TRANS  │
└──────────────┘  └──────────────┘  └──────────────┘
       │                   │
       │ restart           │ restart
       └───────────────────┘
               │
               ▼
         ┌──────────────┐
         │     READY    │
         └──────────────┘
```

---

## Summary

This Detailed Design Document covers all modules in the Snake game architecture:

| Module | File | Primary Responsibility |
|--------|------|----------------------|
| GameEngine | `snake/engine/game_engine.py` | Central coordinator, game loop |
| Snake | `snake/models/snake.py` | Snake entity and movement |
| Food | `snake/models/food.py` | Food spawning and types |
| CollisionDetector | `snake/core/collision.py` | All collision detection |
| InputHandler | `snake/io/input_handler.py` | User input processing |
| Display | `snake/io/display.py` | Game rendering |
| ScoreManager | `snake/core/score_manager.py` | Scoring and high scores |
| GameState | `snake/core/game_state.py` | State machine |
| Config | `snake/config/config.py` | Configuration management |
| Main | `snake/main.py` | Entry point and orchestration |

Each module is designed with clear interfaces, minimal dependencies, and follows single responsibility principles for maintainability and testability.