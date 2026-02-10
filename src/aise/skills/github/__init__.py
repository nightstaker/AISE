"""GitHub integration skills."""

from .pr_merge import PRMergeSkill
from .pr_review import PRReviewSkill

__all__ = [
    "PRMergeSkill",
    "PRReviewSkill",
]
