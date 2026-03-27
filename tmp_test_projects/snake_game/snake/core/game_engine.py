"""
Game Engine Module

The Game Engine is the central orchestrator of the Snake game. It manages the game loop,
coordinates all subsystems, handles game states, and manages the overall game flow.

This module implements the GameEngine class which serves as the main entry point
for the game logic.
"""

from __future__ import annotations

import logging
from enum import Enum, auto
from typing import Callable, Optional, TYPE_CHECKING
from dataclasses import dataclass, field

if TYPE_CHECKING:
    from .snake_controller import SnakeController
    from .food_manager import FoodManager
    from .collision_detector import CollisionDetector
    from ..rendering.display import Display

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class GameState(Enum):
    """Enum representing the possible states of the game."""
    MENU = auto()      # Main menu state
    PLAYING = auto()   # Active gameplay
    PAUSED = auto()    # Game paused
    GAME_OVER = auto() # Game ended due to collision
    VICTORY = auto()   # Game won (if applicable)


class GameEvent(Enum):
    """Enum representing game events that can be triggered."""
    GAME_STARTED = auto()
    GAME_PAUSED = auto()
    GAME_RESUMED = auto()
    GAME_ENDED = auto()
    FOOD_EATEN = auto()
    SCORE_CHANGED = auto()
    HIGH_SCORE_BEATEN = auto()
    LEVEL_CHANGED = auto()


@dataclass
class GameConfig:
    """Configuration settings for the game."""
    width: int = 20
    height: int = 10
    initial_snake_length: int = 3
    initial_speed: float = 1.0  # Seconds per move (lower = faster)
    speed_increase_per_food: float = 0.01  # Speed increase per food eaten
    min_speed: float = 0.1  # Minimum speed (maximum game speed)
    wall_collision_enabled: bool = True  # If False, snake wraps around
    self_collision_enabled: bool = True
    max_snake_length: Optional[int] = None  # If set, game ends when reached
    score_per_food: int = 10
    enable_high_score: bool = True
    high_score_file: str = "high_score.txt"
    
    def validate(self) -> None:
        """Validate configuration values."""
        if self.width < 10:
            raise ValueError("Width must be at least 10")
        if self.height < 5:
            raise ValueError("Height must be at least 5")
        if self.initial_snake_length < 1:
            raise ValueError("Initial snake length must be at least 1")
        if self.initial_speed <= 0:
            raise ValueError("Initial speed must be positive")
        if self.speed_increase_per_food < 0:
            raise ValueError("Speed increase must be non-negative")
        if self.min_speed <= 0 or self.min_speed >= self.initial_speed:
            raise ValueError("Min speed must be positive and less than initial speed")
        if self.max_snake_length and self.max_snake_length < self.initial_snake_length:
            raise ValueError("Max length must be greater than initial length")
        if self.score_per_food < 0:
            raise ValueError("Score per food must be non-negative")


@dataclass
class GameStats:
    """Statistics tracked during gameplay."""
    score: int = 0
    high_score: int = 0
    games_played: int = 0
    games_won: int = 0
    foods_eaten: int = 0
    total_play_time: float = 0.0


class GameEngine:
    """
    The central game engine that orchestrates all game subsystems.
    
    Responsibilities:
    - Manage game state transitions
    - Run the game loop
    - Coordinate between subsystems (snake, food, collision)
    - Handle scoring and game statistics
    - Manage game configuration
    - Provide hooks for rendering and input
    
    Example:
        engine = GameEngine(config=GameConfig())
        engine.setup(snake_controller, food_manager, collision_detector, display)
        engine.start()
        while engine.is_running:
            engine.update(delta_time)
            engine.render()
    """
    
    def __init__(self, config: Optional[GameConfig] = None) -> None:
        """
        Initialize the game engine with optional configuration.
        
        Args:
            config: Game configuration settings. Uses defaults if not provided.
        """
        self._config = config or GameConfig()
        self._config.validate()
        
        # Game state
        self._state: GameState = GameState.MENU
        self._is_running: bool = False
        self._is_paused: bool = False
        
        # Subsystems (set via setup method)
        self._snake_controller: Optional[SnakeController] = None
        self._food_manager: Optional[FoodManager] = None
        self._collision_detector: Optional[CollisionDetector] = None
        self._display: Optional[Display] = None
        
        # Game data
        self._stats = GameStats()
        self._current_speed: float = self._config.initial_speed
        self._moves_since_last_update: float = 0.0
        
        # Event handlers
        self._event_handlers: dict[GameEvent, list[Callable]] = {
            event: [] for event in GameEvent
        }
        
        logger.info("GameEngine initialized with config: %s", self._config)
    
    # Properties
    @property
    def state(self) -> GameState:
        """Current game state."""
        return self._state
    
    @property
    def is_running(self) -> bool:
        """Whether the game loop is running."""
        return self._is_running
    
    @property
    def is_paused(self) -> bool:
        """Whether the game is currently paused."""
        return self._is_paused
    
    @property
    def config(self) -> GameConfig:
        """Game configuration (read-only)."""
        return self._config
    
    @property
    def stats(self) -> GameStats:
        """Current game statistics (read-only)."""
        return self._stats
    
    @property
    def current_speed(self) -> float:
        """Current game speed (seconds per move)."""
        return self._current_speed
    
    @property
    def snake_controller(self) -> SnakeController:
        """The snake controller subsystem."""
        if self._snake_controller is None:
            raise RuntimeError("SnakeController not initialized. Call setup() first.")
        return self._snake_controller
    
    @property
    def food_manager(self) -> FoodManager:
        """The food manager subsystem."""
        if self._food_manager is None:
            raise RuntimeError("FoodManager not initialized. Call setup() first.")
        return self._food_manager
    
    @property
    def collision_detector(self) -> CollisionDetector:
        """The collision detector subsystem."""
        if self._collision_detector is None:
            raise RuntimeError("CollisionDetector not initialized. Call setup() first.")
        return self._collision_detector
    
    @property
    def display(self) -> Display:
        """The display subsystem."""
        if self._display is None:
            raise RuntimeError("Display not initialized. Call setup() first.")
        return self._display
    
    def setup(
        self,
        snake_controller: SnakeController,
        food_manager: FoodManager,
        collision_detector: CollisionDetector,
        display: Optional[Display] = None
    ) -> None:
        """
        Set up all game subsystems.
        
        Args:
            snake_controller: The snake controller instance.
            food_manager: The food manager instance.
            collision_detector: The collision detector instance.
            display: Optional display instance for rendering.
        """
        self._snake_controller = snake_controller
        self._food_manager = food_manager
        self._collision_detector = collision_detector
        self._display = display
        
        # Initialize collision detector with references
        self._collision_detector.set_game_bounds(self._config.width, self._config.height)
        
        logger.info("GameEngine setup complete")
    
    def on(self, event: GameEvent, handler: Callable) -> None:
        """
        Register an event handler.
        
        Args:
            event: The event to listen for.
            handler: The callback function to invoke.
        """
        self._event_handlers[event].append(handler)
        logger.debug("Registered handler for event: %s", event)
    
    def off(self, event: GameEvent, handler: Callable) -> None:
        """
        Remove an event handler.
        
        Args:
            event: The event to stop listening for.
            handler: The callback function to remove.
        """
        if handler in self._event_handlers[event]:
            self._event_handlers[event].remove(handler)
            logger.debug("Removed handler for event: %s", event)
    
    def _emit(self, event: GameEvent, *args, **kwargs) -> None:
        """
        Emit an event to all registered handlers.
        
        Args:
            event: The event to emit.
            *args, **kwargs: Arguments to pass to handlers.
        """
        for handler in self._event_handlers[event]:
            try:
                handler(*args, **kwargs)
            except Exception as e:
                logger.error("Error in event handler for %s: %s", event, e)
    
    def start(self) -> None:
        """
        Start the game from the menu state.
        
        Transitions to PLAYING state and initializes game entities.
        """
        if self._state != GameState.MENU and self._state != GameState.GAME_OVER:
            logger.warning("Start called from unexpected state: %s", self._state)
        
        self._reset_game()
        self._state = GameState.PLAYING
        self._is_running = True
        self._is_paused = False
        
        # Initialize subsystems
        self._snake_controller.reset(
            self._config.width,
            self._config.height,
            self._config.initial_snake_length
        )
        self._food_manager.spawn_food()
        
        # Reset game data
        self._stats = GameStats(high_score=self._stats.high_score)
        self._current_speed = self._config.initial_speed
        self._moves_since_last_update = 0.0
        
        self._emit(GameEvent.GAME_STARTED)
        logger.info("Game started")
    
    def pause(self) -> None:
        """Pause the game if currently playing."""
        if self._state == GameState.PLAYING:
            self._state = GameState.PAUSED
            self._is_paused = True
            self._emit(GameEvent.GAME_PAUSED)
            logger.info("Game paused")
    
    def resume(self) -> None:
        """Resume the game if currently paused."""
        if self._state == GameState.PAUSED:
            self._state = GameState.PLAYING
            self._is_paused = False
            self._emit(GameEvent.GAME_RESUMED)
            logger.info("Game resumed")
    
    def toggle_pause(self) -> None:
        """Toggle between paused and playing states."""
        if self._state == GameState.PLAYING:
            self.pause()
        elif self._state == GameState.PAUSED:
            self.resume()
    
    def end_game(self, victory: bool = False) -> None:
        """
        End the current game.
        
        Args:
            victory: Whether the game ended in victory.
        """
        self._state = GameState.VICTORY if victory else GameState.GAME_OVER
        self._is_running = False
        
        # Update high score if applicable
        if self._config.enable_high_score and self._stats.score > self._stats.high_score:
            self._stats.high_score = self._stats.score
            self._emit(GameEvent.HIGH_SCORE_BEATEN, self._stats.score)
        
        # Update game statistics
        self._stats.games_played += 1
        if victory:
            self._stats.games_won += 1
        
        self._emit(GameEvent.GAME_ENDED, victory=victory, score=self._stats.score)
        logger.info("Game ended - Victory: %s, Score: %s", victory, self._stats.score)
    
    def restart(self) -> None:
        """Restart the game from the beginning."""
        self._state = GameState.MENU
        self.start()
    
    def _reset_game(self) -> None:
        """Reset game state to initial values."""
        self._stats = GameStats(high_score=self._stats.high_score)
        self._current_speed = self._config.initial_speed
        self._moves_since_last_update = 0.0
    
    def update(self, delta_time: float) -> None:
        """
        Update game state for one frame.
        
        Args:
            delta_time: Time elapsed since last update in seconds.
        """
        if self._state != GameState.PLAYING or self._is_paused:
            return
        
        # Accumulate time for snake movement
        self._moves_since_last_update += delta_time
        
        # Check if it's time to move the snake
        while self._moves_since_last_update >= self._current_speed:
            self._moves_since_last_update -= self._current_speed
            self._update_game_logic()
    
    def _update_game_logic(self) -> None:
        """Execute one game tick (snake movement and collision detection)."""
        # Move the snake
        self._snake_controller.move()
        
        # Get snake head position for collision detection
        head_position = self._snake_controller.head_position
        
        # Check for wall collision
        if self._config.wall_collision_enabled:
            wall_collision = self._collision_detector.check_wall_collision(
                head_position, self._config.width, self._config.height
            )
            if wall_collision:
                self.end_game(victory=False)
                return
        
        # Check for self collision
        if self._config.self_collision_enabled:
            self_collision = self._collision_detector.check_self_collision(
                self._snake_controller.body_positions
            )
            if self_collision:
                self.end_game(victory=False)
                return
        
        # Check for food collision
        food_position = self._food_manager.food_position
        if self._collision_detector.check_food_collision(head_position, food_position):
            self._handle_food_eaten(food_position)
        
        # Check for victory condition
        if self._config.max_snake_length:
            if self._snake_controller.length >= self._config.max_snake_length:
                self.end_game(victory=True)
                return
    
    def _handle_food_eaten(self, food_position) -> None:
        """
        Handle the snake eating food.
        
        Args:
            food_position: Position of the eaten food.
        """
        # Grow the snake
        self._snake_controller.grow()
        
        # Update score
        old_score = self._stats.score
        self._stats.score += self._config.score_per_food
        self._stats.foods_eaten += 1
        
        # Increase speed
        self._current_speed = max(
            self._config.min_speed,
            self._current_speed - self._config.speed_increase_per_food
        )
        
        # Spawn new food
        self._food_manager.spawn_food()
        
        # Emit events
        self._emit(GameEvent.FOOD_EATEN, position=food_position)
        self._emit(GameEvent.SCORE_CHANGED, old_score=old_score, new_score=self._stats.score)
        
        logger.debug("Food eaten at %s, new score: %s", food_position, self._stats.score)
    
    def get_game_data(self) -> dict:
        """
        Get current game data for rendering.
        
        Returns:
            Dictionary containing all game state data needed for rendering.
        """
        return {
            "state": self._state,
            "snake": self._snake_controller.body_positions if self._snake_controller else [],
            "snake_head": self._snake_controller.head_position if self._snake_controller else None,
            "food": self._food_manager.food_position if self._food_manager else None,
            "score": self._stats.score,
            "high_score": self._stats.high_score,
            "width": self._config.width,
            "height": self._config.height,
            "speed": self._current_speed,
        }
    
    def render(self) -> None:
        """Render the current game state."""
        if self._display:
            game_data = self.get_game_data()
            self._display.render(game_data)
    
    def process_input(self, key: str) -> None:
        """
        Process input key press.
        
        Args:
            key: The key that was pressed.
        """
        if key == "q":
            self._is_running = False
            logger.info("Game quit requested")
            return
        
        if key == "p":
            self.toggle_pause()
            return
        
        if key == "r" and self._state in (GameState.GAME_OVER, GameState.VICTORY):
            self.restart()
            return
        
        if key == "Enter" and self._state == GameState.MENU:
            self.start()
            return
        
        if self._state == GameState.PLAYING and not self._is_paused:
            self._snake_controller.handle_input(key)
    
    def save_high_score(self) -> None:
        """Save the high score to file."""
        if not self._config.enable_high_score:
            return
        
        try:
            with open(self._config.high_score_file, "w") as f:
                f.write(str(self._stats.high_score))
            logger.info("High score saved: %s", self._stats.high_score)
        except IOError as e:
            logger.error("Failed to save high score: %s", e)
    
    def load_high_score(self) -> None:
        """Load the high score from file."""
        if not self._config.enable_high_score:
            return
        
        try:
            with open(self._config.high_score_file, "r") as f:
                content = f.read().strip()
                if content:
                    self._stats.high_score = int(content)
            logger.info("High score loaded: %s", self._stats.high_score)
        except (IOError, ValueError) as e:
            logger.warning("Failed to load high score: %s", e)
            self._stats.high_score = 0


if __name__ == "__main__":
    # Example usage and basic test
    print("Testing GameEngine module...")
    
    # Test configuration
    config = GameConfig(
        width=20,
        height=10,
        initial_snake_length=3,
        initial_speed=0.1,
    )
    
    # Create engine
    engine = GameEngine(config=config)
    
    print(f"Engine state: {engine.state}")
    print(f"Config width: {engine.config.width}")
    print(f"Config height: {engine.config.height}")
    
    print("\nGameEngine module loaded successfully!")
