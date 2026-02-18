# Product Manager Agent

**Role:** `PRODUCT_MANAGER` | **Module:** `aise.agents.product_manager` | **Phase:** Requirements

Owns the requirements phase. Analyzes raw user input into structured requirements, generates user stories, produces PRDs, and validates deliverables.

## Skills

1. `requirement_analysis` → `REQUIREMENTS` — parse raw input into functional/non-functional/constraints
2. `user_story_writing` → `USER_STORIES` — generate user stories with acceptance criteria
3. `product_design` → `PRD` — create product requirement document
4. `product_review` → `REVIEW_FEEDBACK` — validate PRD against requirements **(review gate)**

Skills execute in order 1→2→3→4. Skill 4 is the review gate that approves/rejects the PRD.

## Artifact Flow

**Produces:** REQUIREMENTS, USER_STORIES, PRD, REVIEW_FEEDBACK
**Consumes:** none externally (self-contained phase)

**Internal dependencies:**
- user_story_writing reads REQUIREMENTS
- product_design reads REQUIREMENTS + USER_STORIES
- product_review reads REQUIREMENTS + PRD

## Downstream Handoff

- **Architect** consumes REQUIREMENTS and PRD for system_design
- **Project Manager** consumes REQUIREMENTS for conflict_resolution

## Quick Reference

```python
from aise.agents.product_manager import ProductManagerAgent

pm = ProductManagerAgent(bus, store)

# First skill requires raw input
pm.execute_skill("requirement_analysis", {
    "raw_requirements": "User login\nDashboard\nPerformance < 200ms"
}, project_name="MyProject")

# Remaining skills read from artifact store
pm.execute_skill("user_story_writing", {}, project_name="MyProject")
pm.execute_skill("product_design", {}, project_name="MyProject")
pm.execute_skill("product_review", {}, project_name="MyProject")
```
