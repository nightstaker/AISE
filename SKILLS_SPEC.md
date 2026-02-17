# Skills Specification

Machine-readable registry of all skills in the AISE multi-agent system. This file serves as the single source of truth for skill discovery, routing, and dependency resolution.

## Skill Index

| ID | Skill Name | Agent | Phase | Class | Module |
|----|-----------|-------|-------|-------|--------|
| SK-01 | `requirement_analysis` | product_manager | requirements | `RequirementAnalysisSkill` | `aise.skills.pm.requirement_analysis` |
| SK-02 | `user_story_writing` | product_manager | requirements | `UserStoryWritingSkill` | `aise.skills.pm.user_story_writing` |
| SK-03 | `product_design` | product_manager | requirements | `ProductDesignSkill` | `aise.skills.pm.product_design` |
| SK-04 | `product_review` | product_manager | requirements | `ProductReviewSkill` | `aise.skills.pm.product_review` |
| SK-05 | `system_design` | architect | design | `SystemDesignSkill` | `aise.skills.architect.system_design` |
| SK-06 | `api_design` | architect | design | `APIDesignSkill` | `aise.skills.architect.api_design` |
| SK-07 | `tech_stack_selection` | architect | design | `TechStackSelectionSkill` | `aise.skills.architect.tech_stack_selection` |
| SK-08 | `architecture_review` | architect | design | `ArchitectureReviewSkill` | `aise.skills.architect.architecture_review` |
| SK-09 | `code_generation` | developer | implementation | `CodeGenerationSkill` | `aise.skills.developer.code_generation` |
| SK-10 | `unit_test_writing` | developer | implementation | `UnitTestWritingSkill` | `aise.skills.developer.unit_test_writing` |
| SK-11 | `code_review` | developer | implementation | `CodeReviewSkill` | `aise.skills.developer.code_review` |
| SK-12 | `bug_fix` | developer | implementation | `BugFixSkill` | `aise.skills.developer.bug_fix` |
| SK-13 | `test_plan_design` | qa_engineer | testing | `TestPlanDesignSkill` | `aise.skills.qa.test_plan_design` |
| SK-14 | `test_case_design` | qa_engineer | testing | `TestCaseDesignSkill` | `aise.skills.qa.test_case_design` |
| SK-15 | `test_automation` | qa_engineer | testing | `TestAutomationSkill` | `aise.skills.qa.test_automation` |
| SK-16 | `test_review` | qa_engineer | testing | `TestReviewSkill` | `aise.skills.qa.test_review` |
| SK-17 | `conflict_resolution` | project_manager | cross-cutting | `ConflictResolutionSkill` | `aise.skills.lead.conflict_resolution` |
| SK-18 | `progress_tracking` | project_manager | cross-cutting | `ProgressTrackingSkill` | `aise.skills.lead.progress_tracking` |
| SK-19 | `version_release` | project_manager | cross-cutting | `VersionReleaseSkill` | `aise.skills.lead.version_release` |
| SK-20 | `team_health` | project_manager | cross-cutting | `TeamHealthSkill` | `aise.skills.lead.team_health` |
| SK-21 | `team_formation` | rd_director | setup | `TeamFormationSkill` | `aise.skills.manager.team_formation` |
| SK-22 | `requirement_distribution` | rd_director | setup | `RequirementDistributionSkill` | `aise.skills.manager.requirement_distribution` |

## Artifact Types

| Type | Enum Value | Primary Producer | Consumers |
|------|-----------|------------------|-----------|
| `REQUIREMENTS` | `requirements` | requirement_analysis, requirement_distribution | user_story_writing, product_design, product_review, system_design, tech_stack_selection, conflict_resolution |
| `USER_STORIES` | `user_stories` | user_story_writing | product_design |
| `PRD` | `prd` | product_design | product_review, system_design |
| `ARCHITECTURE_DESIGN` | `architecture_design` | system_design | api_design, tech_stack_selection, architecture_review, code_generation, test_plan_design, test_case_design |
| `API_CONTRACT` | `api_contract` | api_design | architecture_review, code_generation, test_plan_design, test_case_design, test_review |
| `TECH_STACK` | `tech_stack` | tech_stack_selection | architecture_review, code_generation, test_automation |
| `SOURCE_CODE` | `source_code` | code_generation | unit_test_writing, code_review, bug_fix, architecture_review |
| `UNIT_TESTS` | `unit_tests` | unit_test_writing | code_review, test_review |
| `REVIEW_FEEDBACK` | `review_feedback` | product_review, architecture_review, code_review, test_review, conflict_resolution | orchestrator |
| `TEST_PLAN` | `test_plan` | test_plan_design | test_review |
| `TEST_CASES` | `test_cases` | test_case_design | test_automation, test_review |
| `AUTOMATED_TESTS` | `automated_tests` | test_automation | test_review |
| `BUG_REPORT` | `bug_report` | bug_fix | — |
| `PROGRESS_REPORT` | `progress_report` | progress_tracking, version_release, team_health, team_formation | — |

## Dependency Graph

Execution order derived from artifact dependencies. Skills can only run after their upstream dependencies have produced artifacts.

```
team_formation                (no dependencies — setup entry point, rd_director)
requirement_distribution      (no dependencies — setup entry point, rd_director)

requirement_analysis          (no dependencies — delivery entry point)
  ├─► user_story_writing      (requires: REQUIREMENTS)
  ├─► product_design          (requires: REQUIREMENTS, USER_STORIES)
  │     └─► product_review    (requires: REQUIREMENTS, PRD) [review gate]
  ├─► system_design           (requires: REQUIREMENTS, PRD)
  │     ├─► api_design        (requires: ARCHITECTURE_DESIGN)
  │     └─► tech_stack_selection (requires: REQUIREMENTS, ARCHITECTURE_DESIGN)
  │           └─► architecture_review (requires: ARCHITECTURE_DESIGN, API_CONTRACT, TECH_STACK) [review gate]
  └─► code_generation         (requires: ARCHITECTURE_DESIGN, API_CONTRACT, TECH_STACK)
        ├─► unit_test_writing (requires: SOURCE_CODE)
        │     └─► code_review (requires: SOURCE_CODE, UNIT_TESTS) [review gate]
        └─► bug_fix           (requires: SOURCE_CODE) [on-demand]

test_plan_design              (requires: ARCHITECTURE_DESIGN, API_CONTRACT)
  └─► test_case_design        (requires: ARCHITECTURE_DESIGN, API_CONTRACT)
        └─► test_automation   (requires: TEST_CASES, TECH_STACK)
              └─► test_review (requires: TEST_PLAN, TEST_CASES, AUTOMATED_TESTS, API_CONTRACT, UNIT_TESTS) [review gate]

conflict_resolution           (requires: REQUIREMENTS — on-demand, project_manager)
progress_tracking             (reads all artifact types — on-demand, project_manager)
version_release               (requires: REQUIREMENTS, ARCHITECTURE_DESIGN, SOURCE_CODE, UNIT_TESTS — on-demand, project_manager)
team_health                   (cross-cutting, no hard dependencies — project_manager)
```

## Workflow Phases

### Phase 0: Setup (RD Director)
| Order | Skill | Agent |
|-------|-------|-------|
| 1 | `team_formation` | rd_director |
| 2 | `requirement_distribution` | rd_director |

### Phase 1: Requirements
| Order | Skill | Review Gate |
|-------|-------|-------------|
| 1 | `requirement_analysis` | — |
| 2 | `user_story_writing` | — |
| 3 | `product_design` | — |
| 4 | `product_review` | Validates PRD against REQUIREMENTS |

### Phase 2: Design
| Order | Skill | Review Gate |
|-------|-------|-------------|
| 1 | `system_design` | — |
| 2 | `api_design` | — |
| 3 | `tech_stack_selection` | — |
| 4 | `architecture_review` | Validates ARCHITECTURE_DESIGN completeness |

### Phase 3: Implementation
| Order | Skill | Review Gate |
|-------|-------|-------------|
| 1 | `code_generation` | — |
| 2 | `unit_test_writing` | — |
| 3 | `code_review` | Validates SOURCE_CODE quality |
| 4 | `bug_fix` | On-demand loop |

### Phase 4: Testing
| Order | Skill | Review Gate |
|-------|-------|-------------|
| 1 | `test_plan_design` | — |
| 2 | `test_case_design` | — |
| 3 | `test_automation` | — |
| 4 | `test_review` | Validates coverage ≥70%, automation ≥60% |

## Skill Details

### SK-01: requirement_analysis

- **Input:** `{ "raw_requirements": str | list }` — raw text or list of requirement strings
- **Output artifact:** `REQUIREMENTS` — structured functional/non-functional/constraints
- **Classification rules:** NFR keywords: `performance`, `security`, `scalab`, `reliab`, `maintain`; constraint keywords: `constraint`, `must use`, `limited to`, `budget`, `deadline`; all others → functional
- **Validation:** `raw_requirements` must be present and non-empty
- **Dependencies:** none (entry point)

### SK-02: user_story_writing

- **Input:** `{}` — reads REQUIREMENTS from artifact store
- **Output artifact:** `USER_STORIES` — user stories with acceptance criteria
- **Format:** `As a [user], I want [goal], so that [benefit]` + acceptance criteria list
- **Dependencies:** requirement_analysis

### SK-03: product_design

- **Input:** `{}` — reads REQUIREMENTS, USER_STORIES from artifact store
- **Output artifact:** `PRD` — product requirement document with features, user flows, priorities
- **Dependencies:** requirement_analysis, user_story_writing

### SK-04: product_review

- **Input:** `{}` — reads REQUIREMENTS, PRD from artifact store
- **Output artifact:** `REVIEW_FEEDBACK` — approval/rejection with coverage analysis
- **Review gate:** Sets PRD status to APPROVED or REJECTED
- **Dependencies:** requirement_analysis, product_design

### SK-05: system_design

- **Input:** `{}` — reads PRD, REQUIREMENTS from artifact store
- **Output artifact:** `ARCHITECTURE_DESIGN` — components, data flows, deployment strategy
- **Dependencies:** product_design

### SK-06: api_design

- **Input:** `{}` — reads ARCHITECTURE_DESIGN from artifact store
- **Output artifact:** `API_CONTRACT` — OpenAPI-style endpoints and schemas
- **Dependencies:** system_design

### SK-07: tech_stack_selection

- **Input:** `{}` — reads REQUIREMENTS, ARCHITECTURE_DESIGN from artifact store
- **Output artifact:** `TECH_STACK` — technology choices with justifications
- **Dependencies:** system_design

### SK-08: architecture_review

- **Input:** `{}` — reads ARCHITECTURE_DESIGN, API_CONTRACT, TECH_STACK, SOURCE_CODE from artifact store
- **Output artifact:** `REVIEW_FEEDBACK` — architecture validation results
- **Review gate:** Sets ARCHITECTURE_DESIGN status to APPROVED or REJECTED
- **Dependencies:** system_design, api_design, tech_stack_selection

### SK-09: code_generation

- **Input:** `{}` — reads ARCHITECTURE_DESIGN, API_CONTRACT, TECH_STACK from artifact store
- **Output artifact:** `SOURCE_CODE` — module files (models, routes, services)
- **Supports:** Python/FastAPI, Go/Gin
- **Dependencies:** system_design, api_design, tech_stack_selection

### SK-10: unit_test_writing

- **Input:** `{}` — reads SOURCE_CODE from artifact store
- **Output artifact:** `UNIT_TESTS` — test suites per module
- **Dependencies:** code_generation

### SK-11: code_review

- **Input:** `{}` — reads SOURCE_CODE, UNIT_TESTS from artifact store
- **Output artifact:** `REVIEW_FEEDBACK` — code quality review results
- **Review gate:** Sets SOURCE_CODE status to APPROVED or REJECTED
- **Checks:** security, style, test coverage
- **Dependencies:** code_generation, unit_test_writing

### SK-12: bug_fix

- **Input:** `{ "bug_reports": [{ "id": str, "description": str }] }` — bug reports to fix
- **Output artifact:** `BUG_REPORT` — fix records with root cause analysis
- **Trigger:** On-demand (not part of standard phase flow)
- **Dependencies:** code_generation

### SK-13: test_plan_design

- **Input:** `{}` — reads ARCHITECTURE_DESIGN, API_CONTRACT from artifact store
- **Output artifact:** `TEST_PLAN` — testing scope, strategy, risks, subsystem plans
- **Dependencies:** system_design, api_design

### SK-14: test_case_design

- **Input:** `{}` — reads ARCHITECTURE_DESIGN, API_CONTRACT from artifact store
- **Output artifact:** `TEST_CASES` — detailed test cases with preconditions and expected results
- **Dependencies:** system_design, api_design

### SK-15: test_automation

- **Input:** `{}` — reads TEST_CASES, TECH_STACK from artifact store
- **Output artifact:** `AUTOMATED_TESTS` — pytest scripts, conftest, configuration
- **Dependencies:** test_case_design, tech_stack_selection

### SK-16: test_review

- **Input:** `{}` — reads TEST_PLAN, TEST_CASES, AUTOMATED_TESTS, API_CONTRACT, UNIT_TESTS from artifact store
- **Output artifact:** `REVIEW_FEEDBACK` — test quality review with coverage metrics
- **Review gate:** Sets AUTOMATED_TESTS status to APPROVED or REJECTED
- **Thresholds:** endpoint coverage ≥70%, automation rate ≥60%
- **Dependencies:** test_plan_design, test_case_design, test_automation

### SK-17: conflict_resolution

- **Input:** `{ "conflicts": [{ "parties": [str], "issue": str, "options": [str] }] }`
- **Output artifact:** `REVIEW_FEEDBACK` — resolutions with rationale
- **Heuristics:** NFR-aligned (performance, security); falls back to first option
- **Dependencies:** reads REQUIREMENTS (on-demand)

### SK-18: progress_tracking

- **Input:** `{}` — reads all artifact types from store
- **Output artifact:** `PROGRESS_REPORT` — phase completion and artifact status report
- **Metrics:** per-phase completion %, overall progress, review feedback summary
- **Dependencies:** none (reads whatever is available)

### SK-19: version_release

- **Input:** `{ "version": str, "release_notes": str (optional), "release_type": str (optional) }`
- **Output artifact:** `PROGRESS_REPORT` — release record with readiness checks and blockers
- **Readiness checks:** REQUIREMENTS, ARCHITECTURE_DESIGN, SOURCE_CODE, UNIT_TESTS must all exist
- **Validation:** `version` is required
- **Trigger:** On-demand (project_manager calls when ready to cut a release)
- **Dependencies:** requires core delivery artifacts to be present

### SK-20: team_health

- **Input:** `{ "agent_statuses": dict (optional), "blocked_tasks": [str] (optional), "overdue_tasks": [str] (optional) }`
- **Output artifact:** `PROGRESS_REPORT` — health score, risk factors, and recommendations
- **Health score:** 100 − (blocked_tasks × 10) − (overdue_tasks × 5), capped at 0
- **Status thresholds:** healthy ≥ 70, at_risk ≥ 40, critical < 40
- **Trigger:** On-demand or periodic (project_manager)
- **Dependencies:** none (reads artifact store for context)

### SK-21: team_formation

- **Input:** `{ "roles": { role_name: { "count": int, "model": str, "provider": str, "enabled": bool } }, "development_mode": "local"|"github" }`
- **Output artifact:** `PROGRESS_REPORT` — team roster with agent names and model assignments
- **Validation:** `roles` must be non-empty; `development_mode` must be `"local"` or `"github"`
- **Trigger:** Once at project start (rd_director)
- **Dependencies:** none (setup entry point)

### SK-22: requirement_distribution

- **Input:** `{ "product_requirements": str | [str], "architecture_requirements": str | [str] (optional), "recipients": [str] (optional) }`
- **Output artifact:** `REQUIREMENTS` — structured distribution record with functional and architecture requirements
- **Validation:** `product_requirements` must be non-empty
- **Trigger:** Once at project start after team_formation (rd_director)
- **Dependencies:** team_formation (logical; no hard artifact dependency)

## Routing Rules

Given a task description, use these rules to select the correct agent and skill:

| Intent | Agent | Skill |
|--------|-------|-------|
| Form the project team (roles, counts, models) | rd_director | team_formation |
| Distribute initial requirements to the team | rd_director | requirement_distribution |
| Parse/analyze requirements from raw input | product_manager | requirement_analysis |
| Write user stories with acceptance criteria | product_manager | user_story_writing |
| Create product requirement document (PRD) | product_manager | product_design |
| Validate PRD against requirements | product_manager | product_review |
| Design system architecture | architect | system_design |
| Design API endpoints and contracts | architect | api_design |
| Select technology stack | architect | tech_stack_selection |
| Validate architecture completeness | architect | architecture_review |
| Generate source code from design | developer | code_generation |
| Write unit tests for code | developer | unit_test_writing |
| Review code quality | developer | code_review |
| Fix bugs from reports or failing tests | developer | bug_fix |
| Create test plan with strategy | qa_engineer | test_plan_design |
| Design detailed test cases | qa_engineer | test_case_design |
| Generate automated test scripts | qa_engineer | test_automation |
| Review test coverage and quality | qa_engineer | test_review |
| Resolve inter-agent conflicts | project_manager | conflict_resolution |
| Report project progress | project_manager | progress_tracking |
| Cut a version release | project_manager | version_release |
| Assess team health and flag risks | project_manager | team_health |

## Review Gates Summary

| Phase | Reviewer | Skill | Target Artifact | Min Review Rounds | Max Iterations | Requires Tests Pass |
|-------|----------|-------|-----------------|-------------------|----------------|---------------------|
| requirements | product_manager | product_review | PRD | 1 | 3 | No |
| design | architect | architecture_review | ARCHITECTURE_DESIGN | 3 | 3 | No |
| implementation | developer | code_review | SOURCE_CODE | 3 | 3 | Yes |
| testing | qa_engineer | test_review | AUTOMATED_TESTS | 1 | 3 | No |

**Notes:**
- **Min Review Rounds**: The minimum number of review iterations that must occur between the design/implementation work and the review gate approval. Design and Implementation phases require at least 3 rounds.
- **Requires Tests Pass**: When set, all unit tests must pass before the review gate is reached. This ensures no PR is submitted with failing tests.
