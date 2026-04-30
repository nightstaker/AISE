---
process_id: waterfall_standard_v1
name: Sequential Waterfall Lifecycle
work_type: structured_development
keywords: waterfall, sequential, design-first, documentation, milestone
summary: A linear and sequential approach to software development where each phase must be completed before the next begins. Default choice for most structured projects.
caps:
  # ``max_dispatches`` is the upper bound; the runtime auto-scales
  # the *floor* per project as
  # ``Σ(1 + len(components)) + DISPATCH_FLOOR_BUFFER``
  # (see ``src/aise/runtime/runtime_config.py`` and
  # ``ProjectSession._auto_scale_dispatch_floor``), so a 5-subsystem /
  # 32-component project gets ~50–60 dispatches of headroom, well
  # under this 128 cap. Bumping this higher only matters for very
  # large projects (≥ 8 subsystems with deep component trees).
  max_dispatches: 128
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
#### step_implement_modules: Subsystem Fan-Out Implementation
- agents: developer
- description: |
    The orchestrator MUST issue exactly ONE tool call here:

      dispatch_subsystems(phase="implementation")

    The runtime reads docs/stack_contract.json (produced by the
    architect in phase 2) and fans out in two stages:

      Stage 1 — skeleton: one dispatch per subsystem, producing
      public API signatures + barrel files (no logic, no tests).
      Skeletons across subsystems run in parallel, throttled by
      safety_limits.max_concurrent_subsystem_dispatches.

      Stage 2 — components: one dispatch per
      subsystems[].components[] entry, each producing exactly the
      (source, test) file pair declared in the contract. Components
      across the entire project are eligible to run in parallel as
      soon as their parent subsystem's skeleton completes.

    Do NOT call dispatch_task or dispatch_tasks_parallel for
    per-module implementation here — the runtime owns the fan-out
    decision because the orchestrator LLM cannot reliably emit N
    parallel tool_calls in one inference, which serialised the old
    flow into N sequential ReAct cycles.

    On return, the verification_command runs once over the whole
    src/ + tests/ tree.
- deliverables: src/, tests/
- verification_command: python -m pytest tests/ -q --tb=short
- on_failure: retry_with_output
- max_retries: 2

#### step_integrate_main: Main Entry Point
- agents: developer
- description: |
    After dispatch_subsystems completes, dispatch the developer
    once more to wire the runnable entry point per the
    `entry_point_wiring` skill:

      dispatch_task(developer, "Write the main entry file declared
      at docs/stack_contract.json#/entry_point following the
      entry_point_wiring skill — Step A construct every subsystem
      from src/, Step B iterate
      docs/stack_contract.json#/lifecycle_inits[] invoking each
      <attr>.<method>() in order, Step C enter the framework's
      native main loop using the framework recorded in
      stack_contract.json#/framework_backend (or framework_frontend
      for UI projects), Step D add the lifecycle self-check
      assertion. Do NOT write defensive `if self._<x> is None: return`
      guards in render/update/handler methods — raise RuntimeError
      instead. Also add the integration test that boots the entry
      point end-to-end against a real headless surface (NOT a
      MagicMock display) when ui_required is true.")

    This is a single dispatch_task — the entry point is one file
    pair, not a fan-out. The runtime exercises the chosen stack at
    boot time, which is what guarantees the framework choice is
    real and not just declared in prose. After the dispatch returns,
    the post-phase safety net runs the entry_point_lifecycle layer-B
    check; a missing initialize() call re-dispatches the developer
    with the precise diff.
- deliverables: src/main.<ext>, tests/test_main.<ext>
- verification_command: python -m pytest tests/ -q --tb=short
- on_failure: retry_with_output
- max_retries: 2

### phase_4_verification: Integration & Testing
#### step_integration_test: Integration Testing
- agents: qa_engineer
- description: |
    Read src/ and tests/ to understand the system, identify
    integration scenarios, then write integration tests to
    tests/test_integration.py and a brief test plan to
    docs/integration_test_plan.md. Do not duplicate the developer's
    unit tests.

    For UI-required projects
    (`docs/stack_contract.json#/ui_required == true`), the
    integration tests MUST run against a real headless surface
    (`SDL_VIDEODRIVER=dummy` + real `pygame.Surface`,
    `QT_QPA_PLATFORM=offscreen` + real `QImage`, Playwright for
    web), with at least one pixel-level invariant assertion.
    `MagicMock`-ing the display surface is forbidden — see the
    `tdd` skill anti-patterns. Then run the Check 7.3 pixel-smoke
    procedure documented in qa_engineer.md and record the
    `pixel_smoke` block in `docs/qa_report.json`. The post-phase
    safety net runs the `ui_smoke_frame` layer-B check on the
    captured screenshot; a blank frame (non_bg_samples below
    threshold) re-dispatches the qa_engineer.
- deliverables: tests/test_integration.py, docs/integration_test_plan.md, artifacts/smoke_frame_0.png (UI-required projects)
- verification_command: python -m pytest tests/ -q --tb=short
- on_failure: retry_with_output
- max_retries: 2

### phase_5_delivery: Delivery
#### deliver_report: Final Delivery Report
- agents: project_manager
- description: Compose the final delivery report summarizing requirements, architecture, implementation, testing results, and any open issues. Write to docs/delivery_report.md and call mark_complete with the same content.
- deliverables: docs/delivery_report.md
