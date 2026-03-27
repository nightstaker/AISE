"""
Score Repository Module

A repository pattern implementation for managing high scores in the Snake game.
Supports persistent storage, filtering by game mode, and thread-safe operations.
"""

from __future__ import annotations
from dataclasses import dataclass, field, asdict
from typing import Optional
from pathlib import Path
import json
import threading
from datetime import datetime
import logging

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class GameScore:
    """Represents a high score entry."""
    
    player_name: str
    score: int
    game_mode: str = "classic"
    date_achieved: str = field(default_factory=lambda: datetime.now().isoformat())
    length: int = 0  # Snake length at time of death
    speed_level: int = 1  # Game speed level
    
    def to_dict(self) -> dict:
        """Convert score to dictionary for serialization."""
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> GameScore:
        """Create a GameScore from a dictionary."""
        return cls(
            player_name=data.get("player_name", "Unknown"),
            score=data.get("score", 0),
            game_mode=data.get("game_mode", "classic"),
            date_achieved=data.get("date_achieved", datetime.now().isoformat()),
            length=data.get("length", 0),
            speed_level=data.get("speed_level", 1)
        )
    
    def __lt__(self, other: GameScore) -> bool:
        """Enable sorting by score (descending)."""
        return self.score > other.score


@dataclass
class ScoreRepositoryConfig:
    """Configuration for the ScoreRepository."""
    
    file_path: Path = field(default_factory=lambda: Path("data/high_scores.json"))
    max_scores_per_mode: int = 100
    auto_cleanup: bool = True
    backup_on_write: bool = True


class ScoreRepository:
    """
    Repository for managing Snake game high scores.
    
    Provides thread-safe access to high scores with support for:
    - Multiple game modes
    - Persistent JSON storage
    - Sorted retrieval
    - Score validation
    """
    
    def __init__(self, config: Optional[ScoreRepositoryConfig] = None):
        """
        Initialize the score repository.
        
        Args:
            config: Optional configuration object. Uses defaults if not provided.
        """
        self.config = config or ScoreRepositoryConfig()
        self._scores: dict[str, list[GameScore]] = {}
        self._lock = threading.RLock()
        self._initialized = False
        
        # Ensure data directory exists
        self.config.file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Load existing scores
        self._load_scores()
        self._initialized = True
    
    def _load_scores(self) -> None:
        """Load scores from the JSON file."""
        try:
            if self.config.file_path.exists():
                with open(self.config.file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for mode, score_dicts in data.items():
                        self._scores[mode] = [
                            GameScore.from_dict(s) for s in score_dicts
                        ]
                logger.info(f"Loaded {sum(len(s) for s in self._scores.values())} scores from {self.config.file_path}")
            else:
                logger.debug("No existing scores file found, starting fresh")
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse scores file: {e}")
            self._scores = {}
        except Exception as e:
            logger.error(f"Error loading scores: {e}")
            self._scores = {}
    
    def _save_scores(self) -> bool:
        """Save scores to the JSON file."""
        try:
            # Sort scores before saving (highest first)
            for mode in self._scores:
                self._scores[mode].sort(key=lambda s: s.score, reverse=True)
            
            data = {mode: [s.to_dict() for s in scores] for mode, scores in self._scores.items()}
            
            # Create backup if enabled
            if self.config.backup_on_write and self.config.file_path.exists():
                backup_path = self.config.file_path.with_suffix(".json.bak")
                with open(self.config.file_path, "r", encoding="utf-8") as src:
                    with open(backup_path, "w", encoding="utf-8") as dst:
                        dst.write(src.read())
            
            # Write to file atomically (write to temp, then rename)
            temp_path = self.config.file_path.with_suffix(".json.tmp")
            with open(temp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            
            temp_path.rename(self.config.file_path)
            return True
            
        except Exception as e:
            logger.error(f"Failed to save scores: {e}")
            return False
    
    def add_score(self, score: GameScore) -> bool:
        """
        Add a new high score.
        
        Args:
            score: The GameScore to add.
            
        Returns:
            True if the score was added successfully, False otherwise.
        """
        with self._lock:
            if not score.player_name or not score.player_name.strip():
                score.player_name = "Anonymous"
            
            if score.score < 0:
                logger.warning("Attempted to add negative score, rejecting")
                return False
            
            mode = score.game_mode
            if mode not in self._scores:
                self._scores[mode] = []
            
            # Check if score qualifies for leaderboard
            current_scores = self._scores[mode]
            if self.config.auto_cleanup:
                # Only add if score is better than lowest in list
                if len(current_scores) >= self.config.max_scores_per_mode:
                    min_score = current_scores[-1].score
                    if score.score <= min_score:
                        logger.debug(f"Score {score.score} doesn't qualify for leaderboard (min: {min_score})")
                        return False
                else:
                    current_scores.append(score)
            
            self._scores[mode].append(score)
            self._save_scores()
            logger.info(f"Added score: {score.player_name} - {score.score} ({mode})")
            return True
    
    def get_top_scores(self, limit: int = 10, mode: str = "classic") -> list[GameScore]:
        """
        Get the top N scores for a game mode.
        
        Args:
            limit: Maximum number of scores to return.
            mode: Game mode to filter by.
            
        Returns:
            List of top scores, sorted by score descending.
        """
        with self._lock:
            scores = self._scores.get(mode, []).copy()
            scores.sort(key=lambda s: s.score, reverse=True)
            return scores[:limit]
    
    def get_all_scores(self, mode: str = "classic") -> list[GameScore]:
        """
        Get all scores for a game mode.
        
        Args:
            mode: Game mode to filter by.
            
        Returns:
            List of all scores for the mode.
        """
        with self._lock:
            return self._scores.get(mode, []).copy()
    
    def get_score_by_player(self, player_name: str, mode: str = "classic") -> Optional[GameScore]:
        """
        Find a player's best score for a game mode.
        
        Args:
            player_name: The player's name to search for.
            mode: Game mode to filter by.
            
        Returns:
            The player's best score, or None if not found.
        """
        with self._lock:
            scores = self._scores.get(mode, [])
            matching = [s for s in scores if s.player_name.lower() == player_name.lower()]
            if matching:
                return max(matching, key=lambda s: s.score)
            return None
    
    def delete_score(self, player_name: str, mode: str = "classic") -> bool:
        """
        Delete all scores for a specific player.
        
        Args:
            player_name: The player's name.
            mode: Game mode to filter by.
            
        Returns:
            True if any scores were deleted, False otherwise.
        """
        with self._lock:
            if mode not in self._scores:
                return False
            
            original_len = len(self._scores[mode])
            self._scores[mode] = [
                s for s in self._scores[mode] 
                if s.player_name.lower() != player_name.lower()
            ]
            
            deleted = original_len - len(self._scores[mode])
            if deleted > 0:
                self._save_scores()
                logger.info(f"Deleted {deleted} score(s) for player: {player_name}")
            
            return deleted > 0
    
    def clear_scores(self, mode: Optional[str] = None) -> int:
        """
        Clear high scores.
        
        Args:
            mode: Specific mode to clear. If None, clears all modes.
            
        Returns:
            Number of scores cleared.
        """
        with self._lock:
            if mode:
                if mode in self._scores:
                    count = len(self._scores[mode])
                    self._scores[mode] = []
                    self._save_scores()
                    return count
                return 0
            else:
                total = sum(len(scores) for scores in self._scores.values())
                self._scores.clear()
                self._save_scores()
                return total
    
    def get_game_modes(self) -> list[str]:
        """
        Get list of all game modes that have scores.
        
        Returns:
            List of game mode names.
        """
        with self._lock:
            return list(self._scores.keys())
    
    def get_stats(self) -> dict:
        """
        Get statistics about the stored scores.
        
        Returns:
            Dictionary containing score statistics.
        """
        with self._lock:
            total_scores = sum(len(scores) for scores in self._scores.values())
            modes = {
                mode: {
                    "count": len(scores),
                    "highest": max((s.score for s in scores), default=0),
                    "average": sum(s.score for s in scores) / len(scores) if scores else 0,
                }
                for mode, scores in self._scores.items()
            }
            
            return {
                "total_scores": total_scores,
                "modes": modes,
                "file_path": str(self.config.file_path),
            }
    
    def validate_and_fix(self) -> dict:
        """
        Validate and fix any corrupted data in the repository.
        
        Returns:
            Dictionary describing validation results.
        """
        with self._lock:
            issues = []
            fixed = 0
            
            for mode, scores in self._scores.items():
                valid_scores = []
                for score in scores:
                    # Validate score fields
                    if not score.player_name:
                        score.player_name = "Unknown"
                    if score.score < 0:
                        issues.append(f"Negative score found and removed: {score}")
                        continue
                    if not score.game_mode:
                        score.game_mode = "classic"
                    valid_scores.append(score)
                
                if len(valid_scores) != len(scores):
                    fixed += len(scores) - len(valid_scores)
                    self._scores[mode] = valid_scores
            
            if fixed > 0:
                self._save_scores()
            
            return {
                "issues_found": len(issues),
                "scores_fixed": fixed,
                "issues": issues,
            }


# Singleton instance for convenience
_default_repository: Optional[ScoreRepository] = None


def get_repository(config: Optional[ScoreRepositoryConfig] = None) -> ScoreRepository:
    """
    Get or create the default score repository instance.
    
    Args:
        config: Optional configuration for a new repository.
        
    Returns:
        The default ScoreRepository instance.
    """
    global _default_repository
    if _default_repository is None or config is not None:
        _default_repository = ScoreRepository(config)
    return _default_repository
