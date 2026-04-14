---
process_id: waterfall_standard_v1
name: Sequential Waterfall Lifecycle
work_type: structured_development
keywords: waterfall, sequential, design-first, documentation, milestone
summary: A linear and sequential approach to software development where each phase must be completed before the next begins. Default choice for most structured projects.
caps:
  max_dispatches: 30
  max_continuations: 15
terminal_step: deliver_report
required_phases:
  - phase_1_requirement
  - phase_2_design
  - phase_3_implementation
  - phase_4_verification
  - phase_5_delivery
---

# Waterfall Software Development Process

<!-- Legacy bullet metadata duplicated from the YAML frontmatter above so
     the older aise.core.process_md_repository parser still loads this
     process. The new runtime parser reads the frontmatter directly. -->
- process_id: waterfall_standard_v1
- name: Sequential Waterfall Lifecycle
- work_type: structured_development
- keywords: waterfall, sequential, design-first, documentation, milestone
- summary: A linear and sequential approach to software development where each phase must be completed before the next begins.

## Steps

### phase_1_requirement: Requirement Specification
#### step_requirement_analysis: Requirement Analysis
- agents: product_manager
- description: Read the raw requirement, expand it, and write a system requirement specification to docs/requirement.md. Each requirement is a verifiable usecase the user can test against the system as a black box.
- deliverables: docs/requirement.md

### phase_2_design: Architecture Design
#### step_architecture_design: Architecture Blueprint
- agents: architect
- description: Read docs/requirement.md and produce a complete technical blueprint covering modules, data flow, API contracts, and pseudocode for the key algorithms. Write to docs/architecture.md.
- deliverables: docs/architecture.md

### phase_3_implementation: Implementation
#### step_implement_modules: Per-Module TDD Implementation
- agents: developer
- description: |
    IMPORTANT: The orchestrator must dispatch the developer ONCE PER MODULE,
    not once for all modules. Read docs/architecture.md to identify the list
    of modules, then for each module:
      1. dispatch_task(developer, "Implement module <name>: write tests/test_<name>.py then src/<name>.py.
         This module depends on: <list imports from other modules if any>.")
      2. After the dispatch returns, run the verification_command
      3. If verification fails, re-dispatch with the pytest output
      4. Move to the next module only after the current one passes

    Dispatch ORDER matters: implement base/data modules first (no dependencies),
    then modules that depend on them. Include dependency info in each task description
    so the developer knows what to import.

    Each dispatch should produce exactly 2 files: one test file and one source file.
    This keeps each agent invocation small and focused.
- deliverables: src/, tests/
- verification_command: python -m pytest tests/ -q --tb=short
- on_failure: retry_with_output
- max_retries: 2

#### step_integrate_main: Main Entry Point
- agents: developer
- description: |
    After all modules are implemented, dispatch the developer ONE MORE TIME to write
    the main entry point that wires all modules together:
      dispatch_task(developer, "Write src/main.py — the main entry point that imports
      and initializes all modules (<list the implemented modules>), and provides a
      runnable application. Also write tests/test_main.py to verify the integration.")

    This step ensures the system is runnable as a whole, not just isolated modules.
- deliverables: src/main.py, tests/test_main.py
- verification_command: python -m pytest tests/ -q --tb=short
- on_failure: retry_with_output
- max_retries: 2

### phase_4_verification: Integration & Testing
#### step_integration_test: Integration Testing
- agents: qa_engineer
- description: Read src/ and tests/ to understand the system, identify integration scenarios, then write integration tests to tests/test_integration.py and a brief test plan to docs/integration_test_plan.md. Do not duplicate the developer's unit tests.
- deliverables: tests/test_integration.py, docs/integration_test_plan.md
- verification_command: python -m pytest tests/ -q --tb=short
- on_failure: retry_with_output
- max_retries: 2

### phase_5_delivery: Delivery
#### deliver_report: Final Delivery Report
- agents: project_manager
- description: Compose the final delivery report summarizing requirements, architecture, implementation, testing results, and any open issues. Write to docs/delivery_report.md and call mark_complete with the same content.
- deliverables: docs/delivery_report.md
