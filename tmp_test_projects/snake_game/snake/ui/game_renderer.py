"""
Game Renderer Module

Handles all visual rendering of the Snake game including:
- Game board and walls
- Snake body and head
- Food items
- Score display
- Game status messages

Uses ASCII characters and ANSI color codes for visual appeal.
"""

from typing import List, Tuple, Optional, Dict, Any
from dataclasses import dataclass
from enum import Enum, auto
from abc import ABC, abstractmethod


class Color(Enum):
    """ANSI color codes for terminal output."""
    RESET = "\033[0m"
    
    # Foreground colors
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # Bright foreground colors
    BRIGHT_BLACK = "\033[90m"
    BRIGHT_RED = "\033[91m"
    BRIGHT_GREEN = "\033[92m"
    BRIGHT_YELLOW = "\033[93m"
    BRIGHT_BLUE = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN = "\033[96m"
    BRIGHT_WHITE = "\033[97m"
    
    # Background colors
    BG_BLACK = "\033[40m"
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN = "\033[46m"
    BG_WHITE = "\033[47m"
    
    # Styles
    BOLD = "\033[1m"
    DIM = "\033[2m"
    UNDERLINE = "\033[4m"
    BLINK = "\033[5m"
    REVERSE = "\033[7m"


@dataclass(frozen=True)
class Position:
    """Represents a position on the game board."""
    x: int
    y: int
    
    def __hash__(self) -> int:
        return hash((self.x, self.y))
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Position):
            return False
        return self.x == other.x and self.y == other.y
    
    def __add__(self, other: Tuple[int, int]) -> "Position":
        """Add a tuple to this position."""
        return Position(self.x + other[0], self.y + other[1])
    
    def __sub__(self, other: Tuple[int, int]) -> "Position":
        """Subtract a tuple from this position."""
        return Position(self.x - other[0], self.y - other[1])


@dataclass
class GameBoardConfig:
    """Configuration for the game board rendering."""
    wall_top_left: str = "┌"
    wall_top_right: str = "┐"
    wall_bottom_left: str = "└"
    wall_bottom_right: str = "┘"
    wall_horizontal: str = "─"
    wall_vertical: str = "│"
    snake_head: str = "█"
    snake_body: str = "█"
    food: str = "●"
    empty_space: str = " "
    
    # Colors
    wall_color: Color = Color.CYAN
    snake_head_color: Color = Color.BRIGHT_GREEN
    snake_body_color: Color = Color.GREEN
    food_color: Color = Color.BRIGHT_RED
    text_color: Color = Color.WHITE


class Theme:
    """Predefined color themes for the game."""
    
    DEFAULT = GameBoardConfig()
    
    DARK = GameBoardConfig(
        wall_color=Color.BRIGHT_CYAN,
        snake_head_color=Color.BRIGHT_GREEN,
        snake_body_color=Color.GREEN,
        food_color=Color.BRIGHT_YELLOW,
        text_color=Color.BRIGHT_WHITE
    )
    
    RETRO = GameBoardConfig(
        wall_top_left="┌",
        wall_top_right="┐",
        wall_bottom_left="└",
        wall_bottom_right="┘",
        wall_horizontal="─",
        wall_vertical="│",
        snake_head="@",
        snake_body="o",
        food="*",
        wall_color=Color.YELLOW,
        snake_head_color=Color.BRIGHT_GREEN,
        snake_body_color=Color.GREEN,
        food_color=Color.BRIGHT_RED,
        text_color=Color.WHITE
    )
    
    MINIMAL = GameBoardConfig(
        wall_top_left="+",
        wall_top_right="+",
        wall_bottom_left="+",
        wall_bottom_right="+",
        wall_horizontal="-",
        wall_vertical="|",
        snake_head="#",
        snake_body=".",
        food="o",
        wall_color=Color.WHITE,
        snake_head_color=Color.GREEN,
        snake_body_color=Color.BRIGHT_BLACK,
        food_color=Color.RED,
        text_color=Color.WHITE
    )


class GameRenderer:
    """
    Renders the Snake game visual elements to the terminal.
    
    This class handles all visual aspects of the game including:
    - Drawing the game board with walls
    - Rendering the snake body and head
    - Displaying food items
    - Showing score and game information
    - Applying color themes
    
    Example:
        >>> renderer = GameRenderer()
        >>> renderer.render_header("Snake Game")
        >>> renderer.render_board(snake_body, food_position, walls)
        >>> renderer.render_footer(score=100, high_score=200)
    """
    
    def __init__(self, theme: Optional[GameBoardConfig] = None) -> None:
        """
        Initialize the GameRenderer.
        
        Args:
            theme: Optional custom theme configuration. Uses default if None.
        """
        self.config = theme if theme else GameBoardConfig()
        self._frame_buffer: List[str] = []
        self._last_render_time: float = 0.0
    
    def set_theme(self, theme: GameBoardConfig) -> None:
        """
        Set a custom theme for rendering.
        
        Args:
            theme: Theme configuration to apply
        """
        self.config = theme
    
    def apply_color(self, text: str, color: Color) -> str:
        """
        Apply ANSI color to text.
        
        Args:
            text: Text to colorize
            color: Color to apply
            
        Returns:
            Colorized text string
        """
        return f"{color.value}{text}{Color.RESET.value}"
    
    def apply_style(self, text: str, style: Color) -> str:
        """
        Apply ANSI style (bold, dim, etc.) to text.
        
        Args:
            text: Text to style
            style: Style to apply
            
        Returns:
            Styled text string
        """
        return f"{style.value}{text}{Color.RESET.value}"
    
    def render_header(self, title: str = "SNAKE") -> str:
        """
        Render the game header with title.
        
        Args:
            title: Game title to display
            
        Returns:
            Formatted header string
        """
        # Create decorative header
        border_char = "═"
        title_length = len(title)
        padding = (60 - title_length) // 2
        
        header_lines = [
            " " * 15 + self.apply_color(border_char * 30, Color.CYAN),
            " " * 15 + self.apply_color(f" {title} ", Color.BOLD),
            " " * 15 + self.apply_color(border_char * 30, Color.CYAN),
            ""
        ]
        
        return "\n".join(header_lines)
    
    def render_board(
        self,
        snake: List[Position],
        food: Position,
        board_width: int,
        board_height: int,
        walls: Optional[List[Tuple[Position, Position]]] = None
    ) -> str:
        """
        Render the game board with snake and food.
        
        Args:
            snake: List of positions representing snake body (head first)
            food: Position of the food
            board_width: Width of the game board
            board_height: Height of the game board
            walls: Optional list of wall segments as (start, end) tuples
            
        Returns:
            Formatted board string ready for display
        """
        if not snake:
            snake = [Position(0, 0)]
        
        # Create board grid
        grid: List[List[str]] = []
        for y in range(board_height + 2):
            row: List[str] = []
            for x in range(board_width + 2):
                row.append(self.config.empty_space)
            grid.append(row)
        
        # Draw outer walls
        for x in range(board_width + 2):
            grid[0][x] = self.config.wall_horizontal
            grid[board_height + 1][x] = self.config.wall_horizontal
        for y in range(board_height + 2):
            grid[y][0] = self.config.wall_vertical
            grid[y][board_width + 1] = self.config.wall_vertical
        
        # Corner pieces
        grid[0][0] = self.config.wall_top_left
        grid[0][board_width + 1] = self.config.wall_top_right
        grid[board_height + 1][0] = self.config.wall_bottom_left
        grid[board_height + 1][board_width + 1] = self.config.wall_bottom_right
        
        # Draw internal walls
        if walls:
            self._draw_walls(grid, walls, board_width, board_height)
        
        # Draw food
        if 0 <= food.y < board_height and 0 <= food.x < board_width:
            grid[food.y + 1][food.x + 1] = self.config.food
        
        # Draw snake (body first, then head to ensure head is on top)
        for i, pos in enumerate(snake):
            if 0 <= pos.y < board_height and 0 <= pos.x < board_width:
                if i == 0:  # Head
                    grid[pos.y + 1][pos.x + 1] = self.config.snake_head
                else:  # Body
                    grid[pos.y + 1][pos.x + 1] = self.config.snake_body
        
        # Convert grid to string with colors
        return self._grid_to_colored_string(grid)
    
    def _draw_walls(
        self,
        grid: List[List[str]],
        walls: List[Tuple[Position, Position]],
        board_width: int,
        board_height: int
    ) -> None:
        """
        Draw internal walls on the grid.
        
        Args:
            grid: The game grid to draw on
            walls: List of wall segments
            board_width: Board width
            board_height: Board height
        """
        for start, end in walls:
            sx, sy = start.x + 1, start.y + 1
            ex, ey = end.x + 1, end.y + 1
            
            # Clamp to board boundaries
            sx = max(1, min(sx, board_width))
            sy = max(1, min(sy, board_height))
            ex = max(1, min(ex, board_width))
            ey = max(1, min(ey, board_height))
            
            # Draw horizontal wall
            if sy == ey:
                for x in range(min(sx, ex), max(sx, ex) + 1):
                    grid[sy][x] = self.config.wall_horizontal
            
            # Draw vertical wall
            elif sx == ex:
                for y in range(min(sy, ey), max(sy, ey) + 1):
                    grid[y][sx] = self.config.wall_vertical
    
    def _grid_to_colored_string(self, grid: List[List[str]]) -> str:
        """
        Convert grid with character codes to colored string.
        
        Args:
            grid: 2D list of characters
            
        Returns:
            Colored string representation
        """
        lines = []
        for row in grid:
            colored_row = []
            for char in row:
                color = self._get_char_color(char)
                if color:
                    colored_row.append(f"{color.value}{char}{Color.RESET.value}")
                else:
                    colored_row.append(char)
            lines.append("".join(colored_row))
        return "\n".join(lines)
    
    def _get_char_color(self, char: str) -> Optional[Color]:
        """
        Get the color for a character based on game config.
        
        Args:
            char: Character to colorize
            
        Returns:
            Color or None if no special coloring
        """
        if char == self.config.snake_head:
            return self.config.snake_head_color
        elif char == self.config.snake_body:
            return self.config.snake_body_color
        elif char == self.config.food:
            return self.config.food_color
        elif char in (self.config.wall_horizontal, self.config.wall_vertical,
                      self.config.wall_top_left, self.config.wall_top_right,
                      self.config.wall_bottom_left, self.config.wall_bottom_right):
            return self.config.wall_color
        return None
    
    def render_score_panel(
        self,
        score: int,
        high_score: int,
        level: int = 1,
        length: int = 0
    ) -> str:
        """
        Render the score and game information panel.
        
        Args:
            score: Current score
            high_score: High score
            level: Current level
            length: Current snake length
            
        Returns:
            Formatted score panel string
        """
        panel_width = 25
        
        lines = [
            self.apply_color("┌" + "─" * (panel_width - 2) + "┐", Color.CYAN),
            f"│  {self.apply_color('SCORE:', Color.YELLOW)}  {score:>6} │",
            f"│  {self.apply_color('HIGH:',  Color.YELLOW)}  {high_score:>6} │",
            f"│  {self.apply_color('LEVEL:', Color.YELLOW)} {level:>6} │",
            f"│  {self.apply_color('LENGTH:',Color.YELLOW)} {length:>5} │",
            self.apply_color("└" + "─" * (panel_width - 2) + "┘", Color.CYAN),
        ]
        
        return "\n".join(lines)
    
    def render_footer(
        self,
        score: int,
        high_score: int,
        level: int = 1,
        message: Optional[str] = None
    ) -> str:
        """
        Render the game footer with score summary.
        
        Args:
            score: Current score
            high_score: High score
            level: Current level
            message: Optional message to display
            
        Returns:
            Formatted footer string
        """
        footer_width = 80
        
        # Score line
        score_line = (
            f"  {self.apply_color('SCORE:', Color.YELLOW)} {score:>6} | "
            f"{self.apply_color('HIGH:', Color.YELLOW)} {high_score:>6} | "
            f"{self.apply_color('LEVEL:', Color.YELLOW)} {level}"
        )
        
        # Message line if provided
        if message:
            msg_line = f"  {self.apply_color(message, Color.BRIGHT_WHITE)}"
            return f"{score_line}\n{msg_line}"
        
        return score_line
    
    def render_pause_screen(
        self,
        board_width: int,
        board_height: int,
        score: int,
        high_score: int
    ) -> str:
        """
        Render the pause screen overlay.
        
        Args:
            board_width: Width of game board
            board_height: Height of game board
            score: Current score
            high_score: High score
            
        Returns:
            Formatted pause screen string
        """
        # Calculate center position
        msg = "  PAUSED  "
        msg_width = len(msg)
        start_x = (board_width - msg_width) // 2
        
        lines = []
        
        # Create pause overlay
        for y in range(board_height):
            row = []
            for x in range(board_width):
                if y == board_height // 2 and x == start_x:
                    row.append(self.apply_color(msg, Color.BRIGHT_YELLOW))
                else:
                    row.append(" " * len(msg) if x == start_x else " ")
            lines.append("".join(row))
        
        # Score info below pause
        score_info = f"Score: {score}  High: {high_score}"
        info_width = len(score_info)
        info_start = (board_width - info_width) // 2
        
        pause_lines = lines + [
            " " * info_start + self.apply_color(score_info, Color.CYAN)
        ]
        
        return "\n".join(pause_lines)
    
    def render_game_over(
        self,
        board_width: int,
        board_height: int,
        score: int,
        high_score: int,
        is_new_high_score: bool = False
    ) -> str:
        """
        Render the game over screen.
        
        Args:
            board_width: Width of game board
            board_height: Height of game board
            score: Final score
            high_score: High score
            is_new_high_score: Whether this is a new high score
            
        Returns:
            Formatted game over screen string
        """
        lines = []
        
        # GAME OVER text
        game_over = "GAME OVER!"
        go_width = len(game_over)
        go_start = (board_width - go_width) // 2
        
        lines.append(" " * go_start + self.apply_color(game_over, Color.BRIGHT_RED))
        lines.append("")
        
        # Score display
        score_text = f"Final Score: {score}"
        score_width = len(score_text)
        score_start = (board_width - score_width) // 2
        lines.append(" " * score_start + self.apply_color(score_text, Color.YELLOW))
        
        # High score
        high_text = f"High Score:  {high_score}"
        high_start = (board_width - score_width) // 2
        lines.append(" " * high_start + self.apply_color(high_text, Color.CYAN))
        
        # New high score message
        if is_new_high_score:
            new_hs = ">>> NEW HIGH SCORE! <<<"
            new_hs_width = len(new_hs)
            new_hs_start = (board_width - new_hs_width) // 2
            lines.append("")
            lines.append(" " * new_hs_start + 
                       self.apply_color(new_hs, Color.BRIGHT_MAGENTA))
        
        # Instructions
        lines.append("")
        replay = "Press 'R' to replay or 'Q' to quit"
        replay_width = len(replay)
        replay_start = (board_width - replay_width) // 2
        lines.append(" " * replay_start + 
                   self.apply_color(replay, Color.WHITE))
        
        return "\n".join(lines)
    
    def render_welcome_screen(
        self,
        terminal_width: int = 80,
        terminal_height: int = 25
    ) -> str:
        """
        Render the welcome screen with game instructions.
        
        Args:
            terminal_width: Terminal width
            terminal_height: Terminal height
            
        Returns:
            Formatted welcome screen string
        """
        # Center calculations
        title = "  ═══════════════════════════════════  "
        game_title = "       ★  SNAKE GAME  ★       "
        subtitle = "  ═══════════════════════════════════  "
        
        # Instructions
        instructions = [
            "",
            "  CONTROLS:",
            "  ┌─────────────────────────────────┐",
            "  │  ↑/W  - Move Up                 │",
            "  │  ↓/S  - Move Down               │",
            "  │  ←/A  - Move Left               │",
            "  │  →/D  - Move Right              │",
            "  │  SPACE - Pause/Resume           │",
            "  │  Q    - Quit Game               │",
            "  └─────────────────────────────────┘",
            "",
            "  OBJECTIVE:",
            "  Eat the food (●) to grow and score points!",
            "  Avoid hitting the walls and your own tail.",
            "",
            "  Press any key to start...",
        ]
        
        # Build centered output
        lines = [
            self.apply_color(title, Color.CYAN),
            self.apply_color(game_title, Color.BRIGHT_GREEN),
            self.apply_color(subtitle, Color.CYAN),
        ] + instructions
        
        return "\n".join(lines)
    
    def render_level_up(
        self,
        board_width: int,
        board_height: int,
        new_level: int,
        old_level: int
    ) -> str:
        """
        Render level up announcement.
        
        Args:
            board_width: Width of game board
            board_height: Height of game board
            new_level: New level reached
            old_level: Previous level
            
        Returns:
            Formatted level up screen string
        """
        lines = []
        
        level_up = f"  LEVEL UP!  "
        lu_width = len(level_up)
        lu_start = (board_width - lu_width) // 2
        
        lines.append(" " * lu_start + 
                   self.apply_color(level_up, Color.BRIGHT_YELLOW))
        lines.append("")
        
        level_change = f"  Level {old_level} → Level {new_level}  "
        lc_width = len(level_change)
        lc_start = (board_width - lc_width) // 2
        
        lines.append(" " * lc_start + 
                   self.apply_color(level_change, Color.CYAN))
        
        return "\n".join(lines)
    
    def render_flash_effect(
        self,
        board_width: int,
        board_height: int,
        frame: int = 0
    ) -> str:
        """
        Render a flash effect (for eating food, etc.).
        
        Args:
            board_width: Width of game board
            board_height: Height of game board
            frame: Animation frame (0 or 1 for on/off)
            
        Returns:
            Formatted flash effect string
        """
        if frame == 0:
            # Flash on - bright background
            flash_char = self.apply_color(" ", Color.BG_YELLOW)
        else:
            # Flash off - normal
            flash_char = " "
        
        lines = []
        for _ in range(board_height):
            lines.append(flash_char * board_width)
        
        return "\n".join(lines)
    
    def render_border(
        self,
        width: int,
        height: int,
        title: Optional[str] = None
    ) -> str:
        """
        Render a decorative border.
        
        Args:
            width: Border width
            height: Border height
            title: Optional title to display in border
            
        Returns:
            Formatted border string
        """
        lines = []
        
        top_border = "┌" + "─" * (width - 2) + "┐"
        middle_border = "│" + " " * (width - 2) + "│"
        bottom_border = "└" + "─" * (width - 2) + "┘"
        
        if title:
            title_line = "│" + title.center(width - 2) + "│"
            lines.append(self.apply_color(top_border, Color.CYAN))
            lines.append(self.apply_color(title_line, Color.BOLD))
            lines.append(self.apply_color(middle_border, Color.CYAN))
        else:
            lines.append(self.apply_color(top_border, Color.CYAN))
        
        for _ in range(height - 2):
            lines.append(self.apply_color(middle_border, Color.CYAN))
        
        lines.append(self.apply_color(bottom_border, Color.CYAN))
        
        return "\n".join(lines)
    
    def clear_frame(self) -> None:
        """Clear the internal frame buffer."""
        self._frame_buffer.clear()
    
    def __str__(self) -> str:
        """Return string representation of renderer state."""
        return f"GameRenderer(theme={self.config.snake_head_color.name})"

---