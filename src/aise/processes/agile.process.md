---
process_id: agile_sprint_v1
name: Iterative Agile Sprint Workflow
work_type: rapid_iteration
keywords: agile, sprint, backlog, mvp, feedback, iterative
summary: An iterative approach centered on sprint planning, rapid prototyping, continuous review, and retrospective. Produces a working MVP each sprint.
caps:
  max_dispatches: 30
  max_continuations: 15
terminal_step: deliver_report
required_phases:
  - phase_sprint_planning
  - phase_sprint_execution
  - phase_sprint_review
  - phase_sprint_retrospective
  - phase_delivery
---

# Agile Iterative Development Process

<!-- Legacy bullet metadata duplicated from the YAML frontmatter above so
     the older aise.core.process_md_repository parser still loads this
     process. The new runtime parser reads the frontmatter directly. -->
- process_id: agile_sprint_v1
- name: Iterative Agile Sprint Workflow
- work_type: rapid_iteration
- keywords: agile, sprint, backlog, mvp, feedback, iterative
- summary: An iterative approach centered on sprint planning, rapid prototyping, continuous review, and retrospective. Produces a working MVP each sprint.

## Steps

### phase_sprint_planning: Sprint Planning
#### step_backlog_and_stories: Backlog & User Stories
- agents: product_manager
- description: Read the raw requirement. Produce docs/product_backlog.md — list user stories (As a …, I want …, So that …) with acceptance criteria and Definition of Done (DoD). Highlight the MVP scope for the first sprint. Each user story MUST carry a Mermaid use case diagram.
- deliverables: docs/product_backlog.md

### phase_sprint_execution: Sprint Execution
#### step_sprint_design: Lightweight Sprint Design
- agents: architect
- description: Read docs/product_backlog.md. Produce docs/sprint_design.md — a LIGHTWEIGHT technical design (modules, public interfaces, data flow). Prefer simplicity over completeness; this is a sprint, not a long-design phase. Use Mermaid (C4Context, C4Container) for architecture diagrams.
- deliverables: docs/sprint_design.md

#### step_sprint_implementation: Rapid Prototyping & TDD
- agents: developer
- description: |
    Dispatch developer per MVP module. Each task writes
    tests/test_<module>.py, then src/<module>.py, then runs ONLY that
    module's test file. Keep modules small and focused on shipping the
    MVP, not on finishing every backlog item.
- deliverables: src/, tests/
- verification_command: python -m pytest tests/ -q --tb=short
- on_failure: retry_with_output
- max_retries: 2

#### step_sprint_main_entry: Working Entry Point
- agents: developer
- description: Wire all sprint modules into a runnable entry file so the MVP can be demoed at review.
- deliverables: src/main.py

### phase_sprint_review: Sprint Review & Demo
#### step_sprint_integration: Integration + Demo Test
- agents: qa_engineer
- description: Run the FULL pytest suite. Verify each user story's acceptance criteria against real output. Summarize pass/fail per story in tests/test_integration.py + docs/sprint_review.md.
- deliverables: tests/test_integration.py, docs/sprint_review.md
- verification_command: python -m pytest tests/ -q --tb=short
- on_failure: retry_with_output
- max_retries: 2

### phase_sprint_retrospective: Sprint Retrospective
#### step_retrospective: Process Optimization
- agents: project_manager
- description: Produce docs/sprint_retrospective.md — what went well, what did not, efficiency bottlenecks (which agents stalled, which dispatches needed retries). Feed the outcome into the next sprint's backlog.
- deliverables: docs/sprint_retrospective.md

### phase_delivery: Sprint Delivery
#### deliver_report: MVP Delivery Report
- agents: product_manager
- description: Compose docs/delivery_report.md — MVP summary, user stories shipped vs deferred, implementation / test metrics, retrospective highlights. End with mark_complete.
- deliverables: docs/delivery_report.md
