"""
Display Manager Module

Handles all display-related operations including screen clearing,
cursor positioning, and platform-specific terminal manipulation.

This module provides a cross-platform interface for terminal control
that abstracts away OS-specific differences between Windows and Unix-like systems.
"""

import os
import sys
import time
from typing import Tuple, Optional, NoReturn
from dataclasses import dataclass
from enum import Enum, auto


class PlatformType(Enum):
    """Enum representing supported platform types."""
    WINDOWS = auto()
    UNIX = auto()
    UNKNOWN = auto()


@dataclass(frozen=True)
class TerminalSize:
    """Data class representing terminal dimensions."""
    width: int
    height: int
    
    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Terminal dimensions must be positive integers")
    
    def is_valid(self) -> bool:
        """Check if terminal size is valid for game play."""
        return self.width >= 40 and self.height >= 15


class DisplayError(Exception):
    """Custom exception for display-related errors."""
    pass


class DisplayManager:
    """
    Manages all terminal display operations for the Snake game.
    
    This class provides a unified interface for:
    - Detecting the platform type
    - Clearing the terminal screen
    - Hiding/showing the cursor
    - Moving the cursor to specific positions
    - Getting terminal dimensions
    
    Example:
        >>> display = DisplayManager()
        >>> display.clear_screen()
        >>> display.hide_cursor()
        >>> display.move_cursor(10, 5)
    """
    
    # ANSI escape sequences for terminal control
    ANSI_CLEAR_SCREEN = "\033[2J"
    ANSI_MOVE_CURSOR = "\033[{row};{col}H"
    ANSI_HIDE_CURSOR = "\033[?25l"
    ANSI_SHOW_CURSOR = "\033[?25h"
    ANSI_RESET = "\033[0m"
    
    def __init__(self) -> None:
        """
        Initialize the DisplayManager.
        
        Detects the platform type and sets up platform-specific handlers.
        """
        self._platform = self._detect_platform()
        self._cursor_hidden = False
        self._original_title: Optional[str] = None
        self._original_cursor_visible: Optional[bool] = None
        
        # Set up cleanup handler
        self._setup_cleanup()
    
    def _detect_platform(self) -> PlatformType:
        """
        Detect the current platform type.
        
        Returns:
            PlatformType enum indicating the detected platform.
        """
        system_name = sys.platform.lower()
        
        if system_name.startswith("win"):
            return PlatformType.WINDOWS
        elif system_name in ("linux", "darwin", "freebsd", "cygwin"):
            return PlatformType.UNIX
        else:
            return PlatformType.UNKNOWN
    
    def _setup_cleanup(self) -> None:
        """Set up cleanup handlers for graceful termination."""
        import atexit
        
        def cleanup() -> None:
            """Restore terminal state on exit."""
            try:
                self.show_cursor()
                self.print("\n")
            except Exception:
                pass
        
        atexit.register(cleanup)
        
        # Handle keyboard interrupts
        original_sigint = None
        try:
            import signal
            original_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        except (ImportError, ValueError):
            pass
        
        self._original_sigint = original_sigint
    
    def _signal_handler(self, signum: int, frame: Optional[NoReturn]) -> NoReturn:
        """
        Handle SIGINT signal for graceful cleanup.
        
        Args:
            signum: Signal number
            frame: Current stack frame
        """
        self.show_cursor()
        self.print("\nGame interrupted. Goodbye!")
        sys.exit(0)
    
    @property
    def platform(self) -> PlatformType:
        """Get the detected platform type."""
        return self._platform
    
    @property
    def is_windows(self) -> bool:
        """Check if running on Windows platform."""
        return self._platform == PlatformType.WINDOWS
    
    @property
    def is_unix(self) -> bool:
        """Check if running on Unix-like platform."""
        return self._platform == PlatformType.UNIX
    
    def clear_screen(self) -> None:
        """
        Clear the terminal screen and move cursor to home position.
        
        Uses platform-appropriate method for clearing:
        - Windows: Uses system 'cls' command
        - Unix: Uses ANSI escape sequence
        """
        try:
            if self.is_windows:
                os.system("cls")
            else:
                self.print(self.ANSI_CLEAR_SCREEN)
        except OSError as e:
            raise DisplayError(f"Failed to clear screen: {e}")
    
    def hide_cursor(self) -> None:
        """
        Hide the terminal cursor.
        
        On Unix systems, uses ANSI escape sequence.
        On Windows, attempts to use console API if available.
        """
        if self._cursor_hidden:
            return
        
        try:
            if self.is_unix:
                self.print(self.ANSI_HIDE_CURSOR)
            elif self.is_windows:
                self._windows_hide_cursor()
            
            self._cursor_hidden = True
        except Exception as e:
            raise DisplayError(f"Failed to hide cursor: {e}")
    
    def _windows_hide_cursor(self) -> None:
        """Hide cursor using Windows Console API."""
        try:
            import ctypes
            
            # Import necessary Windows API functions
            kernel32 = ctypes.windll.kernel32
            conio = ctypes.windll.conio
            
            # Get console handle
            handle = kernel32.GetStdHandle(-11)
            
            # Get current console info
            console_info = ctypes.create_string_buffer(16)
            kernel32.GetConsoleScreenBufferInfo(
                handle, ctypes.byref(console_info)
            )
            
            # Hide cursor (set size to 0)
            cursor_info = ctypes.create_string_buffer(16)
            ctypes.memmove(cursor_info, console_info[12:], 4)
            cursor_info[0] = 0  # Set cursor size to 0 (hidden)
            ctypes.memmove(console_info[12:], cursor_info, 4)
            
            kernel32.SetConsoleCursorInfo(handle, ctypes.byref(console_info))
            
        except Exception:
            # Fall back to ANSI if Windows API fails
            # This often works in modern terminals on Windows
            self.print(self.ANSI_HIDE_CURSOR)
    
    def show_cursor(self) -> None:
        """
        Show the terminal cursor.
        
        Restores cursor visibility to the terminal.
        """
        if not self._cursor_hidden:
            return
        
        try:
            if self.is_unix:
                self.print(self.ANSI_SHOW_CURSOR)
            elif self.is_windows:
                self._windows_show_cursor()
            
            self._cursor_hidden = False
        except Exception as e:
            raise DisplayError(f"Failed to show cursor: {e}")
    
    def _windows_show_cursor(self) -> None:
        """Show cursor using Windows Console API."""
        try:
            import ctypes
            
            kernel32 = ctypes.windll.kernel32
            
            handle = kernel32.GetStdHandle(-11)
            
            console_info = ctypes.create_string_buffer(16)
            kernel32.GetConsoleScreenBufferInfo(
                handle, ctypes.byref(console_info)
            )
            
            # Show cursor (set size to 25)
            cursor_info = ctypes.create_string_buffer(16)
            ctypes.memmove(cursor_info, console_info[12:], 4)
            cursor_info[0] = 25  # Set cursor size to 25 (visible)
            ctypes.memmove(console_info[12:], cursor_info, 4)
            
            kernel32.SetConsoleCursorInfo(handle, ctypes.byref(console_info))
            
        except Exception:
            self.print(self.ANSI_SHOW_CURSOR)
    
    def move_cursor(self, row: int, col: int) -> None:
        """
        Move the cursor to a specific position.
        
        Args:
            row: Row position (1-indexed, 0 = top)
            col: Column position (1-indexed, 0 = left)
            
        Raises:
            ValueError: If row or col is negative
        """
        if row < 0:
            raise ValueError("Row position cannot be negative")
        if col < 0:
            raise ValueError("Column position cannot be negative")
        
        try:
            if self.is_unix:
                sequence = self.ANSI_MOVE_CURSOR.format(row=row + 1, col=col + 1)
                self.print(sequence)
            elif self.is_windows:
                self._windows_move_cursor(row, col)
        except Exception as e:
            raise DisplayError(f"Failed to move cursor to ({row}, {col}): {e}")
    
    def _windows_move_cursor(self, row: int, col: int) -> None:
        """Move cursor using Windows Console API."""
        try:
            import ctypes
            
            kernel32 = ctypes.windll.kernel32
            
            handle = kernel32.GetStdHandle(-11)
            
            # Create COORD structure
            coord = ctypes.c_short(col) | (ctypes.c_short(row) << 16)
            
            kernel32.SetConsoleCursorPosition(handle, coord)
            
        except Exception:
            # Fall back to ANSI
            self.move_cursor(row, col)
    
    def get_terminal_size(self) -> TerminalSize:
        """
        Get the current terminal dimensions.
        
        Returns:
            TerminalSize object with width and height
            
        Raises:
            DisplayError: If unable to determine terminal size
        """
        try:
            if self.is_windows:
                width, height = self._windows_get_terminal_size()
            else:
                width, height = self._unix_get_terminal_size()
            
            return TerminalSize(width=width, height=height)
            
        except Exception as e:
            raise DisplayError(f"Unable to get terminal size: {e}")
    
    def _windows_get_terminal_size(self) -> Tuple[int, int]:
        """Get terminal size using Windows Console API."""
        try:
            import ctypes
            
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-12)
            
            console_screen_buffer_info = ctypes.create_string_buffer(22)
            kernel32.GetConsoleScreenBufferInfo(
                handle, ctypes.byref(console_screen_buffer_info)
            )
            
            # Parse the buffer
            max_coord = int.from_bytes(
                console_screen_buffer_info[8:12], 'little'
            )
            width = max_coord & 0xFFFF
            height = max_coord >> 16
            
            return width, height
            
        except Exception:
            # Fallback: use shutil
            import shutil
            size = shutil.get_terminal_size((80, 25))
            return size.columns, size.lines
    
    def _unix_get_terminal_size(self) -> Tuple[int, int]:
        """Get terminal size using Unix methods."""
        try:
            # Try ioctl method first
            import struct
            import fcntl
            import termios
            
            # TIOCGWINSZ ioctl call
            fd = sys.stdout.fileno()
            rows, cols, *_ = struct.unpack(
                'hhhh', fcntl.ioctl(fd, termios.TIOCGWINSZ, struct.pack('hhhh', 0, 0, 0, 0))
            )
            
            return cols, rows
            
        except Exception:
            # Fallback: use shutil
            import shutil
            size = shutil.get_terminal_size((80, 25))
            return size.columns, size.lines
    
    def print(self, text: str, end: str = "\n", flush: bool = True) -> None:
        """
        Print text to terminal with proper handling.
        
        Args:
            text: Text to print
            end: String appended after text
            flush: Whether to flush output buffer
        """
        sys.stdout.write(text + end)
        if flush:
            sys.stdout.flush()
    
    def set_title(self, title: str) -> None:
        """
        Set the terminal window title.
        
        Args:
            title: New window title
        """
        try:
            # ANSI escape sequence for window title
            self.print(f"\033]0;{title}\007", end="", flush=True)
        except Exception:
            pass  # Silently fail if not supported
    
    def blink_screen(self, duration: float = 0.1) -> None:
        """
        Flash the screen for visual feedback.
        
        Args:
            duration: Time in seconds for each flash state
        """
        try:
            original = self.get_terminal_size()
            
            for _ in range(2):
                self.clear_screen()
                self.print("GAME OVER!")
                time.sleep(duration)
                self.clear_screen()
                time.sleep(duration)
                
        except Exception:
            pass
    
    def __enter__(self) -> "DisplayManager":
        """Context manager entry - hide cursor."""
        self.hide_cursor()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - show cursor."""
        self.show_cursor()

---