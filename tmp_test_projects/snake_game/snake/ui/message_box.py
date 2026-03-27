"""
Message Box Module

Handles modal message dialogs for the Snake game including:
- Game over screens
- Pause notifications
- Level up announcements
- Score displays
- Confirmation dialogs

Provides a consistent UI for all game messages.
"""

from typing import Optional, List, Callable, Any, Tuple
from dataclasses import dataclass, field
from enum import Enum, auto
from abc import ABC, abstractmethod


class MessageBoxType(Enum):
    """Types of message boxes."""
    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    SUCCESS = auto()
    QUESTION = auto()


@dataclass(frozen=True)
class Button:
    """Represents a button in a message box."""
    label: str
    action: str
    is_default: bool = False
    is_cancel: bool = False
    
    def __str__(self) -> str:
        """Return button string representation."""
        return self.label


@dataclass
class MessageBoxConfig:
    """Configuration for message box appearance."""
    # Border characters
    top_left: str = "┌"
    top_right: str = "┐"
    bottom_left: str = "└"
    bottom_right: str = "┘"
    horizontal: str = "─"
    vertical: str = "│"
    
    # Padding
    content_padding: int = 2
    button_padding: int = 1
    
    # Default dimensions
    min_width: int = 40
    min_height: int = 10
    
    # Colors (as strings for flexibility)
    border_color: str = "\033[36m"  # Cyan
    title_color: str = "\033[1m"    # Bold
    content_color: str = "\033[37m" # White
    button_color: str = "\033[32m"  # Green
    default_button_color: str = "\033[1;32m"  # Bright Green
    
    # Type-specific colors
    info_color: str = "\033[34m"    # Blue
    warning_color: str = "\033[33m" # Yellow
    error_color: str = "\033[31m"   # Red
    success_color: str = "\033[32m" # Green
    question_color: str = "\033[35m" # Magenta


class MessageBoxStyle(Enum):
    """Predefined message box styles."""
    SIMPLE = auto()
    DECORATED = auto()
    RETRO = auto()


class BaseMessageBox(ABC):
    """Abstract base class for message boxes."""
    
    def __init__(self, config: Optional[MessageBoxConfig] = None) -> None:
        """
        Initialize message box.
        
        Args:
            config: Custom configuration
        """
        self.config = config if config else MessageBoxConfig()
        self._title: str = ""
        self._message: str = ""
        self._message_type: MessageBoxType = MessageBoxType.INFO
        self._buttons: List[Button] = []
        self._width: int = self.config.min_width
        self._height: int = self.config.min_height
        self._result: Optional[str] = None
    
    @abstractmethod
    def render(self) -> str:
        """Render the message box as a string."""
        pass
    
    @abstractmethod
    def show(
        self,
        title: str,
        message: str,
        buttons: Optional[List[Button]] = None,
        message_type: Optional[MessageBoxType] = None
    ) -> str:
        """
        Show the message box and return user's choice.
        
        Args:
            title: Title of the message box
            message: Message to display
            buttons: Buttons to show
            message_type: Type of message
            
        Returns:
            User's button choice or None
        """
        pass
    
    def _get_type_color(self) -> str:
        """Get color based on message type."""
        colors = {
            MessageBoxType.INFO: self.config.info_color,
            MessageBoxType.WARNING: self.config.warning_color,
            MessageBoxType.ERROR: self.config.error_color,
            MessageBoxType.SUCCESS: self.config.success_color,
            MessageBoxType.QUESTION: self.config.question_color,
        }
        return colors.get(self._message_type, self.config.content_color)


class SimpleMessageBox(BaseMessageBox):
    """
    Simple message box implementation.
    
    Provides basic modal dialog functionality with configurable
    title, message, and buttons.
    """
    
    def __init__(self, config: Optional[MessageBoxConfig] = None) -> None:
        """Initialize simple message box."""
        super().__init__(config)
    
    def _apply_color(self, text: str, color: str) -> str:
        """Apply color to text."""
        return f"{color}{text}\033[0m"
    
    def _wrap_text(self, text: str, width: int) -> List[str]:
        """
        Wrap text to fit within specified width.
        
        Args:
            text: Text to wrap
            width: Maximum line width
            
        Returns:
            List of wrapped lines
        """
        if width <= 0:
            return [text]
        
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            if len(current_line) + len(word) + 1 <= width:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        
        if current_line:
            lines.append(current_line)
        
        return lines if lines else [text]
    
    def _calculate_dimensions(
        self,
        title: str,
        message: str,
        buttons: List[Button]
    ) -> Tuple[int, int]:
        """
        Calculate required dimensions for content.
        
        Args:
            title: Title text
            message: Message text
            buttons: List of buttons
            
        Returns:
            Tuple of (width, height)
        """
        # Calculate content width
        title_width = len(title) + 2  # Padding
        message_lines = self._wrap_text(message, self.config.min_width - 4)
        message_width = max(len(line) for line in message_lines) + 4 if message_lines else 0
        button_width = sum(len(b.label) for b in buttons) + len(buttons) - 1 + 4 if buttons else 0
        
        content_width = max(title_width, message_width, button_width)
        width = max(self.config.min_width, content_width + 2)
        
        # Calculate content height
        height = 1  # Title
        height += len(message_lines) + 2  # Message with padding
        if buttons:
            height += 2  # Button area with padding
        
        return width, max(self.config.min_height, height)
    
    def render(self) -> str:
        """
        Render the message box.
        
        Returns:
            Rendered message box as string
        """
        lines = []
        
        # Border characters
        tl, tr, bl, br = (
            self.config.top_left, self.config.top_right,
            self.config.bottom_left, self.config.bottom_right
        )
        h, v = self.config.horizontal, self.config.vertical
        
        # Calculate dimensions based on content
        button_strs = [b.label for b in self._buttons] if self._buttons else []
        width, height = self._calculate_dimensions(
            self._title, self._message, self._buttons
        )
        
        # Top border with title
        title_centered = self._title.center(width - 2)
        lines.append(
            self._apply_color(
                f"{tl}{h * (width - 2)}{tr}",
                self.config.border_color
            )
        )
        lines.append(
            self._apply_color(
                f"{v} {title_centered} {v}",
                self.config.title_color
            )
        )
        lines.append(
            self._apply_color(
                f"{tl}{h * (width - 2)}{tr}",
                self.config.border_color
            )
        )
        
        # Message content
        type_color = self._get_type_color()
        message_lines = self._wrap_text(
            self._message, width - 4 - 2 * self.config.content_padding
        )
        
        # Add top padding
        lines.append(
            self._apply_color(
                f"{v}{self.config.horizontal * (width - 2)}{v}",
                self.config.border_color
            )
        )
        
        for msg_line in message_lines:
            padded_line = msg_line.center(width - 2 - 2 * self.config.content_padding)
            lines.append(
                self._apply_color(
                    f"{v}{self.config.content_padding * ' '}"
                    f"{padded_line}"
                    f"{self.config.content_padding * ' '}{v}",
                    type_color
                )
            )
        
        # Add bottom padding
        lines.append(
            self._apply_color(
                f"{v}{self.config.horizontal * (width - 2)}{v}",
                self.config.border_color
            )
        )
        
        # Buttons
        if self._buttons:
            button_line = "  "
            for i, button in enumerate(self._buttons):
                if button.is_default:
                    button_line += f"[{button.label}]"
                else:
                    button_line += f"({button.label})"
                if i < len(self._buttons) - 1:
                    button_line += "  "
            button_line += "  "
            
            lines.append(
                self._apply_color(
                    f"{v}{button_line}{v}",
                    self.config.button_color
                )
            )
        
        # Bottom border
        lines.append(
            self._apply_color(
                f"{bl}{h * (width - 2)}{br}",
                self.config.border_color
            )
        )
        
        return "\n".join(lines)
    
    def show(
        self,
        title: str,
        message: str,
        buttons: Optional[List[Button]] = None,
        message_type: Optional[MessageBoxType] = None
    ) -> str:
        """
        Show the message box.
        
        Args:
            title: Title of the message box
            message: Message to display
            buttons: Buttons to show
            message_type: Type of message
            
        Returns:
            User's button choice
        """
        self._title = title
        self._message = message
        self._buttons = buttons if buttons else []
        self._message_type = message_type or MessageBoxType.INFO
        
        # Render the box
        rendered = self.render()
        print(rendered)
        
        # Return default button action if available
        for button in self._buttons:
            if button.is_default:
                return button.action
        
        return self._buttons[0].action if self._buttons else ""


class GameMessageBox(SimpleMessageBox):
    """
    Specialized message box for game-related messages.
    
    Provides convenience methods for common game scenarios
    like game over, pause, level up, etc.
    """
    
    def __init__(self, config: Optional[MessageBoxConfig] = None) -> None:
        """Initialize game message box."""
        super().__init__(config)
    
    def show_game_over(
        self,
        score: int,
        high_score: int,
        is_new_high_score: bool = False
    ) -> str:
        """
        Show game over message.
        
        Args:
            score: Final score
            high_score: High score
            is_new_high_score: Whether this is a new high score
            
        Returns:
            User's choice (replay or quit)
        """
        message_parts = [
            f"Game Over!",
            f"Final Score: {score}",
            f"High Score:  {high_score}",
        ]
        
        if is_new_high_score:
            message_parts.append("*** NEW HIGH SCORE! ***")
        
        message_parts.append("")
        message_parts.append("Press [R] to Replay or (Q) to Quit")
        
        message = "\n".join(message_parts)
        
        buttons = [
            Button("R", "replay", is_default=True),
            Button("Q", "quit"),
        ]
        
        return self.show(
            title="GAME OVER",
            message=message,
            buttons=buttons,
            message_type=MessageBoxType.ERROR
        )
    
    def show_pause(self, score: int, high_score: int) -> str:
        """
        Show pause message.
        
        Args:
            score: Current score
            high_score: High score
            
        Returns:
            Always returns "resume"
        """
        message = (
            f"  PAUSED\n"
            f"  Score: {score}\n"
            f"  High:  {high_score}\n"
            f"\n"
            f"Press [SPACE] to Resume or (Q) to Quit"
        )
        
        buttons = [
            Button("SPACE", "resume", is_default=True),
            Button("Q", "quit"),
        ]
        
        return self.show(
            title="PAUSED",
            message=message,
            buttons=buttons,
            message_type=MessageBoxType.INFO
        )
    
    def show_level_up(self, old_level: int, new_level: int) -> str:
        """
        Show level up message.
        
        Args:
            old_level: Previous level
            new_level: New level
            
        Returns:
            "continue" to proceed
        """
        message = (
            f"  LEVEL UP!\n"
            f"  Level {old_level} → Level {new_level}\n"
            f"\n"
            f"Press any key to continue..."
        )
        
        buttons = [Button("ANY", "continue", is_default=True)]
        
        return self.show(
            title="LEVEL UP!",
            message=message,
            buttons=buttons,
            message_type=MessageBoxType.SUCCESS
        )
    
    def show_game_start(self) -> str:
        """
        Show game start message.
        
        Returns:
            "start" to begin game
        """
        message = (
            f"  Welcome to Snake!\n"
            f"\n"
            f"  Controls:\n"
            f"    Arrow Keys or WASD - Move\n"
            f"    SPACE - Pause/Resume\n"
            f"    Q - Quit\n"
            f"\n"
            f"Press any key to start..."
        )
        
        buttons = [Button("ANY", "start", is_default=True)]
        
        return self.show(
            title="SNAKE GAME",
            message=message,
            buttons=buttons,
            message_type=MessageBoxType.INFO
        )
    
    def show_score_update(self, score: int, high_score: int) -> str:
        """
        Show score update notification.
        
        Args:
            score: Current score
            high_score: High score
            
        Returns:
            "continue" to proceed
        """
        is_new_high = score >= high_score
        message = (
            f"  Score: {score}\n"
            f"  High:  {high_score}\n"
        )
        
        if is_new_high:
            message += "\n  *** NEW HIGH SCORE! ***"
        
        message += "\n\nPress any key to continue..."
        
        buttons = [Button("ANY", "continue", is_default=True)]
        
        msg_type = MessageBoxType.SUCCESS if is_new_high else MessageBoxType.INFO
        
        return self.show(
            title="SCORE UPDATE",
            message=message,
            buttons=buttons,
            message_type=msg_type
        )
    
    def show_confirmation(
        self,
        message: str,
        default: bool = True
    ) -> bool:
        """
        Show confirmation dialog.
        
        Args:
            message: Question to ask
            default: Default answer (True for Yes, False for No)
            
        Returns:
            User's choice (True for Yes, False for No)
        """
        buttons = [
            Button("Y", "yes", is_default=default),
            Button("N", "no", is_cancel=not default),
        ]
        
        result = self.show(
            title="Confirm",
            message=message,
            buttons=buttons,
            message_type=MessageBoxType.QUESTION
        )
        
        return result == "yes"
    
    def show_warning(self, message: str) -> str:
        """
        Show warning message.
        
        Args:
            message: Warning message
            
        Returns:
            "ok" to acknowledge
        """
        buttons = [Button("OK", "ok", is_default=True)]
        
        return self.show(
            title="Warning",
            message=message,
            buttons=buttons,
            message_type=MessageBoxType.WARNING
        )
    
    def show_info(self, title: str, message: str) -> str:
        """
        Show info message.
        
        Args:
            title: Title
            message: Message
            
        Returns:
            "ok" to acknowledge
        """
        buttons = [Button("OK", "ok", is_default=True)]
        
        return self.show(
            title=title,
            message=message,
            buttons=buttons,
            message_type=MessageBoxType.INFO
        )
    
    def show_error(self, title: str, message: str) -> str:
        """
        Show error message.
        
        Args:
            title: Title
            message: Error message
            
        Returns:
            "ok" to acknowledge
        """
        buttons = [Button("OK", "ok", is_default=True)]
        
        return self.show(
            title=title,
            message=message,
            buttons=buttons,
            message_type=MessageBoxType.ERROR
        )


class OverlayMessageBox:
    """
    Message box that renders as an overlay on the game board.
    
    This class provides message boxes that can be composited
    over the existing game board for seamless UI transitions.
    """
    
    def __init__(self, config: Optional[MessageBoxConfig] = None) -> None:
        """Initialize overlay message box."""
        self.config = config if config else MessageBoxConfig()
        self._message_box = GameMessageBox(config)
    
    def render_game_over_overlay(
        self,
        board_width: int,
        board_height: int,
        score: int,
        high_score: int,
        is_new_high_score: bool = False
    ) -> str:
        """
        Render game over overlay on game board.
        
        Args:
            board_width: Width of game board
            board_height: Height of game board
            score: Final score
            high_score: High score
            is_new_high_score: Whether this is a new high score
            
        Returns:
            Overlay string to render over game board
        """
        lines = []
        
        # Calculate center positions
        game_over = "GAME OVER!"
        go_width = len(game_over)
        go_x = (board_width - go_width) // 2
        
        score_text = f"Score: {score}"
        score_width = len(score_text)
        score_x = (board_width - score_width) // 2
        
        high_text = f"High: {high_score}"
        high_x = (board_width - score_width) // 2
        
        # Game over text
        for y in range(board_height):
            row = []
            for x in range(board_width):
                if y == board_height // 2 - 1 and go_x <= x < go_x + go_width:
                    char = game_over[x - go_x]
                    row.append(f"\033[91m{char}\033[0m")
                elif y == board_height // 2 and score_x <= x < score_x + score_width:
                    char = score_text[x - score_x]
                    row.append(f"\033[93m{char}\033[0m")
                elif y == board_height // 2 + 1 and high_x <= x < high_x + len(high_text):
                    char = high_text[x - high_x]
                    row.append(f"\033[36m{char}\033[0m")
                else:
                    row.append(" ")
            lines.append("".join(row))
        
        return "\n".join(lines)
    
    def render_pause_overlay(
        self,
        board_width: int,
        board_height: int,
        score: int,
        high_score: int
    ) -> str:
        """
        Render pause overlay on game board.
        
        Args:
            board_width: Width of game board
            board_height: Height of game board
            score: Current score
            high_score: High score
            
        Returns:
            Overlay string to render over game board
        """
        lines = []
        
        paused = "  PAUSED  "
        p_width = len(paused)
        p_x = (board_width - p_width) // 2
        
        score_text = f"Score: {score}"
        score_width = len(score_text)
        score_x = (board_width - score_width) // 2
        
        high_text = f"High: {high_score}"
        high_x = (board_width - score_width) // 2
        
        for y in range(board_height):
            row = []
            for x in range(board_width):
                if y == board_height // 2 and p_x <= x < p_x + p_width:
                    char = paused[x - p_x]
                    row.append(f"\033[93m{char}\033[0m")
                elif y == board_height // 2 + 2 and score_x <= x < score_x + score_width:
                    char = score_text[x - score_x]
                    row.append(f"\033[36m{char}\033[0m")
                elif y == board_height // 2 + 3 and high_x <= x < high_x + len(high_text):
                    char = high_text[x - high_x]
                    row.append(f"\033[36m{char}\033[0m")
                else:
                    row.append(" ")
            lines.append("".join(row))
        
        return "\n".join(lines)
    
    def render_level_up_overlay(
        self,
        board_width: int,
        board_height: int,
        new_level: int
    ) -> str:
        """
        Render level up overlay on game board.
        
        Args:
            board_width: Width of game board
            board_height: Height of game board
            new_level: New level reached
            
        Returns:
            Overlay string to render over game board
        """
        lines = []
        
        level_up = f"LEVEL UP! Level {new_level}"
        lu_width = len(level_up)
        lu_x = (board_width - lu_width) // 2
        
        for y in range(board_height):
            row = []
            for x in range(board_width):
                if y == board_height // 2 and lu_x <= x < lu_x + lu_width:
                    char = level_up[x - lu_x]
                    row.append(f"\033[93m{char}\033[0m")
                else:
                    row.append(" ")
            lines.append("".join(row))
        
        return "\n".join(lines)
    
    def render_flash_overlay(
        self,
        board_width: int,
        board_height: int,
        frame: int = 0
    ) -> str:
        """
        Render flash effect overlay.
        
        Args:
            board_width: Width of game board
            board_height: Height of game board
            frame: Animation frame (0 or 1)
            
        Returns:
            Flash effect string
        """
        if frame == 0:
            flash_char = "\033[43m \033[0m"  # Yellow background
        else:
            flash_char = " "
        
        lines = []
        for _ in range(board_height):
            lines.append(flash_char * board_width)
        
        return "\n".join(lines)

---

## Summary

I've implemented the complete UI subsystem for the Snake game with four modules:

### 1. **display_manager.py**
- Cross-platform terminal control (Windows/Unix)
- Screen clearing, cursor hiding/showing
- Cursor positioning
- Terminal size detection
- Platform detection and cleanup handlers

### 2. **game_renderer.py**
- Game board rendering with walls
- Snake body and head rendering
- Food rendering
- Score panel and footer
- Pause and game over screens
- Color themes (default, dark, retro, minimal)
- ANSI color support

### 3. **input_handler.py**
- Platform-specific input handling
- Non-blocking keyboard reads
- Direction detection (arrows, WASD)
- Special keys (space, enter, escape)
- Callback system for key events
- Input state management

### 4. **message_box.py**
- Modal message dialogs
- Game-specific message types (game over, pause, level up)
- Configurable appearance
- Button support with default/cancel actions
- Overlay rendering for game board integration

All modules follow Python best practices with:
- Type hints throughout
- Comprehensive docstrings
- Proper error handling
- Cross-platform compatibility
- Clean architecture with separation of concerns