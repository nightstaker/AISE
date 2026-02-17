"""All agent skills."""

from .architect import (
    APIDesignSkill,
    ArchitectureDocumentGenerationSkill,
    ArchitectureRequirementSkill,
    ArchitectureReviewSkill,
    FunctionalDesignSkill,
    StatusTrackingSkill,
    SystemDesignSkill,
    TechStackSelectionSkill,
)
from .developer import (
    BugFixSkill,
    CodeGenerationSkill,
    CodeReviewSkill,
    TDDSessionSkill,
    UnitTestWritingSkill,
)
from .github import (
    PRMergeSkill,
    PRReviewSkill,
)
from .lead import (
    ConflictResolutionSkill,
    ProgressTrackingSkill,
    TeamHealthSkill,
    VersionReleaseSkill,
)
from .manager import (
    RequirementDistributionSkill,
    TeamFormationSkill,
)
from .pm import (
    DocumentGenerationSkill,
    ProductDesignSkill,
    ProductReviewSkill,
    RequirementAnalysisSkill,
    SystemFeatureAnalysisSkill,
    SystemRequirementAnalysisSkill,
    UserStoryWritingSkill,
)
from .qa import (
    TestAutomationSkill,
    TestCaseDesignSkill,
    TestPlanDesignSkill,
    TestReviewSkill,
)

__all__ = [
    # PM
    "RequirementAnalysisSkill",
    "UserStoryWritingSkill",
    "ProductDesignSkill",
    "ProductReviewSkill",
    "SystemFeatureAnalysisSkill",
    "SystemRequirementAnalysisSkill",
    "DocumentGenerationSkill",
    # Architect
    "SystemDesignSkill",
    "APIDesignSkill",
    "ArchitectureReviewSkill",
    "TechStackSelectionSkill",
    "ArchitectureRequirementSkill",
    "FunctionalDesignSkill",
    "StatusTrackingSkill",
    "ArchitectureDocumentGenerationSkill",
    # Developer
    "CodeGenerationSkill",
    "UnitTestWritingSkill",
    "CodeReviewSkill",
    "BugFixSkill",
    "TDDSessionSkill",
    # QA
    "TestPlanDesignSkill",
    "TestCaseDesignSkill",
    "TestAutomationSkill",
    "TestReviewSkill",
    # Project Manager
    "ConflictResolutionSkill",
    "ProgressTrackingSkill",
    "VersionReleaseSkill",
    "TeamHealthSkill",
    # RD Director
    "TeamFormationSkill",
    "RequirementDistributionSkill",
    # GitHub
    "PRReviewSkill",
    "PRMergeSkill",
]
