"""
Input Handler Module

Handles all keyboard input for the Snake game including:
- Non-blocking key reads
- Direction input (arrow keys, WASD)
- Special keys (Space, Enter, Escape)
- Platform-specific input handling

Provides cross-platform compatibility for Windows and Unix-like systems.
"""

import sys
import time
from typing import Optional, List, Callable, Set, Tuple, Any
from dataclasses import dataclass, field
from enum import Enum, auto
from abc import ABC, abstractmethod


class InputError(Exception):
    """Custom exception for input-related errors."""
    pass


class Direction(Enum):
    """Enum representing movement directions."""
    UP = auto()
    DOWN = auto()
    LEFT = auto()
    RIGHT = auto()
    NONE = auto()


@dataclass(frozen=True)
class KeyMapping:
    """Maps keyboard keys to game actions."""
    up_keys: Tuple[str, ...] = ("w", "W", "↑", "k", "K")
    down_keys: Tuple[str, ...] = ("s", "S", "↓", "j", "J")
    left_keys: Tuple[str, ...] = ("a", "A", "←", "h", "H")
    right_keys: Tuple[str, ...] = ("d", "D", "→", "l", "L")
    pause_keys: Tuple[str, ...] = (" ", "p", "P", "ESC")
    quit_keys: Tuple[str, ...] = ("q", "Q")
    replay_keys: Tuple[str, ...] = ("r", "R")
    enter_keys: Tuple[str, ...] = ("ENTER", "RETURN")


@dataclass
class InputState:
    """Represents the current state of all inputs."""
    direction: Direction = Direction.NONE
    is_pausing: bool = False
    is_quitting: bool = False
    is_replaying: bool = False
    raw_key: Optional[str] = None
    timestamp: float = field(default_factory=time.time)
    
    def reset(self) -> None:
        """Reset all input flags."""
        self.direction = Direction.NONE
        self.is_pausing = False
        self.is_quitting = False
        self.is_replaying = False
        self.raw_key = None
        self.timestamp = time.time()
    
    def is_any_direction(self) -> bool:
        """Check if any direction key was pressed."""
        return self.direction != Direction.NONE


class InputMode(Enum):
    """Input handling modes."""
    BLOCKING = auto()
    NON_BLOCKING = auto()
    EVENT = auto()


class BaseInputHandler(ABC):
    """Abstract base class for input handlers."""
    
    def __init__(self, key_mapping: Optional[KeyMapping] = None) -> None:
        """
        Initialize the input handler.
        
        Args:
            key_mapping: Custom key mapping. Uses default if None.
        """
        self.key_mapping = key_mapping if key_mapping else KeyMapping()
        self.input_state = InputState()
        self._callbacks: List[Callable[[Direction], None]] = []
        self._key_callbacks: List[Callable[[str], None]] = []
        self._enabled = True
    
    @abstractmethod
    def read_input(self, timeout: Optional[float] = None) -> Optional[str]:
        """Read input from user. Must be implemented by subclasses."""
        pass
    
    @abstractmethod
    def check_input(self) -> bool:
        """Check if input is available. Must be implemented by subclasses."""
        pass
    
    def set_input_mode(self, mode: InputMode) -> None:
        """Set the input handling mode."""
        pass
    
    def register_direction_callback(
        self,
        callback: Callable[[Direction], None]
    ) -> None:
        """
        Register a callback for direction changes.
        
        Args:
            callback: Function to call when direction changes
        """
        self._callbacks.append(callback)
    
    def register_key_callback(
        self,
        callback: Callable[[str], None]
    ) -> None:
        """
        Register a callback for key presses.
        
        Args:
            callback: Function to call when a key is pressed
        """
        self._key_callbacks.append(callback)
    
    def _invoke_callbacks(self) -> None:
        """Invoke all registered callbacks."""
        # Direction callbacks
        if self.input_state.is_any_direction():
            for callback in self._callbacks:
                try:
                    callback(self.input_state.direction)
                except Exception:
                    pass
        
        # Key callbacks
        if self.input_state.raw_key:
            for callback in self._key_callbacks:
                try:
                    callback(self.input_state.raw_key)
                except Exception:
                    pass
    
    def _get_direction_from_key(self, key: str) -> Direction:
        """
        Convert a key to a direction.
        
        Args:
            key: The key that was pressed
            
        Returns:
            Direction enum value
        """
        key_lower = key.lower()
        
        if key in self.key_mapping.up_keys:
            return Direction.UP
        elif key in self.key_mapping.down_keys:
            return Direction.DOWN
        elif key in self.key_mapping.left_keys:
            return Direction.LEFT
        elif key in self.key_mapping.right_keys:
            return Direction.RIGHT
        
        return Direction.NONE
    
    def _is_pause_key(self, key: str) -> bool:
        """Check if key is a pause key."""
        return key in self.key_mapping.pause_keys
    
    def _is_quit_key(self, key: str) -> bool:
        """Check if key is a quit key."""
        return key in self.key_mapping.quit_keys
    
    def _is_replay_key(self, key: str) -> bool:
        """Check if key is a replay key."""
        return key in self.key_mapping.replay_keys
    
    def _is_enter_key(self, key: str) -> bool:
        """Check if key is an enter key."""
        return key in self.key_mapping.enter_keys
    
    def is_enabled(self) -> bool:
        """Check if input handling is enabled."""
        return self._enabled
    
    def enable(self) -> None:
        """Enable input handling."""
        self._enabled = True
    
    def disable(self) -> None:
        """Disable input handling."""
        self._enabled = False
    
    def get_opposite_direction(self, direction: Direction) -> Direction:
        """
        Get the opposite direction.
        
        Args:
            direction: The direction to flip
            
        Returns:
            Opposite direction
        """
        opposites = {
            Direction.UP: Direction.DOWN,
            Direction.DOWN: Direction.UP,
            Direction.LEFT: Direction.RIGHT,
            Direction.RIGHT: Direction.LEFT,
            Direction.NONE: Direction.NONE,
        }
        return opposites.get(direction, Direction.NONE)


class UnixInputHandler(BaseInputHandler):
    """
    Input handler for Unix-like systems (Linux, macOS).
    
    Uses termios for non-blocking terminal input handling.
    """
    
    def __init__(self, key_mapping: Optional[KeyMapping] = None) -> None:
        """
        Initialize Unix input handler.
        
        Args:
            key_mapping: Custom key mapping
        """
        super().__init__(key_mapping)
        self._original_settings: Optional[Any] = None
        self._fd = sys.stdin.fileno()
        self._initialized = False
    
    def _initialize(self) -> None:
        """Initialize termios settings."""
        if self._initialized:
            return
        
        try:
            import termios
            import tty
            
            # Save original settings
            self._original_settings = termios.tcgetattr(self._fd)
            
            # Configure terminal for raw input
            tty.setraw(self._fd)
            
            self._initialized = True
            
        except Exception as e:
            raise InputError(f"Failed to initialize input handler: {e}")
    
    def _restore(self) -> None:
        """Restore original terminal settings."""
        if not self._initialized or self._original_settings is None:
            return
        
        try:
            import termios
            termios.tcsetattr(self._fd, termios.TCSADRAIN, self._original_settings)
            self._initialized = False
        except Exception:
            pass
    
    def read_input(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        Read a single character from input.
        
        Args:
            timeout: Timeout in seconds (None for blocking)
            
        Returns:
            Character read, or None if timeout
        """
        if not self._enabled:
            return None
        
        self._initialize()
        
        try:
            import select
            import termios
            
            if timeout is not None:
                # Non-blocking with timeout
                ready, _, _ = select.select([self._fd], [], [], timeout)
                if not ready:
                    return None
            
            # Read one character
            char = os.read(self._fd, 1).decode('utf-8', errors='ignore')
            
            # Handle escape sequences for arrow keys
            if char == '\x1b':  # Escape character
                # Try to read more (might be arrow key)
                try:
                    if timeout:
                        ready, _, _ = select.select([self._fd], [], [], 0.1)
                        if ready:
                            next_char = os.read(self._fd, 1).decode('utf-8', errors='ignore')
                            if next_char == '[':
                                third_char = os.read(self._fd, 1).decode('utf-8', errors='ignore')
                                return f'ESC[{next_char}{third_char}'
                except Exception:
                    pass
                return char
            
            return char
            
        except Exception as e:
            raise InputError(f"Error reading input: {e}")
        finally:
            if timeout is None:
                self._restore()
    
    def check_input(self) -> bool:
        """
        Check if input is available without reading.
        
        Returns:
            True if input is available
        """
        if not self._enabled:
            return False
        
        self._initialize()
        
        try:
            import select
            ready, _, _ = select.select([self._fd], [], [], 0)
            return bool(ready)
        except Exception:
            return False
        finally:
            self._restore()
    
    def set_input_mode(self, mode: InputMode) -> None:
        """Set input mode (Unix always uses non-blocking)."""
        pass
    
    def __del__(self) -> None:
        """Clean up on deletion."""
        self._restore()


class WindowsInputHandler(BaseInputHandler):
    """
    Input handler for Windows systems.
    
    Uses msvcrt for keyboard input handling.
    """
    
    def __init__(self, key_mapping: Optional[KeyMapping] = None) -> None:
        """
        Initialize Windows input handler.
        
        Args:
            key_mapping: Custom key mapping
        """
        super().__init__(key_mapping)
        self._key_mapping: Dict[int, str] = self._create_key_mapping()
    
    def _create_key_mapping(self) -> Dict[int, str]:
        """Create mapping from Windows virtual key codes to characters."""
        return {
            0x1B: "ESC",      # Escape
            0x0D: "ENTER",    # Enter
            0x20: " ",        # Space
            0x25: "↑",        # Up Arrow
            0x26: "↓",        # Down Arrow
            0x27: "←",        # Left Arrow
            0x28: "→",        # Right Arrow
            0x41: "A",        # A
            0x42: "B",
            0x43: "C",
            0x44: "D",
            0x45: "E",
            0x46: "F",
            0x47: "G",
            0x48: "H",
            0x49: "I",
            0x4A: "J",
            0x4B: "K",
            0x4C: "L",
            0x4D: "M",
            0x4E: "N",
            0x4F: "O",
            0x50: "P",
            0x51: "Q",
            0x52: "R",
            0x53: "S",
            0x54: "T",
            0x55: "U",
            0x56: "V",
            0x57: "W",
            0x58: "X",
            0x59: "Y",
            0x5A: "Z",
        }
    
    def read_input(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        Read a single character from input.
        
        Args:
            timeout: Timeout in seconds (not fully supported on Windows)
            
        Returns:
            Character read, or None if timeout
        """
        if not self._enabled:
            return None
        
        try:
            import msvcrt
            
            if timeout is not None:
                # Windows doesn't support timeout well, use polling
                start_time = time.time()
                while time.time() - start_time < timeout:
                    if msvcrt.kbhit():
                        return self._read_key()
                    time.sleep(0.01)
                return None
            
            # Blocking read
            return self._read_key()
            
        except Exception as e:
            raise InputError(f"Error reading input: {e}")
    
    def _read_key(self) -> str:
        """Read a key and convert to character."""
        import msvcrt
        
        # Check for extended key (arrow keys)
        if msvcrt.kbhit():
            first_byte = msvcrt.getwch()
            if first_byte == '\x00' or first_byte == '\xe0':
                # Extended key - read second byte
                second_byte = msvcrt.getwch()
                vk_code = ord(second_byte)
                return self._key_mapping.get(vk_code, f"VK_{vk_code:X}")
            return first_byte
        
        return ""
    
    def check_input(self) -> bool:
        """
        Check if input is available without reading.
        
        Returns:
            True if input is available
        """
        if not self._enabled:
            return False
        
        try:
            import msvcrt
            return msvcrt.kbhit()
        except Exception:
            return False
    
    def set_input_mode(self, mode: InputMode) -> None:
        """Set input mode (Windows uses kbhit for non-blocking)."""
        pass
    
    def __del__(self) -> None:
        """Clean up on deletion."""
        pass


def create_input_handler(
    platform: Optional[str] = None,
    key_mapping: Optional[KeyMapping] = None
) -> BaseInputHandler:
    """
    Factory function to create the appropriate input handler.
    
    Args:
        platform: Platform name ('windows', 'unix', or None for auto-detect)
        key_mapping: Custom key mapping
        
    Returns:
        Appropriate input handler for the platform
    """
    import sys as sys_module
    
    if platform is None:
        platform = sys_module.platform.lower()
    
    if platform.startswith("win"):
        return WindowsInputHandler(key_mapping)
    else:
        return UnixInputHandler(key_mapping)


class InputHandler:
    """
    High-level input handler that wraps platform-specific handlers.
    
    Provides a unified interface for input handling across platforms,
    with automatic key interpretation and state management.
    
    Example:
        >>> handler = InputHandler()
        >>> handler.init()
        >>> key = handler.read_input(timeout=0.1)
        >>> if key:
        ...     direction = handler.get_direction(key)
        ...     print(f"Direction: {direction}")
        >>> handler.cleanup()
    """
    
    def __init__(
        self,
        key_mapping: Optional[KeyMapping] = None,
        platform: Optional[str] = None
    ) -> None:
        """
        Initialize the input handler.
        
        Args:
            key_mapping: Custom key mapping
            platform: Platform override (None for auto-detect)
        """
        self._handler = create_input_handler(platform, key_mapping)
        self.key_mapping = self._handler.key_mapping
        self.input_state = self._handler.input_state
        self._initialized = False
    
    def init(self) -> None:
        """Initialize input handling."""
        self._handler._initialize()
        self._initialized = True
    
    def cleanup(self) -> None:
        """Clean up input handling."""
        if self._initialized:
            self._handler._restore()
            self._initialized = False
    
    def read_input(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        Read input from user.
        
        Args:
            timeout: Timeout in seconds
            
        Returns:
            Key pressed, or None if timeout
        """
        if not self._initialized:
            self.init()
        
        key = self._handler.read_input(timeout)
        
        if key:
            self._process_key(key)
        
        return key
    
    def check_input(self) -> bool:
        """
        Check if input is available.
        
        Returns:
            True if input is available
        """
        return self._handler.check_input()
    
    def _process_key(self, key: str) -> None:
        """
        Process a key and update input state.
        
        Args:
            key: The key that was pressed
        """
        # Reset state
        self.input_state.reset()
        self.input_state.raw_key = key
        
        # Check for game actions
        direction = self._handler._get_direction_from_key(key)
        if direction != Direction.NONE:
            self.input_state.direction = direction
        
        if self._handler._is_pause_key(key):
            self.input_state.is_pausing = True
        
        if self._handler._is_quit_key(key):
            self.input_state.is_quitting = True
        
        if self._handler._is_replay_key(key):
            self.input_state.is_replaying = True
        
        # Invoke callbacks
        self._handler._invoke_callbacks()
    
    def get_direction(self, key: str) -> Direction:
        """
        Get direction from a key.
        
        Args:
            key: Key to convert
            
        Returns:
            Direction enum
        """
        return self._handler._get_direction_from_key(key)
    
    def is_direction_key(self, key: str) -> bool:
        """Check if key is a direction key."""
        return self.get_direction(key) != Direction.NONE
    
    def is_pause_key(self, key: str) -> bool:
        """Check if key is a pause key."""
        return self._handler._is_pause_key(key)
    
    def is_quit_key(self, key: str) -> bool:
        """Check if key is a quit key."""
        return self._handler._is_quit_key(key)
    
    def is_replay_key(self, key: str) -> bool:
        """Check if key is a replay key."""
        return self._handler._is_replay_key(key)
    
    def is_enter_key(self, key: str) -> bool:
        """Check if key is an enter key."""
        return self._handler._is_enter_key(key)
    
    def wait_for_key(self, timeout: Optional[float] = None) -> Optional[str]:
        """
        Block until a key is pressed.
        
        Args:
            timeout: Optional timeout in seconds
            
        Returns:
            Key pressed, or None if timeout
        """
        return self.read_input(timeout)
    
    def wait_for_any_key(self) -> str:
        """
        Block until any key is pressed.
        
        Returns:
            Key pressed
        """
        while True:
            key = self.read_input()
            if key:
                return key
    
    def wait_for_keys(
        self,
        valid_keys: Set[str],
        timeout: Optional[float] = None
    ) -> Optional[str]:
        """
        Wait for one of the specified keys.
        
        Args:
            valid_keys: Set of valid keys to wait for
            timeout: Optional timeout in seconds
            
        Returns:
            Key pressed, or None if timeout
        """
        start_time = time.time()
        
        while True:
            key = self.read_input(timeout=0.1)
            
            if key:
                if key in valid_keys:
                    return key
                
                if timeout is not None:
                    if time.time() - start_time >= timeout:
                        return None
            else:
                if timeout is not None:
                    if time.time() - start_time >= timeout:
                        return None
    
    def enable(self) -> None:
        """Enable input handling."""
        self._handler.enable()
    
    def disable(self) -> None:
        """Disable input handling."""
        self._handler.disable()
    
    def is_enabled(self) -> bool:
        """Check if input handling is enabled."""
        return self._handler.is_enabled()
    
    def register_direction_callback(
        self,
        callback: Callable[[Direction], None]
    ) -> None:
        """Register a direction callback."""
        self._handler.register_direction_callback(callback)
    
    def register_key_callback(
        self,
        callback: Callable[[str], None]
    ) -> None:
        """Register a key callback."""
        self._handler.register_key_callback(callback)
    
    def reset(self) -> None:
        """Reset input state."""
        self.input_state.reset()
    
    def __enter__(self) -> "InputHandler":
        """Context manager entry."""
        self.init()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.cleanup()

---