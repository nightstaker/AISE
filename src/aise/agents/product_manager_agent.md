# Product Manager Agent

**Role:** `PRODUCT_MANAGER` | **Module:** `aise.agents.product_manager` | **Phase:** Requirements

Owns the requirements phase and requirements-document PR flow. It analyzes raw input, produces system-level artifacts and full requirement docs, and drives PR submission/review/merge for those docs.

## Skills

1. `requirement_analysis` → `REQUIREMENTS` — parse raw input into functional/non-functional/constraints
2. `system_feature_analysis` → `SYSTEM_DESIGN` — derive system-level features (SF)
3. `system_requirement_analysis` → `SYSTEM_REQUIREMENTS` — derive system-level requirements (SR)
4. `user_story_writing` → `USER_STORIES` — generate user stories with acceptance criteria
5. `product_design` → `PRD` — create product requirement document
6. `product_review` → `REVIEW_FEEDBACK` — validate PRD against requirements **(review gate, max 5 rounds)**
7. `document_generation` → `PROGRESS_REPORT` — generate `system-design.md` + `System-Requirements.md`
8. `pr_submission` → `REVIEW_FEEDBACK` — submit requirement documents as a PR
9. `pr_review` → `REVIEW_FEEDBACK` — review requirement document PR
10. `pr_merge` → `REVIEW_FEEDBACK` — merge requirement document PR

Typical execution sequence:
`requirement_analysis` → `system_feature_analysis` → `system_requirement_analysis` → `user_story_writing` → (`product_design` ↔ `product_review`, up to 5 rounds until no major issues) → `document_generation` → `pr_submission` → `pr_review` → `pr_merge`.

## Artifact Flow

**Produces:** REQUIREMENTS, SYSTEM_DESIGN, SYSTEM_REQUIREMENTS, USER_STORIES, PRD, REVIEW_FEEDBACK, PROGRESS_REPORT
**Consumes:** none externally (self-contained phase)

**Internal dependencies:**
- system_feature_analysis reads raw requirements
- system_requirement_analysis reads SYSTEM_DESIGN
- user_story_writing reads REQUIREMENTS
- product_design reads REQUIREMENTS + USER_STORIES + previous product_review feedback
- product_review reads REQUIREMENTS + current PRD
- document_generation reads SYSTEM_DESIGN + SYSTEM_REQUIREMENTS

## Downstream Handoff

- **Architect** owns `system_design`, `api_design`, and `architecture_review` tasks.
- **Project Manager** consumes REQUIREMENTS for conflict_resolution.

## Quick Reference

```python
from aise.agents.product_manager import ProductManagerAgent

pm = ProductManagerAgent(bus, store)

# First skill requires raw input
pm.execute_skill("requirement_analysis", {
    "raw_requirements": "User login\nDashboard\nPerformance < 200ms"
}, project_name="MyProject")

# Remaining skills read from artifact store
pm.execute_skill("system_feature_analysis", {"raw_requirements": "User login\nDashboard\nPerformance < 200ms"})
pm.execute_skill("system_requirement_analysis", {}, project_name="MyProject")
pm.execute_skill("user_story_writing", {}, project_name="MyProject")
# Loop design/review up to 5 rounds until no major issues
pm.execute_skill("product_design", {"iteration": 1}, project_name="MyProject")
pm.execute_skill("product_review", {"iteration": 1}, project_name="MyProject")
pm.execute_skill("document_generation", {"output_dir": "."}, project_name="MyProject")
pm.execute_skill(
    "pr_submission",
    {
        "title": "docs: requirements package",
        "body": "Submit system requirement docs.",
        "head": "docs/requirements-package",
        "base": "main",
    },
    project_name="MyProject",
)
pm.execute_skill("pr_review", {"pr_number": 42, "feedback": "LGTM", "event": "APPROVE"}, project_name="MyProject")
pm.execute_skill("pr_merge", {"pr_number": 42, "merge_method": "squash"}, project_name="MyProject")
```
