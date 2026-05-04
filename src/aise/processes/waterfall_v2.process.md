---
process_id: waterfall_v2
name: Stage-Gated Waterfall (v2)
work_type: structured_development
keywords: waterfall, stage-gate, reviewer, acceptance, fanout
summary: |
  Six-phase waterfall lifecycle with explicit stage gates, cross-role
  reviewers, structured acceptance predicates, and tier-aware phase-internal
  concurrency. Producer failures halt the run; reviewer revise loops are
  bounded and never halt — they at most mark a phase as
  passed-with-unresolved-review.
schema_version: 2

# v2 deliberately has NO budget caps (no max_dispatches, no max_continuations,
# no per_phase_timeout_seconds). Complex projects must be allowed to run
# as long as they need; runaway tasks are surfaced via observability and
# manually abortable, not auto-killed.

terminal_phase: delivery
quality_profile: balanced  # fast | balanced | thorough — tunes revise budgets only

phases:
  # --------------------------------------------------------------------
  - id: requirements
    title: Requirement Specification
    producer: product_manager
    reviewer: architect
    inputs: []
    deliverables:
      - kind: document
        path: docs/requirement.md
        acceptance:
          - file_exists
          - { min_bytes: 2000 }
          - { contains_sections: ["功能需求", "非功能需求", "用例"] }
          - mermaid_validates_via_skill
      - kind: contract
        path: docs/requirement_contract.json
        acceptance:
          - file_exists
          - { schema: schemas/requirement_contract.schema.json }
    review:
      consensus: ALL_PASS
      revise_budget: 3
      on_revise_exhausted: continue_with_marker
      reviewer_questions:
        architect: |
          请评审 docs/requirement.md。判断："是否能仅凭此文档产出完整架构？"
          回答 PASS / REVISE / REJECT，并给出具体 gap list 或阻塞项。

  # --------------------------------------------------------------------
  - id: architecture
    title: Architecture Design
    producer: architect
    reviewer: [developer, qa_engineer]
    inputs:
      - docs/requirement.md
      - docs/requirement_contract.json
    deliverables:
      - kind: document
        path: docs/architecture.md
        acceptance:
          - file_exists
          - { min_bytes: 5000 }
          - mermaid_validates_via_skill
      - kind: contract
        path: docs/stack_contract.json
        acceptance:
          - file_exists
          - { schema: schemas/stack_contract.schema.json }
          - language_supported
      - kind: contract
        path: docs/behavioral_contract.json
        acceptance:
          - file_exists
          - { schema: schemas/behavioral_contract.schema.json }
          - { min_scenarios: 5 }
    review:
      consensus: ALL_PASS
      revise_budget: 3
      on_revise_exhausted: continue_with_marker
      reviewer_questions:
        developer: |
          你能基于 stack_contract.json 实现所有 subsystem.components 吗？
          路径/命名/依赖是否在你的 stack 里能落地？回答 PASS / REVISE / REJECT。
        qa_engineer: |
          behavioral_contract.json 的 scenarios 能用 stack_contract.test_runner
          跑得起来吗？回答 PASS / REVISE / REJECT。

  # --------------------------------------------------------------------
  - id: implementation
    title: Subsystem & Component Implementation
    producer: developer
    reviewer: qa_engineer
    inputs:
      - docs/architecture.md
      - docs/stack_contract.json
    fanout:
      strategy: subsystem_dag
      source_jsonpath: docs/stack_contract.json#/subsystems
      stages:
        - id: skeleton
          tier: T1
          concurrency:
            max_workers: 5
            per_task_retries: 3
            join_policy: ALL_PASS
            on_task_failure_after_retries: phase_halt
        - id: component
          tier: T2
          depends_on: skeleton
          group_by: subsystem
          concurrency:
            max_workers: 5
            per_task_retries: 3
            join_policy: ALL_PASS
            on_task_failure_after_retries: phase_halt
    deliverables:
      - kind: derived
        from: stack_contract
        rule: every_component.file
        acceptance:
          - file_exists
          - { min_bytes: 100 }
          - language_idiomatic_check
      - kind: derived
        from: stack_contract
        rule: every_component.test_file
        acceptance:
          - file_exists
          - { min_bytes: 100 }
    review:
      consensus: ALL_PASS
      revise_budget: 3
      on_revise_exhausted: continue_with_marker
      reviewer_questions:
        qa_engineer: |
          随机抽 3 个 components 验证：(1) 公共 API 是否齐全 (2) test 是否覆盖
          组件核心 method。回答 PASS / REVISE / REJECT，REVISE 给出 gap 列表。

  # --------------------------------------------------------------------
  - id: main_entry
    title: Main Entry Wiring
    producer: developer
    reviewer: qa_engineer
    inputs: [docs/stack_contract.json]
    deliverables:
      - kind: derived
        from: stack_contract
        rule: entry_point
        acceptance:
          - file_exists
          - contains_all_lifecycle_inits
    review:
      consensus: ALL_PASS
      revise_budget: 3
      on_revise_exhausted: continue_with_marker
      reviewer_questions:
        qa_engineer: |
          按 stack_contract.run_command 启动 entry_point 是否能 boot 成功？
          若沙箱无法运行该 runtime，请基于代码静态推断并说明理由。

  # --------------------------------------------------------------------
  - id: verification
    title: Behavioral Scenario Verification
    producer: qa_engineer
    reviewer: project_manager
    inputs:
      - docs/architecture.md
      - docs/behavioral_contract.json
    fanout:
      strategy: scenario_parallel
      source_jsonpath: docs/behavioral_contract.json#/scenarios
      stages:
        - id: scenarios
          tier: T1
          concurrency:
            max_workers: 3
            per_task_retries: 3
            join_policy: ALL_PASS
            on_task_failure_after_retries: phase_halt
          mode_when_runner_unavailable: write_only  # runner_probe → 降级
    deliverables:
      - kind: derived
        from: behavioral_contract
        rule: scenario_test_path
        acceptance:
          - file_exists
          - { min_bytes: 200 }
    review:
      consensus: ALL_PASS
      revise_budget: 3
      on_revise_exhausted: continue_with_marker
      reviewer_questions:
        project_manager: |
          scenarios 是否覆盖 docs/requirement.md 里所有 FR-* 与 NFR-*？
          给出未覆盖列表。回答 PASS / REVISE / REJECT。

  # --------------------------------------------------------------------
  - id: delivery
    title: Final Delivery Report
    producer: project_manager
    reviewer: rd_director
    inputs: []  # delivery 读所有前序 phase tag 与 docs
    deliverables:
      - kind: document
        path: docs/delivery_report.md
        acceptance:
          - file_exists
          - { min_bytes: 1500 }
          - { contains_sections: ["验收结论", "已知 issue", "下一步建议"] }
          - { prior_phases_summarized: 5 }
    review:
      consensus: ALL_PASS
      revise_budget: 3
      on_revise_exhausted: continue_with_marker
      reviewer_questions:
        rd_director: |
          可发布吗？YES / REVISE / REJECT。REJECT 必须给出阻塞项。
---

# Stage-Gated Waterfall (v2)

This process file is the **single source of truth** for phase definition,
acceptance criteria, reviewer assignment, and intra-phase concurrency.
The runtime's PhaseExecutor reads this file and walks the phases —
no phase logic is hardcoded in Python.

## Key invariants

1. **No budgets**: there is no wall-clock, no max_dispatches, no max_turns.
   Complex projects must be allowed to run as long as they need.
2. **Producer halts the run**: a producer's per-task retries (3) exhausting
   without acceptance gate pass is a hard fail → `aise resume_project`.
3. **Reviewer never halts the run**: reviewer REVISE loops are bounded by
   `revise_budget`. Exhaustion produces `passed_with_unresolved_review`
   and execution continues to the next phase.
4. **Strict ALL_PASS for fanout stages**: any sub-task in a fanout stage
   that fails after its 3 retries triggers `on_task_failure_after_retries:
   phase_halt`. No quorum, no best-effort.
5. **Runner-aware verification**: when the project's `test_runner` is not
   available in the sandbox, the verification phase auto-degrades to
   `write_only` mode (writes scenario tests but does not require they run).
6. **Reviewer feedback is prepended verbatim** to the producer's next
   prompt; no PolicyBackend filtering.

## Phase tag conventions

- `phase_<n>_<id>_done` — phase completed with reviewer ALL_PASS
- `phase_<n>_<id>_done_review_pending` — phase completed but reviewer
  revise budget exhausted with one or more reviewers still REVISE/REJECT
- (no rollback tag exists; rollback is not implemented)

## Fanout strategies

- `subsystem_dag`: 2-stage (skeleton → component) DAG over
  `stack_contract.json#/subsystems`. Component stage is grouped by
  subsystem; intra-group serial, cross-group parallel.
- `scenario_parallel`: flat parallel fanout over
  `behavioral_contract.json#/scenarios`.

## Acceptance predicates

See `src/aise/runtime/predicates.py` (commit c2) for the registered
predicates. New predicates can be added without touching the process
file by registering them in the predicate registry.
