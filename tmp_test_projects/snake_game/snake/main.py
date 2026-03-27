"""
Main Module - Snake Game Orchestrator

This module contains the primary SnakeGame class that coordinates all
subsystems including game logic, input handling, and display rendering.

Classes:
    GameStatus: Enum representing the current game state
    GameResult: Dataclass representing the final game outcome
    SnakeGame: Main game orchestrator class

Example:
    >>> game = SnakeGame(width=40, height=20)
    >>> result = game.run()
    >>> print(f"Final Score: {result.score}")
"""

import os
import sys
import time
import signal
import logging
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Tuple, List, Any

# Import game subsystem
from .game import Snake, Food, GameState, Direction, Position
from .input import InputHandler, KeyAction
from .display import Renderer, TerminalUtils
from .config import GameConfig

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class GameStatus(Enum):
    """
    Enum representing the current state of the game.

    Members:
        MENU: Game is displaying the main menu
        PLAYING: Game is actively running
        PAUSED: Game is paused
        GAME_OVER: Game has ended due to collision
        WON: Game has ended due to completing all food
        EXITING: Game is shutting down
    """
    MENU = "menu"
    PLAYING = "playing"
    PAUSED = "paused"
    GAME_OVER = "game_over"
    WON = "won"
    EXITING = "exiting"


@dataclass
class GameResult:
    """
    Dataclass representing the final result of a completed game.

    Attributes:
        status: Final game status (WON or GAME_OVER)
        score: Final score achieved
        length: Final length of the snake
        time_played: Total time played in seconds
        high_score: Current high score
    """
    status: GameStatus
    score: int
    length: int
    time_played: float
    high_score: int

    def __str__(self) -> str:
        """Return a string representation of the game result."""
        status_text = self.status.value.replace("_", " ").title()
        return (
            f"Game Result - {status_text}\n"
            f"  Score: {self.score}\n"
            f"  Snake Length: {self.length}\n"
            f"  Time Played: {self.time_played:.1f}s\n"
            f"  High Score: {self.high_score}"
        )


class SnakeGame:
    """
    Main orchestrator for the Snake game.

    This class coordinates all game subsystems including:
    - Game state management (snake, food, score)
    - Input handling (keyboard controls)
    - Display rendering (terminal output)
    - Game loop (update and render cycles)

    The game follows this lifecycle:
    1. Initialize: Set up all subsystems
    2. Menu: Display main menu and wait for input
    3. Play: Run game loop until game over or win
    4. Result: Display final score and options

    Example:
        >>> game = SnakeGame(width=40, height=20, speed=150)
        >>> result = game.run()
        >>> print(f"Score: {result.score}")

    Args:
        width: Game board width in characters (default: 40)
        height: Game board height in characters (default: 20)
        speed: Game speed in milliseconds (default: 150)
        config: Optional custom GameConfig instance

    Attributes:
        config: Game configuration settings
        state: Current game state manager
        snake: Snake entity
        food: Food entity
        input_handler: Input handler instance
        renderer: Display renderer instance
        status: Current game status
        start_time: Timestamp when game started
        high_score: Current high score
    """

    def __init__(
        self,
        width: int = 40,
        height: int = 20,
        speed: int = 150,
        config: Optional[GameConfig] = None
    ) -> None:
        """
        Initialize the Snake game with all subsystems.

        Args:
            width: Game board width in characters
            height: Game board height in characters
            speed: Game speed in milliseconds per frame
            config: Optional custom configuration
        """
        # Validate parameters
        if width < 20:
            raise ValueError(f"Width must be at least 20, got {width}")
        if height < 10:
            raise ValueError(f"Height must be at least 10, got {height}")
        if speed < 50:
            raise ValueError(f"Speed must be at least 50ms, got {speed}")

        # Store parameters
        self.width = width
        self.height = height
        self.speed = speed

        # Use provided config or create default
        self.config = config or GameConfig(width=width, height=height, speed=speed)

        # Initialize subsystems
        self.state: GameState = GameState()
        self.snake: Snake = Snake(
            initial_position=self._calculate_start_position(),
            initial_direction=Direction.RIGHT,
            max_width=self.config.width,
            max_height=self.config.height
        )
        self.food: Food = Food(
            max_width=self.config.width,
            max_height=self.config.height
        )
        self.input_handler: InputHandler = InputHandler()
        self.renderer: Renderer = Renderer(self.config)

        # Game tracking
        self.status: GameStatus = GameStatus.MENU
        self.start_time: float = 0.0
        self.high_score: int = 0
        self.last_frame_time: float = 0.0

        # Setup signal handlers for clean shutdown
        self._setup_signal_handlers()

        logger.info("SnakeGame initialized with size %dx%d", width, height)

    def _calculate_start_position(self) -> Position:
        """
        Calculate the starting position for the snake.

        The snake starts in the center of the board, slightly offset to the left
        to provide room for initial movement.

        Returns:
            Position tuple (x, y) for the snake's head
        """
        start_x = self.config.width // 4
        start_y = self.config.height // 2
        return Position(start_x, start_y)

    def _setup_signal_handlers(self) -> None:
        """
        Setup signal handlers for graceful shutdown.

        Handles SIGINT (Ctrl+C) and SIGTERM to ensure clean exit
        and terminal restoration.
        """
        def signal_handler(signum: int, frame: Any) -> None:
            logger.info("Received signal %d, shutting down...", signum)
            self.status = GameStatus.EXITING
            self._cleanup()

        try:
            signal.signal(signal.SIGINT, signal_handler)
            signal.signal(signal.SIGTERM, signal_handler)
        except (OSError, ValueError):
            # Signal handling may not be available on all platforms
            logger.debug("Signal handlers not available on this platform")

    def run(self) -> GameResult:
        """
        Run the main game loop.

        This is the primary entry point for running the game. It:
        1. Shows the main menu
        2. Waits for player to start
        3. Runs the game loop
        4. Displays results
        5. Returns the game result

        Returns:
            GameResult containing final score, status, and statistics
        """
        try:
            # Initialize terminal
            self._init_terminal()

            # Show main menu
            self._show_menu()

            # Check if user chose to exit
            if self.status == GameStatus.EXITING:
                return GameResult(
                    status=GameStatus.EXITING,
                    score=0,
                    length=0,
                    time_played=0.0,
                    high_score=self.high_score
                )

            # Start the game
            self._start_game()

            # Run game loop
            self._game_loop()

            # Calculate final result
            result = self._calculate_result()

            # Show results
            self._show_results(result)

            return result

        except KeyboardInterrupt:
            logger.info("Game interrupted by user")
            return GameResult(
                status=GameStatus.EXITING,
                score=self.state.score,
                length=len(self.snake),
                time_played=self._get_elapsed_time(),
                high_score=max(self.state.score, self.high_score)
            )

        finally:
            # Always cleanup
            self._cleanup()

    def _init_terminal(self) -> None:
        """
        Initialize the terminal for raw input mode.

        Sets up the terminal for:
        - Raw input mode (no echo, line buffering)
        - Hidden cursor
        - Fullscreen mode if possible
        """
        TerminalUtils.init_raw_mode()
        TerminalUtils.hide_cursor()
        logger.debug("Terminal initialized")

    def _cleanup(self) -> None:
        """
        Cleanup terminal and restore normal operation.

        Restores:
        - Normal terminal mode
        - Visible cursor
        - Clear screen
        """
        try:
            TerminalUtils.clear_screen()
            TerminalUtils.show_cursor()
            TerminalUtils.exit_raw_mode()
            logger.debug("Terminal cleanup complete")
        except Exception as e:
            logger.warning("Cleanup error: %s", e)

    def _show_menu(self) -> None:
        """
        Display the main menu and wait for input.

        Shows:
        - Game title
        - Instructions
        - Controls
        - Menu options (Start, Settings, Exit)
        """
        self.renderer.clear_screen()
        self.renderer.draw_box(self.width, self.height, "MAIN MENU")

        # Calculate centered positions
        title_x = (self.width - 20) // 2
        title_y = 2

        # Draw title
        self.renderer.draw_text(title_x, title_y, "  _____  _  _ ")
        self.renderer.draw_text(title_x, title_y + 1, " |  __ \\| \\| |")
        self.renderer.draw_text(title_x, title_y + 2, " | |  \\/ .` |")
        self.renderer.draw_text(title_x, title_y + 3, " | |__ / /\\| |")
        self.renderer.draw_text(title_x, title_y + 4, " |____/_/ \\_\\")

        # Draw instructions
        instructions = [
            "",
            "  Use Arrow Keys to move",
            "  Eat food to grow and score points",
            "  Avoid walls and your own tail!",
            "",
            "  Controls:",
            "  [W/↑] Move Up     [S/↓] Move Down",
            "  [A/←] Move Left   [D/→] Move Right",
            "  [P]   Pause       [Q]   Quit",
            "",
            f"  High Score: {self.high_score}",
            "",
            "  Press [ENTER] to Start",
            "  Press [Q] to Quit"
        ]

        for i, line in enumerate(instructions):
            x = (self.width - len(line)) // 2
            y = title_y + 6 + i
            self.renderer.draw_text(x, y, line)

        self.renderer.refresh()

        # Wait for input
        while True:
            key_action = self.input_handler.get_key_action()

            if key_action == KeyAction.QUIT:
                self.status = GameStatus.EXITING
                return
            elif key_action == KeyAction.START:
                return
            elif key_action in (KeyAction.UP, KeyAction.DOWN, KeyAction.LEFT, KeyAction.RIGHT):
                # Allow practice movements in menu
                pass

    def _start_game(self) -> None:
        """
        Initialize the game for a new play session.

        Resets:
        - Snake to initial position
        - Food to random location
        - Score to zero
        - Game status to PLAYING
        """
        # Reset game state
        self.snake.reset(self._calculate_start_position(), Direction.RIGHT)
        self.food.spawn(self.snake)
        self.state.reset()

        # Set game status
        self.status = GameStatus.PLAYING
        self.start_time = time.time()

        logger.info("Game started")

    def _game_loop(self) -> None:
        """
        Main game loop - runs until game over or exit.

        Each frame:
        1. Handle input
        2. Update game state
        3. Check collisions
        4. Render display
        5. Control frame rate
        """
        logger.info("Game loop started")

        while self.status == GameStatus.PLAYING:
            # Calculate frame timing
            current_time = time.time()
            frame_delay = self.config.speed / 1000.0

            # Handle input
            self._handle_input()

            # Check for game over conditions
            if not self._check_collisions():
                break

            # Update game state
            self._update_game_state()

            # Render
            self._render()

            # Frame rate control
            elapsed = time.time() - current_time
            if elapsed < frame_delay:
                time.sleep(frame_delay - elapsed)

        logger.info("Game loop ended")

    def _handle_input(self) -> None:
        """
        Process keyboard input for game control.

        Handles:
        - Direction changes (arrow keys, WASD)
        - Pause/Resume (P key)
        - Quit (Q key)
        - Speed adjustment (plus/minus)
        """
        key_action = self.input_handler.get_key_action()

        if key_action == KeyAction.UP:
            if self.snake.direction != Direction.DOWN:
                self.snake.set_direction(Direction.UP)
        elif key_action == KeyAction.DOWN:
            if self.snake.direction != Direction.UP:
                self.snake.set_direction(Direction.DOWN)
        elif key_action == KeyAction.LEFT:
            if self.snake.direction != Direction.RIGHT:
                self.snake.set_direction(Direction.LEFT)
        elif key_action == KeyAction.RIGHT:
            if self.snake.direction != Direction.LEFT:
                self.snake.set_direction(Direction.RIGHT)
        elif key_action == KeyAction.PAUSE:
            self._toggle_pause()
        elif key_action == KeyAction.QUIT:
            self.status = GameStatus.EXITING

    def _toggle_pause(self) -> None:
        """
        Toggle between PLAYING and PAUSED states.

        When pausing:
        - Display pause overlay
        - Wait for unpause or quit
        """
        if self.status == GameStatus.PLAYING:
            self.status = GameStatus.PAUSED
            self._show_pause_screen()
        elif self.status == GameStatus.PAUSED:
            self.status = GameStatus.PLAYING

    def _show_pause_screen(self) -> None:
        """
        Display the pause overlay screen.

        Shows:
        - "PAUSED" message
        - Resume instructions
        - Quit option
        """
        self.renderer.draw_pause_overlay(self.width, self.height)
        self.renderer.refresh()

        # Wait for unpause or quit
        while self.status == GameStatus.PAUSED:
            key_action = self.input_handler.get_key_action()

            if key_action == KeyAction.PAUSE:
                self.status = GameStatus.PLAYING
            elif key_action == KeyAction.QUIT:
                self.status = GameStatus.EXITING
                return

    def _update_game_state(self) -> None:
        """
        Update all game entities for the current frame.

        Updates:
        - Snake position
        - Food consumption
        - Score calculation
        - Win condition check
        """
        # Move the snake
        self.snake.move()

        # Check if snake ate food
        if self.snake.head == self.food.position:
            # Grow the snake
            self.snake.grow()

            # Update score
            self.state.score += self.config.food_points

            # Spawn new food
            self.food.spawn(self.snake)

            # Check win condition (if all food eaten)
            if self.state.food_eaten >= self.config.max_food:
                self.status = GameStatus.WON

    def _check_collisions(self) -> bool:
        """
        Check for collision conditions that end the game.

        Checks:
        - Wall collision (snake hits boundary)
        - Self collision (snake hits its own body)

        Returns:
            True if no collision, False if collision occurred
        """
        head = self.snake.head

        # Check wall collision
        if (head.x < 0 or head.x >= self.config.width or
            head.y < 0 or head.y >= self.config.height):
            self.status = GameStatus.GAME_OVER
            logger.info("Wall collision detected")
            return False

        # Check self collision (skip head)
        if head in self.snake.body:
            self.status = GameStatus.GAME_OVER
            logger.info("Self collision detected")
            return False

        return True

    def _render(self) -> None:
        """
        Render the current game state to the terminal.

        Draws:
        - Game border
        - Snake body and head
        - Food item
        - Score and game info
        """
        # Clear and draw border
        self.renderer.draw_game_board(self.width, self.height)

        # Draw score header
        self.renderer.draw_score_bar(
            self.width,
            self.state.score,
            len(self.snake),
            self.high_score
        )

        # Draw snake
        for i, segment in enumerate(self.snake):
            if i == 0:
                # Head
                self.renderer.draw_snake_head(segment.x, segment.y, self.snake.direction)
            else:
                # Body
                self.renderer.draw_snake_body(segment.x, segment.y)

        # Draw food
        self.renderer.draw_food(self.food.position.x, self.food.position.y)

        # Refresh display
        self.renderer.refresh()

    def _calculate_result(self) -> GameResult:
        """
        Calculate and return the final game result.

        Updates:
        - High score if beaten
        - Calculates total play time

        Returns:
            GameResult with all final statistics
        """
        elapsed_time = self._get_elapsed_time()

        # Update high score
        if self.state.score > self.high_score:
            self.high_score = self.state.score

        return GameResult(
            status=self.status,
            score=self.state.score,
            length=len(self.snake),
            time_played=elapsed_time,
            high_score=self.high_score
        )

    def _show_results(self, result: GameResult) -> None:
        """
        Display the final game results screen.

        Shows:
        - Game over or win message
        - Final score
        - Snake length
        - Play time
        - Options to play again or quit
        """
        self.renderer.clear_screen()

        # Calculate centered positions
        title_x = (self.width - 25) // 2
        title_y = 3

        # Draw title based on status
        if result.status == GameStatus.WON:
            self.renderer.draw_text(title_x, title_y, "  *** YOU WON! ***  ")
            self.renderer.draw_text(title_x, title_y + 1, "  Congratulations!  ")
        elif result.status == GameStatus.GAME_OVER:
            self.renderer.draw_text(title_x, title_y, "    GAME OVER!     ")
            self.renderer.draw_text(title_x, title_y + 1, "  Better luck next  ")
            self.renderer.draw_text(title_x, title_y + 2, "     time!         ")
        else:
            self.renderer.draw_text(title_x, title_y, "       Game        ")
            self.renderer.draw_text(title_x, title_y + 1, "      Ended        ")

        # Draw results
        results = [
            "",
            f"  Final Score: {result.score}",
            f"  Snake Length: {result.length}",
            f"  Time Played: {result.time_played:.1f}s",
            "",
            f"  High Score: {result.high_score}",
            "",
            "  Press [ENTER] to Play Again",
            "  Press [Q] to Quit"
        ]

        for i, line in enumerate(results):
            x = (self.width - len(line)) // 2
            y = title_y + 4 + i
            self.renderer.draw_text(x, y, line)

        self.renderer.refresh()

        # Wait for input
        while True:
            key_action = self.input_handler.get_key_action()

            if key_action == KeyAction.QUIT:
                self.status = GameStatus.EXITING
                return
            elif key_action == KeyAction.START:
                # Restart game
                self._start_game()
                self._game_loop()
                result = self._calculate_result()
                self._show_results(result)

    def _get_elapsed_time(self) -> float:
        """
        Calculate the elapsed time since game start.

        Returns:
            Elapsed time in seconds
        """
        return time.time() - self.start_time

    def get_statistics(self) -> dict:
        """
        Get current game statistics.

        Returns:
            Dictionary containing:
            - score: Current score
            - snake_length: Current snake length
            - food_eaten: Total food eaten
            - high_score: Current high score
            - status: Current game status
        """
        return {
            "score": self.state.score,
            "snake_length": len(self.snake),
            "food_eaten": self.state.food_eaten,
            "high_score": self.high_score,
            "status": self.status.value
        }


# Main entry point
def main() -> int:
    """
    Main entry point for the Snake game.

    Parses command line arguments and runs the game.

    Args:
        args: Command line arguments

    Returns:
        Exit code (0 for success, 1 for error)
    """
    # Parse command line arguments
    width = 40
    height = 20
    speed = 150

    args = sys.argv[1:]
    i = 0
    while i < len(args):
        if args[i] == "-w" and i + 1 < len(args):
            width = int(args[i + 1])
            i += 2
        elif args[i] == "-h" and i + 1 < len(args):
            height = int(args[i + 1])
            i += 2
        elif args[i] == "-s" and i + 1 < len(args):
            speed = int(args[i + 1])
            i += 2
        elif args[i] == "--help":
            print("Snake Game")
            print("")
            print("Usage: python -m snake [-w WIDTH] [-h HEIGHT] [-s SPEED]")
            print("")
            print("Options:")
            print("  -w WIDTH    Game width (default: 40)")
            print("  -h HEIGHT   Game height (default: 20)")
            print("  -s SPEED    Game speed in ms (default: 150)")
            print("  --help      Show this help message")
            return 0
        else:
            i += 1

    # Create and run game
    try:
        game = SnakeGame(width=width, height=height, speed=speed)
        result = game.run()

        # Print result summary to console after exit
        if result.status not in (GameStatus.EXITING,):
            print("\n" + str(result))

        return 0

    except ValueError as e:
        logger.error("Configuration error: %s", e)
        return 1
    except Exception as e:
        logger.error("Unexpected error: %s", e)
        return 1


if __name__ == "__main__":
    exit(main())

---

## Summary

The **main subsystem** implementation includes:

| File | Purpose |
|------|---------|
| `snake/__init__.py` | Package initialization and public API exports |
| `snake/main.py` | Main game orchestrator with `SnakeGame` class |

### Key Features:

1. **SnakeGame Class** - Central orchestrator managing:
   - Game lifecycle (menu → play → results)
   - Game loop with frame timing
   - Input handling
   - Collision detection
   - Score tracking

2. **GameStatus Enum** - Tracks game states:
   - MENU, PLAYING, PAUSED, GAME_OVER, WON, EXITING

3. **GameResult Dataclass** - Final statistics:
   - Score, length, time played, high score

4. **Robust Error Handling**:
   - Signal handlers for clean shutdown
   - Terminal restoration on exit
   - Input validation

5. **Command Line Interface**:
   - Width, height, speed options
   - Help documentation